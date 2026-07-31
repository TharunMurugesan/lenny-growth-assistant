"""Two-tier intent routing — architecture.md §7.

    Tier 0  guardrails + explicit override      (no model call)
    Tier 1  deterministic heuristics, ~0ms      (no model call)
    Tier 2  small-model classifier               (one model call)

The reason an LLM tier earns its latency is that it does *two* jobs: it
classifies, and it rewrites the message into a standalone `search_query`.
"Make it longer" retrieves nothing on its own; rewritten against the last two
turns it retrieves the original topic. That single field is the difference
between follow-up turns working and failing.

Tier 1 is precision-first on purpose: a pattern fires only when the intent is
unambiguous, and recall is Tier 2's problem. A heuristic that guesses is worse
than one that abstains, because a wrong guess skips the tier that would have
been right.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agent.types import RouteDecision, SkillName
from app.llm.base import Msg

log = logging.getLogger(__name__)

CONFIDENCE_FLOOR = 0.6
MAX_FOLLOWUP_WORDS = 8

# --- Tier 1 patterns (§7.2) ---------------------------------------------

SHIP30_PATTERNS = re.compile(
    r"\b(ship\s?30(for30)?|1250\s*word|write (me )?an? essay|long[- ]form post"
    r"|newsletter post|linkedin post|thread about)\b",
    re.IGNORECASE,
)
ARTIFACT_PATTERNS = re.compile(
    r"\b(html|css|landing page|dashboard|mockup|wireframe|component|svg|render"
    r"|one[- ]pager|cheat ?sheet|checklist|build me a|design a page)\b",
    re.IGNORECASE,
)
META_PATTERNS = re.compile(
    r"^\s*(who are you|what can you do|which model( is this)?|what are you"
    r"|hello|hi|hey|thanks|thank you)\s*[!?.]*\s*$",
    re.IGNORECASE,
)

# Ambiguity rule (§7.2): artifact wins on a *format* word, ship30 on a *length*
# word. Anything still ambiguous falls to Tier 2 rather than guessing.
FORMAT_WORDS = re.compile(r"\b(html|page|mockup|dashboard|wireframe|svg|css)\b", re.I)
LENGTH_WORDS = re.compile(r"\b(1250|essay|long[- ]form|word)\b", re.I)

# Short modifiers that should inherit the previous skill (§7.4).
FOLLOWUP_PATTERNS = re.compile(
    r"^\s*(make it|try again|again|shorter|longer|expand|continue|more of that"
    r"|add|redo|rewrite|tweak|change|what about|same but|do that)\b",
    re.IGNORECASE,
)

CLASSIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["qa", "ship30", "artifact", "meta"]},
        # anyOf, not `{"type": ["string","null"], "enum": [...]}` — that form is
        # rejected with "Enum value 'html' does not match declared type
        # ['string','null']". The failure was invisible in normal operation:
        # the router caught it and fell back to qa, so every request still
        # answered while Tier 2 was entirely dead.
        "artifact_type": {
            "anyOf": [
                {"type": "string", "enum": ["html", "markdown"]},
                {"type": "null"},
            ]
        },
        "confidence": {"type": "number"},
        "search_query": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["intent", "artifact_type", "confidence", "search_query", "rationale"],
    "additionalProperties": False,
}

CLASSIFIER_SYSTEM = """\
You classify a user message for a research assistant grounded in transcripts of
Lenny's Podcast (product management and growth interviews).

Choose exactly one intent:
- "qa"       - a question to answer from the transcripts. This is also the
               correct choice for questions that are simply OFF-TOPIC for this
               corpus (cooking, sports, car repair). Do NOT route those to
               "meta" - the retrieval layer detects that nothing relevant
               exists and produces a proper grounded decline. Routing them to
               "meta" skips that and answers from the wrong place.
- "ship30"   - a request for a long-form (~1250 word) essay or post.
- "artifact" - a request to BUILD something renderable: an HTML page, a
               dashboard, a mockup, a checklist, a one-pager.
- "meta"     - ONLY a greeting, or a question about this assistant itself
               ("who are you", "what can you do", "which model is this").
               Never use "meta" merely because a question is unanswerable.

Also produce "search_query": a standalone retrieval query for the transcripts.
Resolve pronouns and ellipsis using the conversation so far, so the query makes
sense on its own. For "make it longer" after an essay about retention, the
query is about retention - not the words "make it longer".

Set "artifact_type" to "html" for visual or structural output, "markdown" for
document-style output, and null when the intent is not "artifact".

"confidence" is 0..1 - how sure you are of the intent.

