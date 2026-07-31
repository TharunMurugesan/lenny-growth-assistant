"""Turn-aware chunking — architecture.md §10.1.

Windows are cut on speaker-turn boundaries, never mid-sentence. 800 tokens is
large enough to hold a complete argument: podcast insight arrives as a
multi-sentence point, and a 200-token chunk retrieves a fragment that reads as
a non-answer. The 120-token overlap keeps a point straddling a boundary
retrievable from either side.

Every chunk is prefixed at embedding time with `Episode: … | Guest: …` so
episode-level signal lives inside the vector rather than only in metadata.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.ingestion.parse import Episode, Turn

# Split on sentence-ending punctuation followed by whitespace and a capital or
# quote. Deliberately simple — this only has to find a *reasonable* boundary
# inside an over-long turn, not be linguistically correct.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def estimate_tokens(text: str) -> int:
    """Approximate token count.

    An approximation on purpose: the target consumer is `nomic-embed-text`, not
    Claude billing, so the exact tokenizer is irrelevant — what matters is that
    the measure is cheap, deterministic, and monotonic in length. Calling a
    real tokenizer ~9,000 times per ingest would dominate the run for no gain.
    Ratio ≈ 0.75 words per token, the usual English figure.
    """
    words = len(text.split())
    return int(words / 0.75) + 1 if words else 0


@dataclass
class Chunk:
    episode_slug: str
    episode_title: str
    guest: str | None
    source_url: str | None
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    speakers: list[str]

    def embedding_input(self) -> str:
        """The text actually embedded — metadata-prefixed per §10.1."""
        head = f"Episode: {self.episode_title}"
        if self.guest:
            head += f" | Guest: {self.guest}"
        return f"{head}\n\n{self.content}"


def _hash(text: str) -> str:
    """Content hash for idempotency — unchanged text is never re-embedded."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_long_turn(turn: Turn, target: int) -> list[Turn]:
    """Split a single over-long turn at sentence boundaries."""
    if estimate_tokens(turn.text) <= target:
        return [turn]

    pieces: list[Turn] = []
    buf: list[str] = []
    size = 0

    for sentence in SENTENCE_END.split(turn.text):
        n = estimate_tokens(sentence)
        if buf and size + n > target:
            pieces.append(Turn(turn.speaker, " ".join(buf)))
            buf, size = [], 0
        buf.append(sentence)
        size += n

    if buf:
        pieces.append(Turn(turn.speaker, " ".join(buf)))
    return pieces


def _render(turn: Turn) -> str:
    return f"{turn.speaker}: {turn.text}"


def chunk_episode(
    episode: Episode, *, target_tokens: int = 800, overlap_tokens: int = 120
) -> list[Chunk]:
    """Window an episode's turns into overlapping chunks."""
    # Flatten first so an over-long turn can never blow past the target.
    turns: list[Turn] = []
    for turn in episode.turns:
        turns.extend(_split_long_turn(turn, target_tokens))

    chunks: list[Chunk] = []
    window: list[Turn] = []
    size = 0
    index = 0

    def flush() -> None:
        nonlocal window, size, index
        if not window:
            return
        content = "\n\n".join(_render(t) for t in window)
        speakers: dict[str, None] = {}
        for t in window:
            speakers.setdefault(t.speaker, None)

        chunks.append(
            Chunk(
                episode_slug=episode.slug,
                episode_title=episode.title,
                guest=episode.guest,
                source_url=episode.source_url,
                chunk_index=index,
                content=content,
                content_hash=_hash(content),
                token_count=estimate_tokens(content),
                speakers=list(speakers),
            )
        )
        index += 1

        # Carry back whole turns until the overlap budget is met, so the
        # overlap is also turn-aligned rather than a raw character slice.
        carry: list[Turn] = []
        carried = 0
        for turn in reversed(window):
            n = estimate_tokens(turn.text)
            if carried + n > overlap_tokens:
                break
            carry.insert(0, turn)
            carried += n

        # A single turn larger than the overlap budget would otherwise carry
        # nothing and lose the boundary entirely; keep the last turn.
        if not carry and window:
            carry = [window[-1]]
            carried = estimate_tokens(window[-1].text)

        window = carry
        size = carried

    for turn in turns:
        n = estimate_tokens(turn.text)
        if window and size + n > target_tokens:
            flush()
        window.append(turn)
        size += n

    # Final flush must not re-emit only the carried overlap.
    if window and (not chunks or size > 0):
        content = "\n\n".join(_render(t) for t in window)
        if not chunks or content != chunks[-1].content:
            speakers = {}
            for t in window:
                speakers.setdefault(t.speaker, None)
            chunks.append(
                Chunk(
                    episode_slug=episode.slug,
                    episode_title=episode.title,
                    guest=episode.guest,
                    source_url=episode.source_url,
                    chunk_index=index,
                    content=content,
                    content_hash=_hash(content),
                    token_count=estimate_tokens(content),
                    speakers=list(speakers),
                )
            )

    return chunks
