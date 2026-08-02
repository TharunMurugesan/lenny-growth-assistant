"""Streaming `<artifact>` tag parser — architecture.md §9.

The hard requirement: tags arrive split across token boundaries. A model emits
`<arti`, then `fact type="ht`, then `ml">`. A naive substring check never fires
and tag fragments leak into the chat pane as visible garbage.

This is an incremental state machine over a carry buffer:

    TEXT ──sees '<' that could begin "<artifact"──▶ MAYBE_OPEN
      ▲                                               │
      │  prefix cannot complete → flush as text       │ full tag parsed
      │                                               ▼
      │                                         IN_ARTIFACT
      │                                               │ sees '<'
      └───────"</artifact>" complete─────────── MAYBE_CLOSE

Invariants, in order of how easy they are to get wrong:

  1. **No byte is ever dropped.** Everything the model produced leaves as
     either prose or artifact content, including on a malformed or truncated
     stream. `finish()` flushes whatever is still held.
  2. **Bounded memory.** The carry buffer is capped at 512 chars; a tag that
     has not completed by then is flushed as text. A malformed tag can never
     stall the stream or grow memory without bound.
  3. **Two separate channels.** Text in TEXT becomes `token` events; text in
     IN_ARTIFACT becomes `artifact_delta`. The chat pane never shows artifact
     source and the viewer never shows prose.
  4. **Same parser for stream and persistence.** The row written to `messages`
     is built from this output, so replayed history is byte-identical to what
     was streamed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Literal

OPEN_PREFIX = "<artifact"
CLOSE_TAG = "</artifact>"
MAX_CARRY = 512

ArtifactType = Literal["html", "markdown"]

# Matches a complete opening tag. Deliberately narrow (§9.1): two attributes,
# fixed type vocabulary, no nesting — so a malformed emission degrades to
# visible text instead of a parse exception.
OPEN_TAG_RE = re.compile(
    r"""<artifact\s+
        type\s*=\s*(?P<q1>["'])(?P<type>html|markdown)(?P=q1)
        (?:\s+title\s*=\s*(?P<q2>["'])(?P<title>[^"']*)(?P=q2))?
        \s*>""",
    re.VERBOSE | re.IGNORECASE,
)


# --- local artifact tidy-up ----------------------------------------------
#
# Three successive prompt designs were measured against llama3.2:1b and the
# results were not monotonic — one run produced four populated cards, the next
# an empty card, a header-only table and an empty bar. The model cannot hold a
# structure of this size, so the structure stops depending on it.
#
# These rules delete containers the model opened and never filled. Nothing is
# invented: an empty <tbody> becomes no table rather than a fabricated one, so
# a sparse artifact is possible but a visibly broken one is not.
_EMPTY_TABLE = re.compile(r"<table\b(?:(?!</table>).)*?</table>", re.S | re.I)
_EMPTY_CARD = re.compile(r'<div class="card"\s*>(?:(?!</div>).)*?</div>', re.S | re.I)
_EMPTY_BAR = re.compile(r'<div class="bar"\s*>(?:(?!</div>).)*?</div>', re.S | re.I)
_PLACEHOLDER = re.compile(r"\[(?:your name|name|date|company|team)\]", re.I)
_EMPTY_TAG = re.compile(r"<(p|h2|li)\b[^>]*>\s*</\1>", re.I)


_BLOCK = re.compile(
    r"<table\b(?:(?!</table>).)*?</table>"
    r"|<div class=\"grid\"\s*>(?:(?!</div>\s*</div>).)*?</div>\s*</div>"
    r"|<ul\b(?:(?!</ul>).)*?</ul>",
    re.S | re.I,
)


def _drop_repeated_blocks(html: str) -> str:
    """Delete a component the model has already emitted verbatim.

    Repetition is the failure mode a generous token budget reintroduces: the
    model writes a correct table, then writes the same table again. Capping
    tokens suppressed it but also capped how much content the page could carry.
    Removing exact repeats here is what lets the budget be generous again —
    only byte-identical blocks are dropped, so two genuinely different tables
    both survive.
    """
    seen: set[str] = set()

    def keep(match: re.Match[str]) -> str:
        key = " ".join(match.group(0).split())
        if key in seen:
            return ""
        seen.add(key)
        return match.group(0)

    return _BLOCK.sub(keep, html)


def _align_table_columns(html: str) -> str:
    """Make each table's header width match its body rows.

    The visible symptom was a table whose header sat in one block and whose
    rows floated offset beside it. That is not a styling bug: the model wrote a
    four-column <thead> and three-cell body rows, and a browser lays that out
    exactly as badly as it sounds. Trimming the header to the body's width is
    the honest repair — it drops a column heading the rows never had data for,
    rather than inventing a column of blanks to pad with.
    """

    def fix(match: re.Match[str]) -> str:
        table = match.group(0)
        body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", table, re.S | re.I)
        if not body:
            return table
        widths = [
            len(re.findall(r"<td\b", row))
            for row in re.findall(r"<tr\b[^>]*>.*?</tr>", body.group(1), re.S | re.I)
        ]
        widths = [w for w in widths if w]
        if not widths:
            return table
        want = max(set(widths), key=widths.count)  # the most common row width

        def trim_head(head: re.Match[str]) -> str:
            cells = re.findall(r"<th\b[^>]*>.*?</th>", head.group(1), re.S | re.I)
            if len(cells) <= want:
                return head.group(0)
            return f"<thead><tr>{''.join(cells[:want])}</tr></thead>"

        return re.sub(
            r"<thead\b[^>]*>(.*?)</thead>", trim_head, table, flags=re.S | re.I
        )

    return re.sub(r"<table\b(?:(?!</table>).)*?</table>", fix, html, flags=re.S | re.I)


def tidy_artifact_html(html: str) -> str:
    """Remove structural containers the model left empty.

    Applied only to the scaffolded local path, where the document skeleton is
    ours and the model supplies content. Deliberately conservative: it deletes,
    never fills.
    """

    def drop_if(pattern: re.Pattern[str], must_contain: str) -> None:
        nonlocal html
        html = pattern.sub(
            lambda m: m.group(0) if must_contain in m.group(0).lower() else "", html
        )

    # Anything after </html> renders outside the styled wrapper — a stray table
    # or a sentence floating at full bleed under the page. The model does this
    # when it keeps going after finishing; cut it rather than show it.
    end = html.lower().find("</html>")
    if end != -1:
        html = html[: end + len("</html>")]

    html = _drop_repeated_blocks(html)
    html = _align_table_columns(html)
    drop_if(_EMPTY_TABLE, "<td")  # header row but no data
    drop_if(_EMPTY_CARD, 'class="metric"')  # card with no number
    drop_if(_EMPTY_BAR, "width:")  # bar with no fill
    html = _PLACEHOLDER.sub("", html)
    html = _EMPTY_TAG.sub("", html)
    # A heading left with nothing beneath it reads as a rendering failure.
    html = re.sub(r"<h2\b[^>]*>[^<]*</h2>\s*(?=(<h2|</div>|</body>))", "", html, flags=re.I)
    return html


class State(Enum):
    TEXT = auto()
    MAYBE_OPEN = auto()
    IN_ARTIFACT = auto()
    MAYBE_CLOSE = auto()


class EventKind(str, Enum):
    TEXT = "text"
    ARTIFACT_START = "artifact_start"
    ARTIFACT_DELTA = "artifact_delta"
    ARTIFACT_END = "artifact_end"


@dataclass
class ParseEvent:
    kind: EventKind
    text: str = ""
    artifact_type: ArtifactType | None = None
    title: str | None = None
    complete: bool = True


def _is_proper_prefix(s: str, target: str) -> bool:
    """True if `s` could still grow into `target` (and is not yet complete)."""
    return len(s) < len(target) and target.startswith(s)


@dataclass
class ArtifactParser:
    """Feed it deltas, get back prose/artifact events. One instance per stream."""

    state: State = State.TEXT
    carry: str = ""
    _artifact_open: bool = False
    _prose: list[str] = field(default_factory=list)
    _artifact: list[str] = field(default_factory=list)
    _type: ArtifactType | None = None
    _title: str | None = None

    # --- accumulated results, for persistence -------------------------

    @property
    def prose(self) -> str:
        return "".join(self._prose)

    @property
    def artifact_content(self) -> str:
        return "".join(self._artifact)

    @property
    def artifact_type(self) -> ArtifactType | None:
        return self._type

    @property
    def artifact_title(self) -> str | None:
        return self._title

    # --- emission helpers ---------------------------------------------

    def _emit_text(self, text: str) -> ParseEvent | None:
        if not text:
            return None
        self._prose.append(text)
        return ParseEvent(EventKind.TEXT, text=text)

    def _emit_artifact(self, text: str) -> ParseEvent | None:
        if not text:
            return None
        self._artifact.append(text)
        return ParseEvent(EventKind.ARTIFACT_DELTA, text=text)

    # --- main loop ----------------------------------------------------

    def feed(self, delta: str) -> Iterator[ParseEvent]:
        """Consume one token delta, yielding zero or more events."""
        if not delta:
            return

        buf = self.carry + delta
        self.carry = ""

        while buf:
            if self.state is State.TEXT:
                idx = buf.find("<")
                if idx == -1:
                    ev = self._emit_text(buf)
                    if ev:
                        yield ev
                    buf = ""
                    break

                ev = self._emit_text(buf[:idx])
                if ev:
                    yield ev
                buf = buf[idx:]
                self.state = State.MAYBE_OPEN
                continue

            if self.state is State.MAYBE_OPEN:
                match = OPEN_TAG_RE.match(buf)
                if match:
                    self._type = match.group("type").lower()  # type: ignore[assignment]
                    self._title = match.group("title") or None
                    self._artifact_open = True
                    self.state = State.IN_ARTIFACT
                    buf = buf[match.end() :]
                    yield ParseEvent(
                        EventKind.ARTIFACT_START,
                        artifact_type=self._type,
                        title=self._title,
                    )
                    continue

                # Still a viable prefix of "<artifact"? Hold and wait for more.
                head = buf[: len(OPEN_PREFIX)]
                if _is_proper_prefix(buf, OPEN_PREFIX):
                    self.carry = buf
                    buf = ""
                    break

                # `<artifact` matched but attributes are still arriving — the
                # tag is incomplete, not wrong. Hold, up to the cap.
                if head.lower() == OPEN_PREFIX and len(buf) < MAX_CARRY:
                    self.carry = buf
                    buf = ""
                    break

                # Not a tag (or exceeded the cap): the '<' is literal text.
                # Emit just the '<' and re-scan the rest, so a later real tag
                # in the same buffer is still found.
                ev = self._emit_text("<")
                if ev:
                    yield ev
                buf = buf[1:]
                self.state = State.TEXT
                continue

            if self.state is State.IN_ARTIFACT:
                idx = buf.find("<")
                if idx == -1:
                    ev = self._emit_artifact(buf)
                    if ev:
                        yield ev
                    buf = ""
                    break

                ev = self._emit_artifact(buf[:idx])
                if ev:
                    yield ev
                buf = buf[idx:]
                self.state = State.MAYBE_CLOSE
                continue

            # State.MAYBE_CLOSE
            if buf.startswith(CLOSE_TAG):
                buf = buf[len(CLOSE_TAG) :]
                self._artifact_open = False
                self.state = State.TEXT
                yield ParseEvent(
                    EventKind.ARTIFACT_END,
                    complete=True,
                    artifact_type=self._type,
                    title=self._title,
                )
                continue

            if _is_proper_prefix(buf, CLOSE_TAG) and len(buf) < MAX_CARRY:
                self.carry = buf
                buf = ""
                break

            # A '<' inside the artifact that is not the closing tag — ordinary
            # HTML content. Emit it and keep going.
            ev = self._emit_artifact("<")
            if ev:
                yield ev
            buf = buf[1:]
            self.state = State.IN_ARTIFACT

    def finish(self) -> Iterator[ParseEvent]:
        """Flush at end of stream. Guarantees invariant 1 (no byte dropped)."""
        leftover, self.carry = self.carry, ""

        if self.state in (State.TEXT, State.MAYBE_OPEN):
            ev = self._emit_text(leftover)
            if ev:
                yield ev
        elif self.state in (State.IN_ARTIFACT, State.MAYBE_CLOSE):
            ev = self._emit_artifact(leftover)
            if ev:
                yield ev

        if self._artifact_open:
            # Stream died mid-artifact. Close it honestly rather than pretending
            # it finished — the UI renders complete:false differently.
            self._artifact_open = False
            yield ParseEvent(
                EventKind.ARTIFACT_END,
                complete=False,
                artifact_type=self._type,
                title=self._title,
            )

        self.state = State.TEXT