Keep "rationale" to at most 12 words. It is a debugging aid, not an argument -
a long one risks truncating the JSON object before it closes."""


def _tier1(message: str) -> tuple[SkillName, float] | None:
    """Deterministic patterns. Returns None when not confident."""
    if META_PATTERNS.match(message):
        return "meta", 0.95

    ship = bool(SHIP30_PATTERNS.search(message))
    art = bool(ARTIFACT_PATTERNS.search(message))

    if ship and art:
        has_format = bool(FORMAT_WORDS.search(message))
        has_length = bool(LENGTH_WORDS.search(message))
        if has_format and not has_length:
            return "artifact", 0.8
        if has_length and not has_format:
            return "ship30", 0.8
        return None  # genuinely ambiguous — let Tier 2 decide

    if ship:
        return "ship30", 0.9
    if art:
        return "artifact", 0.9
    return None


def _is_followup(message: str) -> bool:
    """A short modifier that carries no topical signal of its own."""
    words = message.split()
    return len(words) <= MAX_FOLLOWUP_WORDS and bool(FOLLOWUP_PATTERNS.match(message))


def _artifact_type_for(message: str) -> str:
    """Default artifact type when the heuristic tier routed (§8.3)."""
    if re.search(r"\b(checklist|one[- ]pager|framework|table|cheat ?sheet)\b", message, re.I):
        return "markdown"
    return "html"


def _context_block(history: list[Msg], message: str) -> str:
    """Last two turns plus the new message, for pronoun resolution."""
    lines = [f"{m.role}: {m.content[:600]}" for m in history[-2:]]
    lines.append(f"user: {message}")
    return "\n".join(lines)


async def route(
    message: str,
    *,
    provider: Any,
    history: list[Msg] | None = None,
    previous_skill: str | None = None,
    skill_override: str | None = None,
) -> RouteDecision:
    """Decide which skill handles this message, and what to retrieve for it."""
    history = history or []
    message = message.strip()

    # --- Tier 0: an explicit user choice is never second-guessed --------
    if skill_override:
        return RouteDecision(
            skill=skill_override,  # type: ignore[arg-type]
            search_query=message,
            confidence=1.0,
            tier="override",
            artifact_type=(
                _artifact_type_for(message) if skill_override == "artifact" else None
            ),  # type: ignore[arg-type]
            needs_retrieval=skill_override != "meta",
            rationale="explicit skill_override",
        )

    # --- §7.4 follow-up inheritance -------------------------------------
    # Checked before Tier 1 because "make it longer" contains no signal that
    # Tier 1 could act on, and reclassifying it lands in qa — returning a
    # 200-word answer where an essay was expected.
    inherit = (
        previous_skill
        if previous_skill and previous_skill != "meta" and _is_followup(message)
        else None
    )

    # --- Tier 1: heuristics ---------------------------------------------
    hit = _tier1(message)
    if hit and not inherit:
        skill, confidence = hit
        return RouteDecision(
            skill=skill,
            search_query=message,
            confidence=confidence,
            tier="heuristic",
            artifact_type=_artifact_type_for(message) if skill == "artifact" else None,  # type: ignore[arg-type]
            needs_retrieval=skill != "meta",
            rationale="deterministic pattern",
        )

    # --- Tier 2: LLM classifier ------------------------------------------
    try:
        raw = await provider.classify(
            CLASSIFIER_SYSTEM, _context_block(history, message), CLASSIFIER_SCHEMA
        )
        intent = str(raw.get("intent", "qa")).lower()
        confidence = float(raw.get("confidence") or 0.0)
        search_query = (raw.get("search_query") or "").strip() or message
        artifact_type = raw.get("artifact_type")
        if artifact_type not in ("html", "markdown"):
            artifact_type = None

        if intent not in ("qa", "ship30", "artifact", "meta"):
            intent, confidence = "qa", 0.0

        # §7.3: below the floor, fall back to qa with the raw message. Grounded
        # Q&A is the most constrained skill, so a misroute into it degrades
        # gracefully rather than producing a confident wrong format.
        if confidence < CONFIDENCE_FLOOR:
            log.info(
                "classifier below confidence floor",
                extra={"intent": intent, "confidence": confidence},
            )
            return RouteDecision(
                skill=inherit or "qa",  # type: ignore[arg-type]
                search_query=search_query,
                confidence=confidence,
                tier="fallback",
                artifact_type=None,
                needs_retrieval=(inherit or "qa") != "meta",
                rationale="confidence below floor; defaulted",
            )

        skill: SkillName = inherit or intent  # type: ignore[assignment]
        if skill == "artifact" and artifact_type is None:
            artifact_type = _artifact_type_for(message)

        return RouteDecision(
            skill=skill,
            search_query=search_query,
            confidence=confidence,
            tier="inherited" if inherit else "llm",
            artifact_type=artifact_type if skill == "artifact" else None,  # type: ignore[arg-type]
            needs_retrieval=skill != "meta",
            rationale=str(raw.get("rationale", ""))[:300],
        )

    except Exception as exc:  # noqa: BLE001
        # §12.3: classifier fails → default to qa with the raw message as the
        # search query. A failed router must not fail the request.
        log.warning("classifier failed, defaulting to qa", extra={"error": type(exc).__name__})
        return RouteDecision(
            skill=inherit or "qa",  # type: ignore[arg-type]
            search_query=message,
            confidence=0.0,
            tier="fallback",
            artifact_type=None,
            needs_retrieval=True,
            rationale=f"classifier error: {type(exc).__name__}",
        )
