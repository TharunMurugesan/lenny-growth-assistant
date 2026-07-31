"""`POST /api/chat` — architecture.md §5.7.

**Phase 2 scope.** README.md's phase table places SSE streaming, the intent
router, and Skills A/B/C in Phase 3. What lands here is the entire pre-stream
half of the endpoint, which §5.7 requires to happen *before* the stream opens:

    payload validation → session ownership → provider resolution

All three are the paths that must return ordinary JSON rather than an SSE
event, because a client cannot otherwise distinguish "bad request" from "bad
answer". They are therefore fully implemented and independently testable now.

Past that point the request raises `NotImplementedYet` (501). Two deliberate
choices in that refusal:

  * It is not a fabricated answer. A stub that streamed placeholder prose would
    make the endpoint look finished while being useless, and the failure would
    surface in Phase 4 against the real UI.
  * The user message is **not** persisted. §3 writes it before generation so a
    mid-stream crash cannot lose it — but with no generation to follow, that
    would accumulate user turns that never receive a reply and corrupt the
    history the sidebar reads. Persistence moves here with the generation it
    protects.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import AppSettings, CurrentUser, DbSession
from app.llm import registry
from app.models import Session
from app.schemas import ChatRequest
from app.utils.errors import NotImplementedYet, SessionNotFound

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> None:
    # Ownership first: the same 404 for "no such session" and "someone else's
    # session", so this is not an existence oracle (§13).
    session = await db.scalar(
        select(Session).where(
            Session.id == payload.session_id, Session.user_id == user.id
        )
    )
    if session is None:
        raise SessionNotFound("That conversation does not exist.")

    # Raises ProviderUnavailable (503) naming the missing prerequisite.
    provider = await registry.resolve_provider(payload.llm_provider, settings)

    log.info(
        "chat request accepted",
        extra={
            "session_id": str(session.id),
            "provider": provider.name,
            "model": provider.model,
            "skill_override": payload.skill_override,
            "message_chars": len(payload.message),
        },
    )

    raise NotImplementedYet(
        "Chat generation is not wired up yet — it lands in Phase 3 along with "
        "the intent router, retrieval, and SSE streaming. Your request was "
        "valid and the provider is reachable.",
        detail={
            "provider": provider.name,
            "model": provider.model,
            "phase": 3,
        },
    )
