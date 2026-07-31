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
