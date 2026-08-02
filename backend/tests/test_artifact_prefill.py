"""Artifact prefill tests — the local-model artifact fix.

Background. Skill C worked on Cloud and failed on Local. The routing was never
at fault: `llama3.2:1b` was correctly classified as `artifact`, then ignored the
instruction to wrap its output in `<artifact type=... title=...>` and returned a
prose *description* of a dashboard — 518 tokens, not one HTML tag.

The fix seeds the assistant turn with the opening tag so the model never has to
produce it. What makes that safe is a property of the existing parser rather
than a change to it: a partial opening tag is held in the carry buffer, so
feeding the seed and then the model's continuation yields exactly the event
sequence the cloud path yields.

These tests pin the three pieces: the seed itself, the parser's handling of a
seed split from its continuation, and the provider's message assembly.
"""

from __future__ import annotations

import pytest

from app.agent.prompts import artifact_prefill
from app.llm.base import Msg
from app.llm.ollama_provider import build_messages
from app.utils.artifacts import ArtifactParser, EventKind

# What the 1B model actually produced once seeded, trimmed for the fixture.
CONTINUATION = (
    'Weekly Cohort Retention">'
    "<!doctype html><html><body><h1>Retention</h1>"
    "<style>b{color:red}</style></body></html></artifact>"
)

CHUNK_SIZES = [1, 2, 3, 5, 7, 13, 64, 10_000]


def split_every(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


def drive(prefill: str, continuation_deltas: list[str]):
    """Feed the seed, then the model's deltas, exactly as the orchestrator does."""
    parser = ArtifactParser()
    events = list(parser.feed(prefill))
    for d in continuation_deltas:
        events.extend(parser.feed(d))
    events.extend(parser.finish())
    return events, parser


# --- the seed ------------------------------------------------------------


@pytest.mark.parametrize(
    "requested,expected_type",
    [("html", "html"), ("markdown", "markdown"), (None, "html"), ("bogus", "html")],
)
def test_prefill_names_a_valid_type(requested, expected_type):
    """An unknown or missing type must fall back, never emit an invalid tag."""
    seed = artifact_prefill(requested)
    assert seed == f'<artifact type="{expected_type}" title="'


def test_prefill_stops_mid_attribute():
    """The seed must end at the open quote so the model supplies the title.

    If it closed the tag instead, the artifact would carry a title the model
    never chose, and every artifact would share one.
    """
    assert artifact_prefill("html").endswith('title="')
    assert not artifact_prefill("html").endswith(">")


def test_seed_alone_emits_nothing():
    """A lone partial tag is held, not leaked as prose.

    This is the invariant the whole approach rests on: if the parser flushed
    the seed as text, `<artifact type="html" title="` would appear verbatim in
    the chat pane.
    """
    parser = ArtifactParser()
    assert list(parser.feed(artifact_prefill("html"))) == []
    assert parser.prose == ""


# --- seed + continuation through the parser ------------------------------


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_seeded_stream_opens_and_closes_the_artifact(n):
    events, parser = drive(artifact_prefill("html"), split_every(CONTINUATION, n))
    kinds = [e.kind for e in events]

    assert kinds.count(EventKind.ARTIFACT_START) == 1
    assert kinds.count(EventKind.ARTIFACT_END) == 1

    start = next(e for e in events if e.kind is EventKind.ARTIFACT_START)
    assert start.artifact_type == "html"
    assert start.title == "Weekly Cohort Retention"


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_seeded_stream_produces_no_prose(n):
    """Everything after the seed belongs to the artifact channel.

    The chat pane must not receive HTML source, at any chunk boundary.
    """
    _, parser = drive(artifact_prefill("html"), split_every(CONTINUATION, n))
    assert parser.prose == ""


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_seeded_artifact_body_is_intact(n):
    """The body is byte-identical regardless of how deltas were split."""
    _, parser = drive(artifact_prefill("html"), split_every(CONTINUATION, n))
    body = parser.artifact_content
    assert body.startswith("<!doctype html>")
    assert body.endswith("</html>")
    assert "<artifact" not in body
    assert "</artifact>" not in body


def test_markdown_seed_yields_markdown_type():
    cont = 'Launch Checklist">## Preparation\n- Define goals</artifact>'
    events, parser = drive(artifact_prefill("markdown"), [cont])
    start = next(e for e in events if e.kind is EventKind.ARTIFACT_START)
    assert start.artifact_type == "markdown"
    assert start.title == "Launch Checklist"
    assert parser.artifact_content == "## Preparation\n- Define goals"


def test_model_omitting_the_closing_tag_still_keeps_the_body():
    """Small models routinely drop `</artifact>`.

    The parser reports the artifact as incomplete, which is correct at this
    layer — it cannot see why the stream stopped. The orchestrator reconciles
    that against the finish reason. What must never happen is losing the body.
    """
    cont = 'Retention">' "<!doctype html><html><body>ok</body></html>"
    events, parser = drive(artifact_prefill("html"), [cont])
    end = next(e for e in events if e.kind is EventKind.ARTIFACT_END)

    assert end.complete is False
    assert parser.artifact_content.endswith("</html>")
    assert parser.prose == ""


# --- provider message assembly -------------------------------------------


def test_prefill_is_appended_as_an_assistant_turn():
    out = build_messages("SYS", [Msg("user", "hi")], artifact_prefill("html"))
    assert [m["role"] for m in out] == ["system", "user", "assistant"]
    assert out[-1]["content"] == '<artifact type="html" title="'


def test_no_prefill_leaves_the_conversation_untouched():
    """Every non-artifact path must send exactly what it sent before."""
    out = build_messages("SYS", [Msg("user", "hi")])
    assert [m["role"] for m in out] == ["system", "user"]


def test_empty_prefill_is_not_appended():
    """The orchestrator passes "" on the cloud path; that must be a no-op."""
    assert build_messages("SYS", [Msg("user", "hi")], "") == build_messages(
        "SYS", [Msg("user", "hi")]
    )
