"""Re-measure the retrieval relevance floor at full corpus size (O16).

The floor was set to 0.55 in Phase 3 against ~386 chunks from 10 episodes. The
corpus is now 12,113 chunks from 303 episodes — 31x larger. More chunks means
more chances for an off-topic query to find a spurious high-similarity match,
so the question is whether the off-topic ceiling has risen into the floor.

Three query classes, because the interesting failure is not "sourdough bread":

  ON        — squarely covered by the corpus. Must clear the floor.
  OFF       — plainly unrelated. Must not clear it.
  ADJACENT  — business/tech questions the podcast does *not* actually cover.
              These are the hard cases: semantically near the corpus, so they
              score high, but answering them would be fabrication.
"""

from __future__ import annotations

import asyncio
import statistics
import sys

from sqlalchemy import text

sys.path.insert(0, ".")

from app.agent.retriever import SIMILARITY_FLOOR, _column, retrieve  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import dispose_engine, get_session_factory, init_engine  # noqa: E402
from app.llm.embeddings import get_embedder  # noqa: E402

ON = [
    "how do great PMs decide what not to build",
    "what makes a retention loop work",
    "how do you know when you have product market fit",
    "advice on hiring your first product manager",
    "how should startups think about pricing",
    "what does a good onboarding flow look like",
    "how to run effective user research interviews",
    "growth loops versus funnels",
    "how to manage up as a product manager",
    "when should a company adopt product led growth",
    "what metrics matter most for early stage startups",
    "how do you build a strong product culture",
]

OFF = [
    "best recipe for sourdough bread",
    "how to replace a car alternator",
    "the offside rule in football explained",
    "quantum chromodynamics lattice gauge theory",
    "how to prune apple trees in winter",
    "symptoms of vitamin D deficiency",
    "how to tune a guitar to drop D",
    "best hiking trails in Patagonia",
    "how do I train for a marathon",
    "what causes the northern lights",
    "how to repoint brickwork on a Victorian house",
    "rules for castling in chess",
]

ADJACENT = [
    "how do I file a software patent",
    "GAAP revenue recognition rules for SaaS",
    "what is the corporate tax rate in Ireland",
    "how do I structure an ESOP for employees",
    "GDPR data processing agreement requirements",
    "how to negotiate a commercial office lease",
]


async def top_similarities(db, vector, column, limit=10):
    rows = await db.execute(
        text(
            f"""
            SELECT 1 - ({column} <=> (:v)::vector) AS sim
            FROM   transcript_chunks
            WHERE  {column} IS NOT NULL
            ORDER  BY {column} <=> (:v)::vector
            LIMIT  :n
            """
        ),
        {"v": str(vector), "n": limit},
    )
    return [float(r.sim) for r in rows]


async def main() -> None:
    settings = get_settings()
    init_engine(settings)
    embedder = get_embedder(settings)
    column = _column(settings)

    results: dict[str, list[tuple[str, float, int]]] = {}

    async with get_session_factory()() as db:
        total = await db.scalar(text("SELECT count(*) FROM transcript_chunks"))
        print(f"corpus: {total:,} chunks   floor: {SIMILARITY_FLOOR}\n")

        for label, queries in (("ON", ON), ("OFF", OFF), ("ADJACENT", ADJACENT)):
            rows = []
            for q in queries:
                vec = (await embedder.embed([q]))[0]
                sims = await top_similarities(db, vec, column)
                # What the app actually decides, not just the raw similarity.
                result = await retrieve(db, settings, q, top_k=8)
                rows.append((q, sims[0], len(result.chunks)))
            results[label] = rows

    # --- per-class detail ------------------------------------------------
    for label in ("ON", "OFF", "ADJACENT"):
        print(f"--- {label} " + "-" * (58 - len(label)))
        for q, top1, n in results[label]:
            verdict = "ANSWER " if n else "DECLINE"
            flag = ""
            if label == "ON" and n == 0:
                flag = "  <-- FALSE DECLINE"
            if label in ("OFF", "ADJACENT") and n:
                flag = "  <-- FALSE ANSWER"
            print(f"  top1={top1:.3f}  {verdict} ({n:2d})  {q[:44]:<44}{flag}")
        print()

    # --- summary ---------------------------------------------------------
    on = [t for _, t, _ in results["ON"]]
    off = [t for _, t, _ in results["OFF"]]
    adj = [t for _, t, _ in results["ADJACENT"]]

    print("=" * 66)
    print(f"{'class':<10} {'n':>3} {'min':>7} {'mean':>7} {'max':>7}")
    for label, vals in (("ON", on), ("OFF", off), ("ADJACENT", adj)):
        print(
            f"{label:<10} {len(vals):>3} {min(vals):>7.3f} "
            f"{statistics.mean(vals):>7.3f} {max(vals):>7.3f}"
        )

    print()
    print(f"separation ON.min - OFF.max      = {min(on) - max(off):+.3f}")
    print(f"separation ON.min - ADJACENT.max = {min(on) - max(adj):+.3f}")
    print()
    print(f"floor {SIMILARITY_FLOOR} sits {min(on) - SIMILARITY_FLOOR:+.3f} below the worst ON query")
    print(f"floor {SIMILARITY_FLOOR} sits {SIMILARITY_FLOOR - max(off):+.3f} above the best OFF query")
    print(f"floor {SIMILARITY_FLOOR} sits {SIMILARITY_FLOOR - max(adj):+.3f} above the best ADJACENT query")

    false_declines = sum(1 for _, _, n in results["ON"] if n == 0)
    false_answers = sum(1 for _, _, n in results["OFF"] + results["ADJACENT"] if n)
    print()
    print(f"false declines (ON with 0 chunks)          : {false_declines}/{len(ON)}")
    print(f"false answers  (OFF/ADJACENT with >0)      : {false_answers}/{len(OFF) + len(ADJACENT)}")

    await dispose_engine()


asyncio.run(main())
