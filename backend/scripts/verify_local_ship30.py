"""Skill B on the Local provider — closes O15.

Skill B is the honest test of a local model, not Skill A. `README.md` warns
that a small model will not hit 1250 words as reliably as Claude, and the §8.2
length guard exists precisely for that. `llama3.2:1b` could never exercise it
meaningfully; `llama3.1:8b-instruct-q4_K_M` is the configured model and the one
the claim should be measured against.

Measures what the UI actually surfaces: word count against the 1125-1375 band,
whether the continuation pass fired, the format constraints the prompt makes
non-negotiable, and citation coverage. Cloud numbers from Phase 3 are printed
alongside so the gap is visible rather than asserted.
"""

from __future__ import annotations

import asyncio
import re
import sys
import time

sys.path.insert(0, ".")

from app.agent.orchestrator import SHIP30_MAX, SHIP30_MIN  # noqa: E402
from app.agent.retriever import retrieve  # noqa: E402
from app.agent.types import SKILL_CONFIG  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import dispose_engine, get_session_factory, init_engine  # noqa: E402
from app.agent import prompts  # noqa: E402
from app.llm import registry  # noqa: E402
from app.llm.base import Msg, StreamResult, Usage  # noqa: E402

TOPIC = "why retention beats acquisition"

# Phase 3, cloud (claude-sonnet-4-6), same topic and prompt.
CLOUD_BASELINE = {
    "words": [1318, 1319, 1294],
    "takeaways": 1,
    "bold": "13-19",
    "bullets": "10-16",
    "citations": "8-9",
    "latency_s": "58-75",
}


def analyse(text: str) -> dict:
    return {
        "words": len(text.split()),
        "bold": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "bullets": len(re.findall(r"^\s*[-*] ", text, re.M)),
        "takeaways": text.count("The takeaway:"),
        "citations": len(set(re.findall(r"\[(\d+)\]", text))),
        "has_hook": bool(text.strip()) and not text.strip().lower().startswith(
            "in today's"
        ),
    }


async def main() -> None:
    settings = get_settings()
    init_engine(settings)

    status = await registry.get_status("local", settings)
    print(f"local provider : available={status.available}  model={status.model}")
    if not status.available:
        print(f"  reason       : {status.reason}")
        await dispose_engine()
        sys.exit(1)

    provider = registry.get_provider("local", settings)
    config = SKILL_CONFIG["ship30"]
    print(f"num_ctx        : {provider.num_ctx}")
    print(f"max_tokens     : {config.max_tokens}\n")

    async with get_session_factory()() as db:
        t0 = time.monotonic()
        result = await retrieve(db, settings, TOPIC, top_k=config.top_k)
        t_retrieve = time.monotonic() - t0
        print(f"retrieved {len(result.chunks)} chunks in {t_retrieve:.1f}s")

        system = prompts.SHIP30_SYSTEM
        user = prompts.ship30_user(result.chunks, TOPIC)
        res = StreamResult(usage=Usage())

        t0 = time.monotonic()
        first_token_at = None
        parts: list[str] = []
        async for delta in provider.stream_chat(
            system,
            [Msg("user", user)],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            result=res,
        ):
            if first_token_at is None:
                first_token_at = time.monotonic() - t0
                print(f"first token at {first_token_at:.1f}s")
            parts.append(delta)

        draft = "".join(parts)
        t_draft = time.monotonic() - t0
        d = analyse(draft)
        print(
            f"draft          : {d['words']} words in {t_draft:.0f}s "
            f"({d['words'] / t_draft:.1f} w/s)  finish={res.finish_reason}"
        )

        # §8.2 length guard: at most one continuation pass, below 1125 words.
        repaired = draft
        fired = False
        if res.finish_reason == "stop" and d["words"] < SHIP30_MIN:
            fired = True
            short_by = 1250 - d["words"]
            print(f"length guard   : FIRED (short by ~{short_by} words)")
            t1 = time.monotonic()
            system_r = prompts.SHIP30_REPAIR_SYSTEM.format(shortfall=short_by)
            user_r = (
                f"{prompts.format_transcripts(result.chunks)}\n\n<topic>{TOPIC}</topic>"
                f"\n\n<draft>\n{draft}\n</draft>"
            )
            cont = (
                await provider.complete(
                    system_r,
                    [Msg("user", user_r)],
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
            ).strip()
            if cont:
                repaired = f"{draft}\n\n{cont}"
            print(
                f"  continuation : +{len(cont.split())} words in "
                f"{time.monotonic() - t1:.0f}s"
            )
        else:
            print("length guard   : not fired")

    f = analyse(repaired)
    in_band = SHIP30_MIN <= f["words"] <= SHIP30_MAX

    print("\n" + "=" * 62)
    print(f"{'metric':<14}{'LOCAL 8B':>14}{'CLOUD (Phase 3)':>22}")
    print("-" * 62)
    print(f"{'words':<14}{f['words']:>14}{str(CLOUD_BASELINE['words']):>22}")
    print(f"{'in 1125-1375':<14}{str(in_band):>14}{'True (3/3)':>22}")
    print(f"{'takeaways':<14}{f['takeaways']:>14}{CLOUD_BASELINE['takeaways']:>22}")
    print(f"{'bold phrases':<14}{f['bold']:>14}{CLOUD_BASELINE['bold']:>22}")
    print(f"{'bullets':<14}{f['bullets']:>14}{CLOUD_BASELINE['bullets']:>22}")
    print(f"{'citations':<14}{f['citations']:>14}{CLOUD_BASELINE['citations']:>22}")
    print(f"{'guard fired':<14}{str(fired):>14}{'True (1 of 3)':>22}")
    print("=" * 62)

    print("\n--- opening 3 lines ---")
    for line in [ln for ln in repaired.strip().split("\n") if ln.strip()][:3]:
        print(f"  {line[:96]}")
    print("\n--- closing 2 lines ---")
    for line in [ln for ln in repaired.strip().split("\n") if ln.strip()][-2:]:
        print(f"  {line[:96]}")

    await dispose_engine()


asyncio.run(main())
