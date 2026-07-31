"""Hybrid retrieval — architecture.md §10.2.

Vector search alone misses exact terms: a query for "PLG" or a guest's name is
semantically diffuse but lexically precise. Lexical search alone misses
paraphrase. Both arms run concurrently and are fused with Reciprocal Rank
Fusion, which needs only ranks — so two incomparable score distributions
(cosine distance and `ts_rank_cd`) combine without normalization or per-arm
weight tuning.

Two filters after fusion carry most of the quality:

  * **Diversity cap.** Without it a well-matched ten-minute stretch of one
    episode fills all 8 slots and one guest's view reads as consensus.
  * **Relevance floor.** Vector search always returns its top-k however bad.
    Without a floor an off-topic question retrieves the 8 least-irrelevant
    chunks and the model dutifully synthesizes an answer from noise. The floor
    is what makes Skill A's honest decline reachable at all.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.types import RetrievedChunk
from app.config import Settings
from app.llm.embeddings import get_embedder
from app.utils.errors import RetrievalEmpty

log = logging.getLogger(__name__)

RRF_K = 60  # standard constant; behaves well without corpus-specific tuning
EF_SEARCH = 64  # above pgvector's default 40 for recall, below the latency knee
MAX_PER_EPISODE = 3

# Measured, not assumed — this closes open item O3.
#
# architecture.md §10.2 specifies 0.35, chosen a priori before any embeddings
# existed. Against `nomic-embed-text` on this corpus that value never rejects
# anything: the model's cosine similarities are compressed into a high band, so
# an off-topic query ("quantum chromodynamics lattice gauge theory") still
# scored 0.44-0.49 and returned a full result set. Skill A's honest decline was
# unreachable.
#
# Measured top-similarity over the corpus:
#     on-topic  queries: 0.642 - 0.723
#     off-topic queries: 0.453 - 0.486
#
# 0.55 sits inside that gap with margin on both sides. It is deliberately
# closer to the off-topic ceiling than the on-topic floor, because a false
# decline (recoverable — the user rephrases) is cheaper than a confident answer
# synthesized from noise.
#
# Also tested and rejected: `nomic-embed-text`'s `search_query:` /
# `search_document:` task prefixes. Applying the query prefix alone *narrowed*
# separation to 0.101, because the stored vectors carry no matching document
# prefix. Symmetric no-prefix embedding is the better pairing here.
SIMILARITY_FLOOR = 0.55


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    degraded: bool = False  # lexical-only, because embeddings were unavailable
    reason: str | None = None


def _column(settings: Settings) -> str:
    return "embedding_local" if settings.embed_space == "local" else "embedding_voyage"


async def _dense_arm(
    session: AsyncSession, vector: list[float], column: str, limit: int
) -> list[dict]:
    """Vector search. The embedding is a bound parameter, never interpolated."""
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
    rows = await session.execute(
        text(
            f"""
            SELECT id, episode_slug, episode_title, guest, source_url, content,
                   1 - ({column} <=> (:vec)::vector) AS similarity
            FROM   transcript_chunks
            WHERE  {column} IS NOT NULL
            ORDER  BY {column} <=> (:vec)::vector
            LIMIT  :limit
            """
        ),
        {"vec": str(vector), "limit": limit},
    )
    return [dict(r._mapping) for r in rows]


async def _lexical_arm(session: AsyncSession, query: str, limit: int) -> list[dict]:
    """Full-text search over the generated `content_tsv` column."""
    rows = await session.execute(
        text(
            """
            SELECT id, episode_slug, episode_title, guest, source_url, content,
                   ts_rank_cd(content_tsv, websearch_to_tsquery('english', :q)) AS rank
            FROM   transcript_chunks
            WHERE  content_tsv @@ websearch_to_tsquery('english', :q)
            ORDER  BY rank DESC
            LIMIT  :limit
            """
        ),
        {"q": query, "limit": limit},
    )
    return [dict(r._mapping) for r in rows]


async def _has_vectors(session: AsyncSession, column: str) -> bool:
    return bool(
        await session.scalar(
            text(f"SELECT 1 FROM transcript_chunks WHERE {column} IS NOT NULL LIMIT 1")
        )
    )


def _fuse(
    dense: list[dict], lexical: list[dict], top_k: int
) -> list[RetrievedChunk]:
    """RRF, then diversity cap, then relevance floor."""
    merged: dict[str, dict] = {}

    for rank, row in enumerate(dense, start=1):
        key = str(row["id"])
        entry = merged.setdefault(key, {"row": row, "score": 0.0})
        entry["score"] += 1.0 / (RRF_K + rank)
        entry["dense_rank"] = rank
        entry["similarity"] = float(row.get("similarity") or 0.0)

    for rank, row in enumerate(lexical, start=1):
        key = str(row["id"])
        entry = merged.setdefault(key, {"row": row, "score": 0.0})
        entry["score"] += 1.0 / (RRF_K + rank)
        entry["lexical_rank"] = rank

    ordered = sorted(merged.values(), key=lambda e: e["score"], reverse=True)

    selected: list[RetrievedChunk] = []
    per_episode: dict[str, int] = {}

    for entry in ordered:
        row = entry["row"]
        similarity = entry.get("similarity")
        has_lexical = entry.get("lexical_rank") is not None

        # Floor: drop only if the dense score is weak AND lexical never hit it.
        # A strong lexical match on a semantically diffuse term (a guest's name,
        # "PLG") is exactly the case the hybrid design exists to keep.
        if not has_lexical and (similarity is None or similarity < SIMILARITY_FLOOR):
            continue

        slug = row["episode_slug"]
        if per_episode.get(slug, 0) >= MAX_PER_EPISODE:
            continue
        per_episode[slug] = per_episode.get(slug, 0) + 1

        selected.append(
            RetrievedChunk(
                chunk_id=row["id"],
                episode_slug=slug,
                episode_title=row["episode_title"],
                guest=row.get("guest"),
                source_url=row.get("source_url"),
                content=row["content"],
                score=entry["score"],
                similarity=similarity,
                lexical_rank=entry.get("lexical_rank"),
                dense_rank=entry.get("dense_rank"),
            )
        )
        if len(selected) >= top_k:
            break

    return selected


async def retrieve(
    session: AsyncSession,
    settings: Settings,
    query: str,
    *,
    top_k: int,
) -> RetrievalResult:
    """Run both arms, fuse, filter. Never raises for an empty result set."""
    if not query.strip() or top_k <= 0:
        return RetrievalResult(chunks=[])

    column = _column(settings)
    candidates = settings.retrieval_candidates

    if not await _has_vectors(session, column):
        # A query against a space with no vectors is a configuration problem,
        # not a bad question — say so explicitly and name the fix (§12.3).
        raise RetrievalEmpty(
            f"No embeddings exist for the '{settings.embed_space}' space. "
            "Ingest the corpus first: python -m app.cli ingest",
            detail={"embed_space": settings.embed_space},
        )

    degraded = False
    reason = None
    dense: list[dict] = []

    try:
        embedder = get_embedder(settings)
        vectors = await embedder.embed([query])
        dense = await _dense_arm(session, vectors[0], column, candidates)
    except Exception as exc:  # noqa: BLE001
        # §12.3: embeddings unavailable mid-request → fall back to the lexical
        # arm alone and flag the response as degraded. Weaker grounding beats
        # no answer, but the user is told which they got.
        degraded = True
        reason = "Embeddings unavailable; searched text only."
        log.warning("dense arm failed, using lexical only",
                    extra={"error": type(exc).__name__})

    lexical = await _lexical_arm(session, query, candidates)

    chunks = _fuse(dense, lexical, top_k)
    log.info(
        "retrieve",
        extra={
            "dense": len(dense),
            "lexical": len(lexical),
            "fused": len(chunks),
            "top_score": round(chunks[0].score, 4) if chunks else None,
            "degraded": degraded,
        },
    )
    return RetrievalResult(chunks=chunks, degraded=degraded, reason=reason)
