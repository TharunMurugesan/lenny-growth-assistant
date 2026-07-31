"""Ingest pipeline — idempotent and resumable (architecture.md §10.1).

    fetch → parse → chunk → embed → UPSERT ON CONFLICT (episode_slug, chunk_index)

Two properties matter more than throughput:

  * **Idempotent.** `content_hash` is compared before embedding; unchanged
    chunks are skipped. Re-running never duplicates rows or re-spends on
    embeddings.
  * **Resumable.** A run interrupted at episode 300 of 400 resumes without
    re-embedding the first 300, because the skip check is per-chunk and
    committed per-episode.

A single malformed transcript is logged and skipped, never fatal to the run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingestion.chunker import Chunk, chunk_episode
from app.ingestion.parse import iter_episodes
from app.llm.embeddings import Embedder, get_embedder
from app.models import IngestRun, TranscriptChunk

log = logging.getLogger(__name__)

EMBED_BATCH = 64


@dataclass
class IngestStats:
    episodes_seen: int = 0
    chunks_written: int = 0
    chunks_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        return (
            f"episodes={self.episodes_seen} written={self.chunks_written} "
            f"skipped={self.chunks_skipped} errors={len(self.errors)}"
        )


async def _existing_hashes(session: AsyncSession, slug: str) -> dict[int, str]:
    """Current (chunk_index → content_hash) for one episode."""
    rows = await session.execute(
        select(TranscriptChunk.chunk_index, TranscriptChunk.content_hash).where(
            TranscriptChunk.episode_slug == slug
        )
    )
    return {index: digest for index, digest in rows.all()}


async def _upsert(
    session: AsyncSession, chunks: list[Chunk], vectors: list[list[float]], column: str
) -> None:
    """Write chunks, setting only the active embedding column.

    The other embedding column is deliberately left untouched: a corpus can be
    ingested once per space, and re-running for `local` must not wipe vectors
    written for `voyage`.
    """
    payload = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        row = {
            "episode_slug": chunk.episode_slug,
            "episode_title": chunk.episode_title,
            "guest": chunk.guest,
            "source_url": chunk.source_url,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "speakers": chunk.speakers,
            column: vector,
        }
        payload.append(row)

    stmt = pg_insert(TranscriptChunk).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[TranscriptChunk.episode_slug, TranscriptChunk.chunk_index],
        set_={
            "episode_title": stmt.excluded.episode_title,
            "guest": stmt.excluded.guest,
            "source_url": stmt.excluded.source_url,
            "content": stmt.excluded.content,
            "content_hash": stmt.excluded.content_hash,
            "token_count": stmt.excluded.token_count,
            "speakers": stmt.excluded.speakers,
            column: getattr(stmt.excluded, column),
        },
    )
    await session.execute(stmt)


async def run_ingest(
    engine: AsyncEngine,
    settings: Settings,
    episodes_dir: Path,
    *,
    limit_episodes: int | None = None,
    embedder: Embedder | None = None,
    progress: bool = True,
) -> IngestStats:
    """Execute one ingest run, recording it in `ingest_runs`."""
    embedder = embedder or get_embedder(settings)
    column = "embedding_local" if embedder.space == "local" else "embedding_voyage"
    stats = IngestStats()

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        run = IngestRun(
            embed_space=embedder.space, embed_model=embedder.model, status="running"
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    try:
        for episode in iter_episodes(episodes_dir, limit=limit_episodes):
            stats.episodes_seen += 1
            chunks = chunk_episode(
                episode,
                target_tokens=settings.chunk_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
            )
            if not chunks:
                continue

            async with factory() as session:
                known = await _existing_hashes(session, episode.slug)

                # The idempotency check: unchanged text is never re-embedded.
                pending = [
                    c for c in chunks if known.get(c.chunk_index) != c.content_hash
                ]
                stats.chunks_skipped += len(chunks) - len(pending)

                if not pending:
                    if progress:
                        log.info(
                            "episode unchanged",
                            extra={"slug": episode.slug, "chunks": len(chunks)},
                        )
                    continue

                for i in range(0, len(pending), EMBED_BATCH):
                    batch = pending[i : i + EMBED_BATCH]
                    vectors = await embedder.embed([c.embedding_input() for c in batch])
                    await _upsert(session, batch, vectors, column)
                    stats.chunks_written += len(batch)

                # Commit per episode — this is what makes the run resumable.
                await session.commit()

            if progress:
                log.info(
                    "episode ingested",
                    extra={
                        "slug": episode.slug,
                        "written": len(pending),
                        "total": len(chunks),
                    },
                )

        status = "success"
        error = None
    except Exception as exc:  # noqa: BLE001 - recorded on the run row
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"[:500]
        stats.errors.append(error)
        log.error("ingest failed", exc_info=exc)
        raise
    finally:
        async with factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE ingest_runs
                    SET status = :status, episodes_seen = :seen,
                        chunks_written = :written, chunks_skipped = :skipped,
                        error = :error, finished_at = :finished
                    WHERE id = :id
                    """
                ),
                {
                    "status": status,
                    "seen": stats.episodes_seen,
                    "written": stats.chunks_written,
                    "skipped": stats.chunks_skipped,
                    "error": error,
                    "finished": datetime.now(timezone.utc),
                    "id": run_id,
                },
            )
            await session.commit()

    return stats
