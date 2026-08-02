"""Grounding policy — what the assistant is permitted to answer.

The brief is explicit: the agent must answer *strictly* from Lenny's Podcast
transcripts. That is a product rule, not a prompt suggestion, so it lives here
as evaluable code rather than as a sentence inside a system prompt that a small
model is free to ignore.

Why this module exists at all
----------------------------
The original design delegated the decision to the model: retrieve generously,
then let Skill A's prompt decline when the excerpts do not support an answer.
Claude honours that. `llama3.2:1b` does not — asked how to roast a chicken it
produced cooking advice and attached a citation to an unrelated excerpt, so the
answer *looked* sourced. A rule the model can decline to follow is not a
control.

Design constraints
------------------
1. **No hardcoded questions.** Nothing here enumerates forbidden topics. A
   denylist of subjects would be endless, would drift as the corpus changes,
   and would still miss the next unanticipated question. Scope is defined by
   one thing only: what the corpus can actually support, measured per request.
2. **Evidence in, decision out.** Rules read retrieval evidence and return a
   verdict with a reason. They never see the question text, so they cannot
   accidentally become a keyword filter.
3. **Ordered and named.** Each rule states what it checks and why that
   threshold. A decline can always be attributed to a specific named rule,
   which is what makes the behaviour explainable to an evaluator.

Calibration
-----------
Thresholds were measured, not chosen. Across 29 questions (17 on-topic, 12
off-topic) the mean of the top three dense similarities separated cleanly:

    on-topic   mean3 in [0.6262, 0.8010]
    off-topic  mean3 in [0.0000, 0.6123]

Three cheaper guards were built first and discarded because they did not
survive measurement:

  * content-word overlap between the answer and the excerpts — off-topic
    answers scored 0.85-0.94, because a parametric answer still shares ordinary
    English with any corpus.
  * asking the model to judge its own groundedness — 2/6 correct. It returned
    `answerable: true` while its own reason field read "does not directly
    discuss roasting".
  * the single best similarity — separated, but by 0.0096 rather than 0.0140.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.agent.types import RetrievedChunk

log = logging.getLogger(__name__)

# Mean of the top N similarities. Three rather than one: a single topically
# adjacent passage scoring well is common on off-topic questions, and taking
# the maximum lets that one passage carry the whole decision.
GROUNDING_SAMPLE = 3

# Sits inside the measured gap [0.6123, 0.6262]. Deliberately nearer the lower
# bound: a false decline on a covered topic is recoverable by rephrasing, while
# a confident ungrounded answer is the failure the brief rules out.
MIN_MEAN_SIMILARITY = 0.62


@dataclass(frozen=True)
class Evidence:
    """What retrieval produced for one request. The only policy input."""

    chunk_count: int
    similarities: tuple[float, ...]

    @classmethod
    def from_chunks(cls, chunks: Sequence[RetrievedChunk]) -> Evidence:
        sims = tuple(
            sorted(
                (c.similarity for c in chunks if c.similarity is not None),
                reverse=True,
            )
        )
        return cls(chunk_count=len(chunks), similarities=sims)

    @property
    def mean_top_similarity(self) -> float:
        top = self.similarities[:GROUNDING_SAMPLE]
        return sum(top) / len(top) if top else 0.0


@dataclass(frozen=True)
class Verdict:
    """Allowed, or declined with the rule and reason that decided it."""

    allowed: bool
    rule: str = ""
    reason: str = ""

    @property
    def declined(self) -> bool:
        return not self.allowed


@dataclass(frozen=True)
class Rule:
    name: str
    describe: str
    check: Callable[[Evidence], bool]  # True == this rule declines


ALLOWED = Verdict(allowed=True)


def _nothing_retrieved(e: Evidence) -> bool:
    return e.chunk_count == 0


def _too_weak(e: Evidence) -> bool:
    return e.mean_top_similarity < MIN_MEAN_SIMILARITY


# Ordered cheapest-first; the first rule that fires decides.
RULES: tuple[Rule, ...] = (
    Rule(
        name="no-supporting-passage",
        describe=(
            "Retrieval returned nothing above the similarity floor, so there is "
            "no transcript material to ground an answer in."
        ),
        check=_nothing_retrieved,
    ),
    Rule(
        name="insufficient-relevance",
        describe=(
            f"The strongest passages averaged below {MIN_MEAN_SIMILARITY}, the "
            "level that separated on-topic from off-topic questions when "
            "measured against the corpus. Passages exist but are adjacent "
            "rather than relevant."
        ),
        check=_too_weak,
    ),
)


def evaluate(chunks: Sequence[RetrievedChunk], *, enforced: bool) -> Verdict:
    """Decide whether an answer may be generated from these passages.

    `enforced` is per-provider rather than global. Claude reads the excerpts and
    declines by itself, and its own decline names what the corpus *does* cover,
    which is more useful than a generic template — so the policy runs in
    advisory mode there and is only enforced where the model cannot be trusted
    to enforce it. The decision is logged either way, so the two paths remain
    comparable.
    """
    evidence = Evidence.from_chunks(chunks)

    for rule in RULES:
        if rule.check(evidence):
            log.info(
                "grounding policy declined" if enforced else "grounding policy advisory",
                extra={
                    "rule": rule.name,
                    "enforced": enforced,
                    "chunks": evidence.chunk_count,
                    "mean_top_similarity": round(evidence.mean_top_similarity, 4),
                },
            )
            if not enforced:
                return ALLOWED
            return Verdict(allowed=False, rule=rule.name, reason=rule.describe)

    return ALLOWED
