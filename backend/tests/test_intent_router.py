"""Route-decision fixture suite — closes open item O4.

O4 asked for "≥ 30 labelled messages that keep Tier 1 and Tier 2 in agreement".
That splits into two things with very different costs:

  * **Tier 0 and Tier 1 are pure functions.** They are tested exhaustively here
    with no network and no model, so the suite runs in milliseconds and is safe
    in CI.
  * **Tier 2 needs a live model.** Those cases are marked `live` and skipped
    unless `RUN_LIVE_ROUTER_TESTS=1`, so a missing API key never turns into a
    red build — but the agreement check exists and can be run on demand.

The `FIXTURES` table below is the shared ground truth for both.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.agent import intent_router as ir

pytestmark = pytest.mark.asyncio

# (message, expected_skill, must_tier1_fire)
#
# `must_tier1_fire=False` means the heuristic tier is *allowed* to abstain and
# hand off to Tier 2 — which is the designed behaviour, not a gap. Tier 1 is
# precision-first: it fires only when the intent is unambiguous.
FIXTURES: list[tuple[str, str, bool]] = [
    # --- ship30 (length/format words) ---------------------------------
    ("Write a Ship30for30 essay on retention", "ship30", True),
    ("write me an essay about product led growth", "ship30", True),
    ("Draft a 1250 word piece on activation", "ship30", True),
    ("Turn this into a long-form post", "ship30", True),
    ("Write a linkedin post about churn", "ship30", True),
    ("Give me a newsletter post on pricing", "ship30", True),
    ("write a thread about onboarding", "ship30", True),
    # --- artifact (format/visual words) --------------------------------
    ("Build me an HTML dashboard for retention", "artifact", True),
    ("Design a landing page for a B2B SaaS", "artifact", True),
    ("Create a wireframe for the signup flow", "artifact", True),
    ("Make a mockup of a pricing page", "artifact", True),
    ("Generate an SVG chart of the funnel", "artifact", True),
    ("build me a checklist for launch readiness", "artifact", True),
    ("Give me a one-pager on positioning", "artifact", True),
    ("Write the CSS for a card component", "artifact", True),
    # --- meta (whole-message greetings / self-questions) ---------------
    ("who are you", "meta", True),
    ("what can you do", "meta", True),
    ("which model is this", "meta", True),
    ("hello", "meta", True),
    ("hi", "meta", True),
    ("thanks", "meta", True),
    # --- qa (no positive pattern; Tier 1 abstains by design) -----------
    ("How do great PMs decide what not to build?", "qa", False),
    ("What did Shreyas say about prioritisation?", "qa", False),
    ("Why do growth loops beat funnels?", "qa", False),
    ("How should I run a discovery interview?", "qa", False),
    ("What is a good activation metric?", "qa", False),
    ("How do you hire a first PM?", "qa", False),
    # --- off-topic still routes to qa, where the floor declines --------
    ("What is the best recipe for sourdough bread?", "qa", False),
    ("How do I replace a car alternator?", "qa", False),
    ("Explain the offside rule", "qa", False),
    # --- ambiguous: BOTH ship30 and artifact patterns present ----------
    # Tier 1 must abstain unless exactly one of format/length disambiguates.
    ("Write an essay and build an HTML page about it", "", False),
    # Negation ("no html") reads as a format word to a keyword matcher, so both
    # disambiguators fire and Tier 1 abstains. That is the correct outcome, not
    # a gap: a regex tier that tried to parse negation would be guessing, and a
    # wrong guess skips the tier that would have been right. Tier 2 handles it.
    ("write a 1250 word essay, no html", "ship30", False),
    # Only artifact patterns match here — "not an essay" contains no ship30
    # trigger — so Tier 1 can fire safely.
    ("build me a dashboard page, not an essay", "artifact", True),
]


class FakeProvider:
    """Stands in for Tier 2 so the offline tests never touch the network."""

    chat_model = "fake"

    def __init__(self, reply: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.reply = reply or {
            "intent": "qa",
            "artifact_type": None,
            "confidence": 0.9,
            "search_query": "rewritten",
            "rationale": "fake",
        }
        self.fail = fail
        self.calls = 0

    async def classify(self, system: str, user: str, schema: dict) -> dict:
        self.calls += 1
        if self.fail:
            raise RuntimeError("classifier exploded")
        return self.reply


# --- Tier 1, offline ------------------------------------------------------


@pytest.mark.parametrize("message,expected,must_fire", FIXTURES)
async def test_tier1_never_contradicts_the_label(
    message: str, expected: str, must_fire: bool
) -> None:
    """Tier 1 may abstain, but must never fire with the wrong skill."""
    hit = ir._tier1(message)
    if must_fire:
        assert hit is not None, f"Tier 1 should have fired for {message!r}"
        assert hit[0] == expected
    elif hit is not None:
        assert hit[0] == expected, f"Tier 1 misfired on {message!r}: {hit[0]}"


async def test_ambiguous_message_abstains_to_tier2() -> None:
    """Both patterns, neither disambiguator — must fall through, not guess."""
    assert ir._tier1("Write an essay and build an HTML page about it") is None


# --- Tier 0 ---------------------------------------------------------------


async def test_skill_override_skips_both_tiers() -> None:
    """An explicit user choice is never second-guessed (§7.1)."""
    provider = FakeProvider()
    decision = await ir.route("anything at all", provider=provider, skill_override="ship30")
    assert decision.skill == "ship30"
    assert decision.tier == "override"
    assert provider.calls == 0


# --- §7.4 follow-up inheritance -------------------------------------------


@pytest.mark.parametrize(
    "message", ["make it longer", "try again", "shorter please", "add a chart", "what about B2C?"]
)
async def test_short_modifiers_inherit_previous_skill(message: str) -> None:
    """Without this, 'make it longer' after an essay returns a 200-word answer."""
    decision = await ir.route(
        message,
        provider=FakeProvider({"intent": "qa", "artifact_type": None, "confidence": 0.95,
                               "search_query": "retention", "rationale": ""}),
        previous_skill="ship30",
    )
    assert decision.skill == "ship30"


async def test_long_message_does_not_inherit() -> None:
    """Inheritance is for short modifiers only, not every follow-up."""
    long_msg = "make it longer and also explain how activation differs from retention in detail"
    decision = await ir.route(
        long_msg,
        provider=FakeProvider({"intent": "qa", "artifact_type": None, "confidence": 0.95,
                               "search_query": "q", "rationale": ""}),
        previous_skill="ship30",
    )
    assert decision.skill == "qa"


# --- §7.3 / §12.3 failure handling ----------------------------------------


async def test_low_confidence_falls_back_to_qa() -> None:
    decision = await ir.route(
        "something inscrutable",
        provider=FakeProvider({"intent": "artifact", "artifact_type": "html",
                               "confidence": 0.2, "search_query": "q", "rationale": ""}),
    )
    assert decision.skill == "qa"
    assert decision.tier == "fallback"


async def test_classifier_failure_defaults_to_qa_with_raw_message() -> None:
    """§12.3: a failed classifier must not fail the request."""
    decision = await ir.route("How do PMs prioritise?", provider=FakeProvider(fail=True))
    assert decision.skill == "qa"
    assert decision.tier == "fallback"
    assert decision.search_query == "How do PMs prioritise?"


async def test_unknown_intent_is_coerced_to_qa() -> None:
    decision = await ir.route(
        "hmm",
        provider=FakeProvider({"intent": "nonsense", "artifact_type": None,
                               "confidence": 0.99, "search_query": "q", "rationale": ""}),
    )
    assert decision.skill == "qa"


async def test_artifact_type_is_only_set_for_artifact_skill() -> None:
    decision = await ir.route(
        "Why does retention matter?",
        provider=FakeProvider({"intent": "qa", "artifact_type": "html",
                               "confidence": 0.9, "search_query": "q", "rationale": ""}),
    )
    assert decision.artifact_type is None


async def test_meta_never_retrieves() -> None:
    decision = await ir.route("who are you", provider=FakeProvider())
    assert decision.skill == "meta"
    assert decision.needs_retrieval is False


# --- Tier 2 agreement, live and opt-in ------------------------------------

live = pytest.mark.skipif(
    os.getenv("RUN_LIVE_ROUTER_TESTS") != "1",
    reason="set RUN_LIVE_ROUTER_TESTS=1 to exercise the real classifier",
)


@live
@pytest.mark.parametrize(
    "message,expected", [(m, e) for m, e, _ in FIXTURES if e]
)
async def test_tier2_agrees_with_labels(message: str, expected: str) -> None:
    """The agreement check O4 asked for. Costs one model call per case."""
    from app.config import get_settings
    from app.llm import registry

    settings = get_settings()
    provider = registry.get_provider("cloud", settings)
    raw = await provider.classify(
        ir.CLASSIFIER_SYSTEM, f"user: {message}", ir.CLASSIFIER_SCHEMA
    )
    assert raw["intent"] == expected, f"{message!r} -> {raw['intent']} (want {expected})"
