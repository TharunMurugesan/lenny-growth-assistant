"""Transcript parsing — episode metadata and speaker turns.

Closes open items O1 and O2 from the Phase 1 log, which flagged the corpus
layout and guest-name derivation as unverified. Both were checked against all
303 files in `ChatPRD/lennys-podcast-transcripts` before this was written:

  * Layout is uniform: `episodes/<slug>/transcript.md`, exactly one file each.
  * Every file (303/303) opens with YAML front matter carrying `guest`.
    `title` is present in 302 and `youtube_url` in 301, so both need fallbacks.
  * **Guest comes from front matter, not the directory slug** — `ryan-hoover/`
    actually contains an interview with Ryan *Singer*. Deriving the guest from
    the path would have mislabelled that episode and every citation from it.

Three speaker-label formats appear in the corpus. The first covers 301 files;
the other two exist in exactly one file each and are supported rather than
skipped, because dropping them would silently lose two real episodes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# `Ada Chen Rekhi (00:00:00):` — a new turn. 301/303 files.
TURN_TIMESTAMPED = re.compile(
    r"^(?P<name>[^(\n]{1,60}?)\s*\((?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\):\s*$"
)
# `(00:01:21):` — same speaker continues under a new timestamp.
CONTINUATION = re.compile(r"^\((?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\):\s*$")
# `[00:00:00] Ryan: text...` — timestamp first, speech on the same line.
TURN_INLINE = re.compile(
    r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<name>[^:]{1,60}):\s*(?P<text>.*)$"
)
# `Adriel Frederick:` — bare label, no timestamp.
TURN_BARE = re.compile(r"^(?P<name>[A-Z][A-Za-z .'\-]{1,58}):\s*$")


@dataclass
class Turn:
    speaker: str
    text: str


@dataclass
class Episode:
    slug: str
    title: str
    guest: str | None
    source_url: str | None
    turns: list[Turn] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in self.turns:
            seen.setdefault(t.speaker, None)
        return list(seen)


class TranscriptParseError(Exception):
    """This transcript is unusable. Logged and skipped, never fatal to a run."""


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Return (front matter, body). Body is returned whole if there is none."""
    if not text.startswith("---"):
        return {}, text

    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text

    raw = parts[0][3:]  # drop the opening '---'
    body = parts[1] if len(parts) == 2 else parts[1] + parts[2]

    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        # Malformed YAML shouldn't cost us the transcript body.
        log.warning("unreadable front matter", extra={"error": str(exc)[:120]})
        return {}, body

    return (meta if isinstance(meta, dict) else {}), body


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_turns(body: str) -> list[Turn]:
    """Extract speaker turns, tolerating all three label formats."""
    turns: list[Turn] = []
    current: Turn | None = None

    for line in body.splitlines():
        stripped = line.strip()

        # Skip markdown headings — '# Title' / '## Transcript' are structure.
        if stripped.startswith("#"):
            continue

        if m := TURN_INLINE.match(stripped):
            current = Turn(speaker=m.group("name").strip(), text=m.group("text").strip())
            turns.append(current)
            continue

        if m := TURN_TIMESTAMPED.match(stripped):
            current = Turn(speaker=m.group("name").strip(), text="")
            turns.append(current)
            continue

        if CONTINUATION.match(stripped):
            # Same speaker, new timestamp — keep appending to the current turn
            # so a single argument isn't fragmented across timestamps.
            continue

        if m := TURN_BARE.match(stripped):
            current = Turn(speaker=m.group("name").strip(), text="")
            turns.append(current)
            continue

        if not stripped:
            continue

        if current is None:
            # Prose before any speaker label (a stray intro line).
            current = Turn(speaker="Unknown", text=stripped)
            turns.append(current)
        else:
            current.text = f"{current.text} {stripped}".strip()

    return [t for t in turns if t.text]


def parse_transcript(path: Path, slug: str | None = None) -> Episode:
    """Parse one `transcript.md`. Raises TranscriptParseError if unusable."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TranscriptParseError(f"cannot read {path}: {exc}") from exc

    meta, body = _split_front_matter(raw)
    slug = slug or path.parent.name

    turns = parse_turns(body)
    if not turns:
        raise TranscriptParseError(f"{slug}: no speaker turns found")

    # Fallback chain for title: front matter, then the first '# ' heading,
    # then the slug — 1 of 303 files has no `title` key.
    title = _clean(meta.get("title"))
    if not title:
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = heading.group(1).strip() if heading else slug.replace("-", " ").title()

    return Episode(
        slug=slug,
        title=title,
        guest=_clean(meta.get("guest")),
        source_url=_clean(meta.get("youtube_url")),
        turns=turns,
    )


def iter_episodes(root: Path, limit: int | None = None):
    """Yield parsed episodes, skipping (and logging) any that fail.

    §10.1: a single malformed transcript is logged and skipped, never fatal.
    """
    paths = sorted(root.glob("*/transcript.md"))
    if limit is not None:
        paths = paths[:limit]

    for path in paths:
        try:
            yield parse_transcript(path)
        except TranscriptParseError as exc:
            log.warning("skipping transcript", extra={"reason": str(exc)})
