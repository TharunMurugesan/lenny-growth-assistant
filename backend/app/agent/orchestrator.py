"""The chat pipeline — architecture.md §3.

    route → retrieve → generate → parse → persist

Emits the §6 SSE event sequence as it goes. Three ordering guarantees the UI
depends on, enforced here rather than assumed:

  * `meta` is always first and always precedes any token, so the skill badge
    renders before text arrives.
  * `citations` is emitted after the prose but before `done`, so the sources
    block renders beneath a completed answer.
  * Exactly one of `done` or a terminal `error` ends every stream.

Persistence timing is deliberate. The user message is written *before*
generation, so a crash mid-stream never loses the user's input. The assistant
message is written once, after the stream terminates — with whatever partial
content exists if it ended early, flagged honestly via `finish_reason`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import intent_router, prompts
from app.agent.retriever import retrieve
from app.agent.types import (
    SKILL_CONFIG,
    GenerationOutcome,
    RetrievedChunk,
    RouteDecision,
)
from app.config import Settings
from app.llm.base import Msg, StreamResult, Usage
from app.models import Message, Session
from app.utils.artifacts import ArtifactParser, EventKind
from app.utils.errors import AppError, InternalError, RetrievalEmpty
from app.utils.sse import frame

log = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[(\d{1,2})\]")
HISTORY_TURNS = 6

# Skill B length guard (§8.2). Target 1250 words, ±10%.
SHIP30_TARGET = 1250
SHIP30_MIN = 1125
SHIP30_MAX = 1375


def _word_count(text: str) -> int:
    return len(text.split())


async def _load_history(db: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    rows = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_TURNS)
    )
    return list(reversed(rows.scalars().all()))


def _to_msgs(history: list[Message]) -> list[Msg]:
    return [
        Msg(role="user" if m.role == "user" else "assistant", content=m.content)
        for m in history
        if m.role in ("user", "assistant") and m.content
    ]


def _validate_citations(
    text: str, chunks: list[RetrievedChunk]
) -> tuple[str, list[dict[str, Any]]]:
    """Strip markers with no corresponding chunk; return only cited sources.

    §8.1: a marker with no chunk behind it is stripped rather than shipped, and
    the citations event reflects what was actually *used*, not what was merely
    retrieved. A sources list padded with unused chunks is a subtler lie than a
    missing one.
    """
    if not chunks:
        return CITATION_RE.sub("", text).strip(), []

    used: dict[int, RetrievedChunk] = {}
    valid = range(1, len(chunks) + 1)

    def keep(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if n in valid:
            used[n] = chunks[n - 1]
            return match.group(0)
        return ""  # dangling marker — drop it

    cleaned = CITATION_RE.sub(keep, text)

    # Renumber so the rendered list is 1..N contiguous even if the model cited
    # [2] and [5] only.
    citations: list[dict[str, Any]] = []
    remap: dict[int, int] = {}
    for new_n, old_n in enumerate(sorted(used), start=1):
        remap[old_n] = new_n
        citations.append(used[old_n].as_citation(new_n))

    if remap != {k: k for k in remap}:
        cleaned = CITATION_RE.sub(
            lambda m: f"[{remap[int(m.group(1))]}]" if int(m.group(1)) in remap else "",
            cleaned,
        )

    return cleaned.strip(), citations


def _build_prompt(
    decision: RouteDecision,
    chunks: list[RetrievedChunk],
    message: str,
    provider_name: str,
    model: str,
) -> tuple[str, str]:
    """(system, user) for the routed skill."""
    if decision.skill == "qa":
        return prompts.QA_SYSTEM, prompts.qa_user(chunks, message)
    if decision.skill == "ship30":
        return prompts.SHIP30_SYSTEM, prompts.ship30_user(chunks, message)
    if decision.skill == "artifact":
        return prompts.ARTIFACT_SYSTEM, prompts.artifact_user(chunks, message)
    return prompts.meta_system(provider_name, model), message


async def _ship30_repair(
    provider: Any, draft: str, chunks: list[RetrievedChunk], topic: str
) -> str:
    """One continuation pass when the essay came in short (§8.2).

    At most one. Iterating to hit an exact count burns latency and tokens for
    diminishing returns, and every extra pass is another chance to drift off
    the source material.
    """
    shortfall = SHIP30_TARGET - _word_count(draft)
    system = prompts.SHIP30_REPAIR_SYSTEM.format(shortfall=shortfall)
    user = (
        f"{prompts.format_transcripts(chunks)}\n\n<topic>{topic}</topic>\n\n"
        f"<draft>\n{draft}\n</draft>"
    )
    return await provider.complete(
        system, [Msg("user", user)], temperature=0.7, max_tokens=SKILL_CONFIG["ship30"].max_tokens
    )


async def run_chat(
    *,
    db: AsyncSession,
    settings: Settings,
    provider: Any,
    session: Session,
    user_message: str,
    llm_provider_name: str,
    skill_override: str | None,
    is_disconnected: Any,
) -> AsyncIterator[str]:
    """Drive one chat turn, yielding SSE frames."""
    started = time.monotonic()
    outcome = GenerationOutcome()
    parser = ArtifactParser()
    artifact_id = uuid.uuid4().hex[:12]
    assistant_id: uuid.UUID | None = None
    terminal_sent = False

    try:
        # --- persist the user turn before anything can fail --------------
        history = await _load_history(db, session.id)
        db.add(Message(session_id=session.id, role="user", content=user_message))
        await db.commit()

        previous_skill = next(
            (m.skill for m in reversed(history) if m.role == "assistant" and m.skill), None
        )

        # --- route -------------------------------------------------------
        t_route = time.monotonic()
        decision = await intent_router.route(
            user_message,
            provider=provider,
            history=_to_msgs(history),
            previous_skill=previous_skill,
            skill_override=skill_override,
        )
        log.info(
            "classify",
            extra={
                "skill": decision.skill,
                "tier": decision.tier,
                "confidence": round(decision.confidence, 2),
                "latency_ms": int((time.monotonic() - t_route) * 1000),
            },
        )

        config = SKILL_CONFIG[decision.skill]
        assistant_id = uuid.uuid4()

        yield frame(
            "meta",
            {
                "message_id": str(assistant_id),
                "session_id": str(session.id),
                "provider": llm_provider_name,
                "model": provider.chat_model,
                **decision.as_meta(),
            },
        )

        # --- retrieve ----------------------------------------------------
        chunks: list[RetrievedChunk] = []
        degraded_note = None
        if decision.needs_retrieval and config.retrieves:
            try:
                result = await retrieve(
                    db, settings, decision.search_query, top_k=config.top_k
                )
                chunks = result.chunks
                degraded_note = result.reason
            except RetrievalEmpty:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("retrieval failed", extra={"error": type(exc).__name__})

        # --- Skill A honest decline (a success path, not an error) -------
        if decision.skill == "qa" and not chunks:
            text = prompts.DECLINE_TEMPLATE
            for piece in text.split("\n"):
                yield frame("token", {"text": piece + "\n"})
            outcome.content = text
            outcome.word_count = _word_count(text)
            outcome.citations = []
            yield frame("citations", {"citations": []})
        else:
            system, user = _build_prompt(
                decision, chunks, user_message, llm_provider_name, provider.chat_model
            )
            stream_result = StreamResult(usage=Usage())
            emitted_artifact = False

            async for delta in provider.stream_chat(
                system,
                [Msg("user", user)],
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                result=stream_result,
            ):
                if await is_disconnected():
                    # §3 cancellation: break, persist the partial, no orphaned
                    # upstream request and no lost text.
                    outcome.finish_reason = "client_disconnect"
                    log.info("client disconnected mid-stream")
                    break

                for event in parser.feed(delta):
                    if event.kind is EventKind.TEXT:
                        yield frame("token", {"text": event.text})
                    elif event.kind is EventKind.ARTIFACT_START:
                        emitted_artifact = True
                        yield frame(
                            "artifact_start",
                            {
                                "artifact_id": artifact_id,
                                "type": event.artifact_type,
                                "title": event.title,
                            },
                        )
                    elif event.kind is EventKind.ARTIFACT_DELTA:
                        yield frame(
                            "artifact_delta",
                            {"artifact_id": artifact_id, "text": event.text},
                        )
                    elif event.kind is EventKind.ARTIFACT_END:
                        yield frame(
                            "artifact_end",
                            {
                                "artifact_id": artifact_id,
                                "bytes": len(parser.artifact_content.encode()),
                                "complete": event.complete,
                            },
                        )

            for event in parser.finish():
                if event.kind is EventKind.TEXT:
                    yield frame("token", {"text": event.text})
                elif event.kind is EventKind.ARTIFACT_DELTA:
                    yield frame(
                        "artifact_delta", {"artifact_id": artifact_id, "text": event.text}
                    )
                elif event.kind is EventKind.ARTIFACT_END:
                    emitted_artifact = True
                    yield frame(
                        "artifact_end",
                        {
                            "artifact_id": artifact_id,
                            "bytes": len(parser.artifact_content.encode()),
                            "complete": event.complete,
                        },
                    )

            if outcome.finish_reason != "client_disconnect":
                outcome.finish_reason = stream_result.finish_reason
            outcome.token_usage = stream_result.usage.as_dict()
            prose = parser.prose

            # --- Skill B length guard --------------------------------------
            if (
                decision.skill == "ship30"
                and outcome.finish_reason == "stop"
                and _word_count(prose) < SHIP30_MIN
            ):
                short_by = SHIP30_TARGET - _word_count(prose)
                log.info("ship30 below target, one repair pass",
                         extra={"words": _word_count(prose), "short_by": short_by})
                try:
                    # The repair returns ONLY the continuation, never the whole
                    # essay. An earlier version asked for the complete text and
                    # tried to stream just the changed tail — but a rewrite
                    # rarely starts with the original prefix, so the fallback
                    # streamed the entire essay a second time and the reader
                    # got it twice. Appending a continuation is both what §8.2
                    # specifies ("without restating") and the only shape that
                    # streams correctly.
                    continuation = (
                        await _ship30_repair(provider, prose, chunks, decision.search_query)
                    ).strip()
                    if continuation:
                        yield frame("token", {"text": "\n\n"})
                        yield frame("token", {"text": continuation})
                        prose = f"{prose}\n\n{continuation}"
                except AppError as exc:
                    # §12.3: length guard fails → return the draft with its
                    # true count. Never claim compliance.
                    log.warning("ship30 repair failed", extra={"code": exc.code})

            # --- citations ---------------------------------------------------
            if decision.skill in ("qa", "ship30"):
                prose, citations = _validate_citations(prose, chunks)
                outcome.citations = citations
                yield frame("citations", {"citations": citations})

            outcome.content = prose
            outcome.word_count = _word_count(prose)

            if emitted_artifact and parser.artifact_content:
                outcome.artifact_type = parser.artifact_type or "none"
                outcome.artifact_content = parser.artifact_content
                outcome.artifact_title = parser.artifact_title

        # --- persist the assistant turn ---------------------------------
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            db.add(
                Message(
                    id=assistant_id,
                    session_id=session.id,
                    role="assistant",
                    content=outcome.content,
                    artifact_type=outcome.artifact_type,
                    artifact_content=outcome.artifact_content,
                    artifact_title=outcome.artifact_title,
                    skill=decision.skill,
                    provider=llm_provider_name,
                    model=provider.chat_model,
                    citations=outcome.citations,
                    token_usage=outcome.token_usage,
                    word_count=outcome.word_count,
                    finish_reason=outcome.finish_reason,
                )
            )
            if len(history) == 0:
                # An explicit UPDATE, not `session.title = ...`.
                #
                # FastAPI tears down a `yield` dependency once the route
                # function returns, which for a StreamingResponse happens
                # *before* this generator finishes. Closing the session
                # detaches every object loaded earlier, so the `Session` row
                # here is `modified` but no longer in `db.dirty` — the commit
                # silently emits no UPDATE. Newly `add()`ed rows are unaffected,
                # which is why the assistant message persisted and only the
                # title vanished. Statements do not depend on the identity map.
                new_title = user_message.strip()[:120] or "New chat"
                await db.execute(
                    update(Session)
                    .where(Session.id == session.id)
                    .values(title=new_title)
                )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            # §12.3: a write failure after generation must not cost the user
            # the answer they already read.
            await db.rollback()
            log.error("failed to persist assistant message", exc_info=exc)
            yield frame(
                "error",
                {
                    "code": "DATABASE_UNAVAILABLE",
                    "message": "The answer was generated but could not be saved.",
                    "retryable": True,
                },
            )

        yield frame(
            "usage",
            {
                **(outcome.token_usage or {"input_tokens": 0, "output_tokens": 0}),
                "latency_ms": latency_ms,
                "word_count": outcome.word_count,
                **({"degraded": degraded_note} if degraded_note else {}),
            },
        )
        terminal_sent = True
        yield frame(
            "done",
            {"message_id": str(assistant_id), "finish_reason": outcome.finish_reason},
        )

    except asyncio.CancelledError:
        raise
    except AppError as exc:
        if not terminal_sent:
            log.warning("stream failed", extra={"code": exc.code})
            yield frame(
                "error",
                {"code": exc.code, "message": exc.message, "retryable": exc.retryable},
            )
    except Exception as exc:  # noqa: BLE001
        if not terminal_sent:
            log.exception("unhandled error in chat pipeline")
            err = InternalError("Something went wrong generating that response.")
            yield frame(
                "error",
                {"code": err.code, "message": err.message, "retryable": False},
            )
