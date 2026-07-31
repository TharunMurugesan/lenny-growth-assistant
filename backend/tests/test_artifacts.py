"""Streaming artifact parser tests — closes open item O5.

The parser's whole reason to exist is that tags arrive split across token
boundaries, so the central technique here is to replay every fixture at many
different chunk sizes — including one character per delta — and assert the
output is identical each time. A parser that works on whole strings but breaks
at `<arti` + `fact...` passes a naive test and fails in production.
"""

from __future__ import annotations

import pytest

from app.utils.artifacts import ArtifactParser, EventKind

HTML_DOC = '<!doctype html><html><body><h1>Hi</h1><style>b{color:red}</style></body></html>'


def run(deltas: list[str]) -> tuple[list, str, str]:
    """Feed deltas through a fresh parser; return (events, prose, artifact)."""
    parser = ArtifactParser()
    events = []
    for d in deltas:
        events.extend(parser.feed(d))
    events.extend(parser.finish())
    return events, parser.prose, parser.artifact_content


def split_every(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


# Sizes chosen to land boundaries inside the tag, the attributes, and the body.
CHUNK_SIZES = [1, 2, 3, 5, 7, 13, 64, 10_000]


# --- invariant: no byte is ever dropped ----------------------------------


@pytest.mark.parametrize("n", CHUNK_SIZES)
@pytest.mark.parametrize(
    "text",
    [
        "just prose, no tags at all",
        "prose with a < literal angle bracket",
        "a < b and c > d, math not markup",
        "<artifac  never completes",
        '<artifact type="html">x</artifact>',
        f'Intro. <artifact type="html" title="T">{HTML_DOC}</artifact>',
        "<not-an-artifact>hello</not-an-artifact>",
        "",
    ],
)
def test_no_byte_is_ever_dropped(text: str, n: int) -> None:
    """Everything in must come out, as prose or artifact content.

    Tag syntax itself is consumed, so it is excluded from the comparison —
    but every non-tag character must survive.
    """
    _, prose, artifact = run(split_every(text, n))
    recovered = prose + artifact
    stripped = text
    for tag in ('<artifact type="html" title="T">', '<artifact type="html">', "</artifact>"):
        stripped = stripped.replace(tag, "")
    assert recovered == stripped


# --- invariant: chunking must not change the result ----------------------


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_result_is_identical_at_every_chunk_size(n: int) -> None:
    text = f'Here is a mockup. <artifact type="html" title="Dash">{HTML_DOC}</artifact>'
    events, prose, artifact = run(split_every(text, n))

    assert prose == "Here is a mockup. "
    assert artifact == HTML_DOC
    kinds = [e.kind for e in events]
    assert kinds.count(EventKind.ARTIFACT_START) == 1
    assert kinds.count(EventKind.ARTIFACT_END) == 1


def test_one_character_per_delta_through_a_full_tag() -> None:
    """O5 verbatim: one character per delta through a complete tag."""
    text = '<artifact type="markdown" title="Checklist"># Todo\n- a\n</artifact>'
    events, prose, artifact = run(list(text))

    start = next(e for e in events if e.kind is EventKind.ARTIFACT_START)
    assert start.artifact_type == "markdown"
    assert start.title == "Checklist"
    assert artifact == "# Todo\n- a\n"
    assert prose == ""


# --- artifact content containing '<' -------------------------------------


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_angle_brackets_inside_artifact_are_content_not_tags(n: int) -> None:
    """HTML is full of '<'. Only '</artifact>' may close the artifact."""
    text = f'<artifact type="html">{HTML_DOC}</artifact>'
    _, _, artifact = run(split_every(text, n))
    assert artifact == HTML_DOC
    assert "</artifact>" not in artifact


# --- malformed and truncated input ---------------------------------------


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_unclosed_artifact_reports_incomplete(n: int) -> None:
    """A stream dying mid-artifact must close it honestly, not silently."""
    text = '<artifact type="html">partial conte'
    events, _, artifact = run(split_every(text, n))

    end = next(e for e in events if e.kind is EventKind.ARTIFACT_END)
    assert end.complete is False
    assert artifact == "partial conte"


@pytest.mark.parametrize("n", CHUNK_SIZES)
def test_malformed_open_tag_degrades_to_text(n: int) -> None:
    """§9.1: a malformed emission degrades to visible text, never an exception."""
    text = '<artifact type="pdf">not a valid type</artifact>'
    events, prose, _ = run(split_every(text, n))

    assert not any(e.kind is EventKind.ARTIFACT_START for e in events)
    assert "not a valid type" in prose


def test_carry_buffer_is_bounded() -> None:
    """An unterminated tag must flush as text rather than grow without bound."""
    text = '<artifact type="html" title="' + "x" * 2000
    parser = ArtifactParser()
    for ch in text:
        list(parser.feed(ch))
    assert len(parser.carry) <= 512
    list(parser.finish())
    assert len(parser.prose) > 1000  # flushed as text, nothing lost


# --- ordering and shape ---------------------------------------------------


def test_prose_and_artifact_are_separate_channels() -> None:
    """The chat pane never sees artifact source; the viewer never sees prose."""
    text = 'Before. <artifact type="html">BODY</artifact>'
    events, prose, artifact = run(split_every(text, 3))

    assert "BODY" not in prose
    assert "Before." not in artifact

    order = [e.kind for e in events]
    assert order.index(EventKind.ARTIFACT_START) < order.index(EventKind.ARTIFACT_DELTA)
    assert order.index(EventKind.ARTIFACT_DELTA) < order.index(EventKind.ARTIFACT_END)


def test_title_is_optional() -> None:
    events, _, artifact = run(['<artifact type="html">', "x", "</artifact>"])
    start = next(e for e in events if e.kind is EventKind.ARTIFACT_START)
    assert start.title is None
    assert artifact == "x"


def test_single_quoted_attributes_are_accepted() -> None:
    events, _, _ = run(["<artifact type='html' title='Q'>x</artifact>"])
    start = next(e for e in events if e.kind is EventKind.ARTIFACT_START)
    assert start.artifact_type == "html"
    assert start.title == "Q"
