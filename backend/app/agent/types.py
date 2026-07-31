"""Shared agent-layer types.

Kept in their own module so `prompts`, `retriever`, `intent_router`, and
`orchestrator` can share them without importing each other — the dependency
direction in §2 is strictly one-way and these types sit below all four.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

SkillName = Literal["qa", "ship30", "artifact", "meta"]
ArtifactType = Literal["html", "markdown"]


@dataclass
class RetrievedChunk:
    """One chunk surviving fusion, diversity, and the relevance floor."""

    chunk_id: uuid.UUID
    episode_slug: str
    episode_title: str
    guest: str | None
    source_url: str | None
    content: str
    score: float
    similarity: float | None = None
    lexical_rank: int | None = None
    dense_rank: int | None = None

    def as_citation(self, n: int) -> dict[str, Any]:
        """The §4.4 citation shape persisted on the message row."""
        return {
            "n": n,
            "episode_title": self.episode_title,
            "guest": self.guest,
            "source_url": self.source_url,
            "chunk_id": str(self.chunk_id),
            "score": round(self.score, 4),
        }


@dataclass
class RouteDecision:
    """What the router concluded, and how it got there."""

    skill: SkillName
    search_query: str
    confidence: float
    tier: Literal["override", "heuristic", "llm", "inherited", "fallback"]
    artifact_type: ArtifactType | None = None
    needs_retrieval: bool = True
    rationale: str = ""

    def as_meta(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "intent": self.skill,
            "confidence": round(self.confidence, 2),
            "tier": self.tier,
            "artifact_expected": self.artifact_type,
        }


@dataclass
class SkillConfig:
    """Per-skill model settings and retrieval budget — §7.5 routing table."""

    top_k: int
    temperature: float
    max_tokens: int
    retrieves: bool = True


# §7.5's routing table, with one measured departure.
#
# The spec sets `artifact` to max 4096. A real HTML dashboard does not fit: the
# first live run hit the cap at 9,830 bytes and terminated with
# `complete: false`. The truncation was reported honestly, but Skill C's entire
# deliverable *is* the artifact, so an honestly-reported unusable artifact is
# still a failed skill. 16384 leaves room for a complete standalone document
# with inline CSS; the response streams, so the larger ceiling costs nothing
# when unused and carries no timeout risk.
SKILL_CONFIG: dict[SkillName, SkillConfig] = {
    "qa": SkillConfig(top_k=8, temperature=0.3, max_tokens=1500),
    "ship30": SkillConfig(top_k=10, temperature=0.7, max_tokens=3500),
    "artifact": SkillConfig(top_k=4, temperature=0.6, max_tokens=16384),
    "meta": SkillConfig(top_k=0, temperature=0.3, max_tokens=400, retrieves=False),
}


@dataclass
class GenerationOutcome:
    """Everything the orchestrator needs to persist after a stream ends."""

    content: str = ""
    artifact_type: str = "none"
    artifact_content: str | None = None
    artifact_title: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    word_count: int | None = None
    finish_reason: str = "stop"
    token_usage: dict[str, int] | None = None
