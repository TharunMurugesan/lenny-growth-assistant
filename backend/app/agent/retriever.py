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

# Measured twice — at 386 chunks (O3) and again at the full 12,113 (O16).
#
# architecture.md §10.2 originally specified 0.35, chosen before any embeddings
# existed. That value never rejects anything: `nomic-embed-text` compresses
# cosine similarities into a high band, so an off-topic query scored 0.44-0.49
# and returned a full result set, leaving Skill A's decline unreachable.
#
# 0.55 was then chosen against a 386-chunk sample that showed a clean gap
# (on-topic 0.642-0.723, off-topic 0.453-0.486). **That gap was an artifact of
# the small corpus.** Re-measured across all 12,113 chunks with 30 queries:
#
#     class      n     min    mean     max
#     on-topic  12   0.583   0.694   0.774
#     off-topic 12   0.476   0.534   0.597
#     adjacent   6   0.543   0.592   0.630     <- business topics not covered
#
# The classes now overlap: on-topic min (0.583) sits *below* off-topic max
# (0.597). No single cosine threshold separates them, and the obvious
# alternatives do not either — mean-of-top-8 is actively inverted, scoring
# "what makes a retention loop work" at 0.558 against "how do I file a software
# patent" at 0.606. More chunks simply means more chances for a topically
# adjacent passage to score well.
#
# 0.55 is kept anyway, for two reasons:
#
#   1. Raising it to clear the off-topic ceiling would falsely decline
#      squarely on-topic queries — at 0.60, "what makes a retention loop work"
#      returns nothing. A false decline on a covered topic is a worse failure
#      than passing chunks the model then declines to use.
#   2. **The floor is a cheap pre-filter, not the grounding guarantee.** Skill
#      A's prompt is the real backstop, and it works: given 8 irrelevant chunks
#      for "how do I structure an ESOP", the model answers "the provided
#      excerpts do not contain any information about structuring an ESOP" and
#      names what the excerpts *do* cover. That decline is more specific and
#      more useful than DECLINE_TEMPLATE would have been.
#
# What 0.55 still buys is the egregious cases — sourdough, northern lights,
# lattice gauge theory — declined for free without spending a model call.
#
# Also tested and rejected: `nomic-embed-text`'s `search_query:` /
# `search_document:` task prefixes. Applying the query prefix alone *narrowed*
# separation, because the stored vectors carry no matching document prefix.
SIMILARITY_FLOOR = 0.55

# --- local-only grounding gate -------------------------------------------
#
# The comment above says the floor is a pre-filter and "Skill A's prompt is the
# real backstop, and it works". That is true of Claude and false of a 1B local
# model, which is the whole problem. Asked "what is the best way to roast a
# chicken?" against chunks about podcasts, llama3.2:1b answered from its own
# knowledge — herbs, salt, rubbing the bird — and attached a citation to an
# unrelated excerpt, so the answer *looked* sourced. Cloud, same question, same
# chunks, declined correctly.
#
# Three guards were built and measured before this one:
#
#   content-word overlap between answer and excerpts — useless. Off-topic
#     answers scored 0.85-0.94 because ordinary English words appear in both.
#   asking the local model to judge its own groundedness — 2/6. It returned
#     answerable=true while its own reason field read "does not directly
#     discuss roasting", and answered the World Cup question from memory.
#   max single similarity — separates, but by only 0.0096.
#
# What survived is the mean of the top three dense similarities, measured over
# 17 on-topic and 12 off-topic questions:
#
#     on-topic   mean3 in [0.6262, 0.8010]
#     off-topic  mean3 in [0.0000, 0.6123]
#
# 0.62 sits in that gap and separated all 29. The margin is thin — this is a
# heuristic, not a proof — so it is applied ONLY on the local path, where there
# is no prompt backstop. Cloud keeps the existing behaviour, which works and
# produces a more specific decline than the template can.
LOCAL_GROUNDING_FLOOR = 0.62
GROUNDING_SAMPLE = 3


def grounding_score(chunks: list[RetrievedChunk]) -> float:
    """Mean of the top `GROUNDING_SAMPLE` dense similarities.

    The mean of three rather than the single best: one topically adjacent chunk
    scoring well is common on off-topic queries, and taking the max lets that
    one chunk carry the whole decision.
    """
    sims = sorted(
        (c.similarity for c in chunks if c.similarity is not None), reverse=True
    )
    if not sims:
        return 0.0
    top = sims[:GROUNDING_SAMPLE]
    return sum(top) / len(top)


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
