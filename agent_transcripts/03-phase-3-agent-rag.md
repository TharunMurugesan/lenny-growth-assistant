# Phase 3 — Ingestion, Retrieval, Routing, Skills, and SSE Streaming

**Date:** 2026-07-31
**Agent:** Claude (Opus) via Claude Code CLI
**Objective:** Make the backend actually answer. Ingest the transcript corpus into the vector
store, build the two-tier intent router, implement Skills A–D, and stream results over SSE.

---

## 1. Prompt

> Phase 3 scope: transcript ingestion into the vector store, the intent router, Skills A/B/C, and
> SSE streaming. Phase 1 constraints carry forward — full files never elided, strict
> backend/frontend separation, robust error handling for missing API keys, Ollama timeouts, and
> database connection failures.

Preceded by a credential blocker: the first Anthropic key supplied returned `401 authentication_error`
and Phase 3 was paused until a working key was provided rather than building the Cloud path against
an unverified credential.

---

## 2. Interpretation

Phase 2 was transcription — `architecture.md` had already resolved the schema and the API contracts,
and the work was mostly typing them in. Phase 3 was not. This is the phase where the design meets
an actual corpus, an actual embedding model, and an actual LLM, and the recurring lesson was that
**numbers chosen before measurement were wrong**. Four of the constants specified in Phase 1 had to
be changed, each because running the system produced evidence the document could not have had.

That shaped the working method: build a piece, run it against real data immediately, and let the
result decide the constant. The relevance floor, the artifact token budget, the classifier token
budget, and the local context window were all set this way. Every one of them was wrong on paper
and is now defensible with a measurement.

The second theme was that **graceful degradation hides bugs**. The system's failure handling is
good — a broken classifier falls back to `qa`, a broken dense arm falls back to lexical. That is the
right behaviour, and it meant a completely dead Tier 2 produced plausible answers for an entire
test round before the logs gave it away. Degradation paths need their own assertions, not just
their own code.

---

## 3. Ambiguities in the specification, and resolutions

### A1 — The corpus layout was unverified (closes O1, O2)

Phase 1 flagged both the file structure and guest-name derivation as unknown. Verified against all
303 files before writing the parser:

- Layout is uniform: `episodes/<slug>/transcript.md`, exactly one file per directory.
- Every file has YAML front matter. `guest` is present in 303/303, `title` in 302, `youtube_url` in
  299 — so `title` and `source_url` need fallbacks and `guest` does not.
- **Guest comes from front matter, not the slug.** The directory `ryan-hoover/` contains an episode
  whose title names Ryan Singer; deriving metadata from paths would have mislabelled it and every
  citation drawn from it.

### A2 — Three speaker formats, not one

The documented shape (`Name (00:00:00):`) covers 301 files. Two others exist: a bare `Name:` label
with no timestamp, and `[00:00:00] Name: text` with the speech inline.

**Resolution:** support all three. §10.1 permits logging and skipping a malformed transcript, and
that path is retained as the true fallback — but exercising it here would have silently discarded
two complete, perfectly readable episodes for want of two regexes.

### A3 — Chunk sizing needs a token count, and the honest options are all approximate

`architecture.md` specifies 800-token chunks. Calling a real tokenizer ~12,000 times per ingest
would dominate the run, and the relevant tokenizer is `nomic-embed-text`'s rather than Claude's.

**Resolution:** a documented word-based approximation (≈0.75 words per token). What matters for
chunking is that the measure is cheap, deterministic, and monotonic in length — not that it matches
any particular model's vocabulary. Stated as an approximation at the definition site so nobody
later mistakes it for exact.

### A4 — `nomic-embed-text` task prefixes

The model documents `search_query:` / `search_document:` prefixes for asymmetric retrieval.

**Resolution:** tested, and **rejected on measurement**. Applying the query prefix against
documents stored without the matching document prefix *narrowed* on/off-topic separation from
0.156 to 0.101. Symmetric no-prefix embedding is the better pairing given the corpus is already
embedded. Recorded because the intuitive choice is the wrong one here.

---

## 4. Failures and corrections

Twelve things were wrong. Every one was found by running the code; none were visible by reading it.

### C1 — The pinned SDK could not express the API the design needed

`anthropic==0.42.0`, pinned in Phase 2, predates `output_config` — the call failed with
`TypeError: unexpected keyword argument 'output_config'`, not an API error. Upgraded to `0.120.2`
and re-pinned. Worth noting that the pin was also far older than the model IDs the project targets;
a dependency pinned "for stability" had quietly become a capability ceiling.

### C2 — The specified classifier technique returns a 400 on the specified model

§7.3 called for a prefilled `{` so the classifier's response is JSON from the first token.
**Assistant-turn prefill returns a 400 on Sonnet 4.6 and the rest of the 4.6+ family.** It happens
to still work on the configured Haiku router model, so the spec was not wrong *today* — but the app
would have broken the instant anyone pointed `ANTHROPIC_ROUTER_MODEL` at Sonnet.

**Correction:** structured outputs (`output_config.format`). Stronger than a prefill — the schema
is enforced rather than encouraged — and it has a natural Local equivalent in Ollama's `format`
parameter, so both providers use the same technique. `architecture.md` §7.3 updated.

### C3 — An invalid JSON schema killed Tier 2 entirely, and nothing looked broken

The schema declared `artifact_type` as `{"type": ["string","null"], "enum": ["html","markdown",null]}`.
The API rejects that: *"Enum value 'html' does not match declared type ['string','null']"*.

**Why it survived a full test round:** §12.3 says a failed classifier defaults to `qa` with the raw
message as the search query. That worked perfectly. Every request answered, every response looked
reasonable, and the entire LLM routing tier was dead — visible only as `tier: "fallback"`,
`confidence: 0.0` in the `meta` frame.

**Correction:** `anyOf` with a separate null branch. The broader lesson is in §2: a degradation path
that is never asserted on is indistinguishable from the happy path.

### C4 — The relevance floor never rejected anything (closes O3)

§10.2 specified a 0.35 cosine floor, chosen before any embeddings existed. Against
`nomic-embed-text` that value is far below the noise band: the query *"quantum chromodynamics
lattice gauge theory"* scored 0.44–0.49 against podcast transcripts and returned a full 8-chunk
result set. Skill A's honest decline — a headline feature — was unreachable.

**Correction:** measured the distribution (on-topic 0.642–0.723, off-topic 0.453–0.486) and set the
floor to **0.55**, inside the gap and deliberately nearer the off-topic ceiling: a false decline is
recoverable, a confident answer synthesized from noise is not. `architecture.md` §10.2 updated with
the measurement table.

### C5 — Skill C's deliverable was being truncated

§7.5 caps `artifact` at 4096 output tokens. A real HTML dashboard does not fit — the first live run
terminated at 9,830 bytes with `complete: false`. The parser reported the truncation correctly, but
Skill C's entire output *is* the artifact, so an honestly-reported unusable artifact is still a
failed skill.

**Correction:** 16384. The response streams, so a larger ceiling costs nothing when unused.

### C6 — The Ship30for30 repair pass streamed the whole essay twice

The length guard fired, and the client received 2,073 words for an essay reported as 1,105.

**Cause:** the repair prompt asked for the complete essay back, and the orchestrator tried to stream
only the changed tail via `repaired[len(prose):]`. A rewrite almost never starts with the original
prefix, so the `startswith` guard failed and the fallback streamed the entire rewritten essay a
second time, directly beneath the first.

**Correction:** the repair now returns **only the continuation**, which is what §8.2's "continuation
pass … without restating" specifies in the first place. My prompt had contradicted the spec it was
implementing. Appending a continuation is also the only shape that streams correctly.

### C7 — …and then produced two takeaway lines

With the continuation appended, both the draft's takeaway and the continuation's survived. §8.2
requires exactly one.

**Correction:** the repair prompt now forbids a takeaway line and is told its material lands after
the draft's conclusion, so it writes supporting depth rather than building to a second ending.

### C8 — Ship30for30 essays cited nothing

`citations: []` on every essay. `SHIP30_SYSTEM` asked for claims to be "traceable to the excerpts"
and for guests to be attributed inline, but never asked for the bracketed `[n]` markers the
citation validator builds the sources list from. Inline attribution names a person; only a bracket
produces a source.

**Correction:** the prompt now asks for both and says why. Essays now carry 8–9 real citations.

### C9 — Off-topic questions were routed to `meta`, bypassing the decline path

*"What is the best recipe for sourdough bread?"* classified as `meta` at 0.95 confidence. `meta`
does not retrieve, so the floor never ran and the carefully-built decline path — with its suggested
reformulations — was skipped entirely. The user still got a sensible refusal, from the wrong code
path and without the reformulation help.

**Correction:** the classifier prompt now states explicitly that off-topic questions are `qa`, that
retrieval detects the gap, and that `meta` must never be chosen merely because a question is
unanswerable.

### C10 — Session auto-titles were silently discarded

A fresh session's first turn set `session.title`, committed successfully, and the database still
read `New chat`.

**Cause, and the most instructive bug of the phase:** FastAPI tears down a `yield` dependency when
the route function returns — which for a `StreamingResponse` is *before* the generator finishes.
Closing the session detaches every ORM object loaded earlier. The `Session` row was `modified: True`
but no longer in `db.dirty`, so `commit()` emitted no UPDATE and raised nothing. Newly `add()`ed
objects are unaffected, which is exactly why the assistant message persisted and only the title
vanished — a partial failure that looks like success.

**Correction:** an explicit `update()` statement, which does not depend on identity-map tracking.

### C11 — The local path silently answered from truncated grounding

Local-mode responses reported `input_tokens: 4096` — exactly. Ollama defaults `num_ctx` to 4096 and
silently truncates anything longer. A Skill A prompt carries 8 retrieved chunks (~6k tokens), so the
model was answering from a prompt with the transcripts cut off, with no error and no warning.

**Correction:** `OLLAMA_NUM_CTX`, default 16384, sized for the largest prompt plus its output
budget. Confirmed by `input_tokens` rising to 5,609 and answer length tripling.

### C12 — The classifier's token budget truncated its own JSON

The live Tier 2 agreement suite failed 2 of 32 cases with unparseable output. §7.3's `max_tokens`
of 128 was sized for a terse prefilled reply; the structured-output schema also carries
`search_query` and `rationale`, and a verbose rationale ran past the cap, cutting the JSON off
before its closing brace. Roughly 1 message in 16 silently degraded to the `qa` fallback.

**Correction:** 400 tokens, plus an explicit instruction to keep `rationale` under 12 words. 32/32
after the change.

### C13 — A performance fix that mostly did not work, kept anyway

Ingest ran at 3.2 chunks/second. Ollama's batch `/api/embed` endpoint measured 3× the throughput of
the legacy per-prompt route on short strings, so the embedder was rewritten to batch — and real
throughput moved to 3.8 chunks/second. The bottleneck is embedding compute on ~750-token chunks,
not round-trips.

**Kept regardless** (it is strictly faster, with a 404 fallback for older daemons) but recorded
because the benchmark that justified it was measured on unrepresentative input. The honest headline
is that a full local ingest takes about an hour and that is inherent, not fixable by batching.

### C14 — A test fixture that was wrong, caught by the suite

`"write a 1250 word essay, no html"` was labelled as a Tier 1 `ship30` hit. It contains both a
length word and a format word, so Tier 1 abstains — correctly, since a keyword matcher cannot parse
the negation "no html", and §7.2 says ambiguous cases fall to Tier 2 rather than guessing. The
fixture was corrected, not the code.

---

## 5. Verification

Executed against the running stack — PostgreSQL 16.14 + pgvector 0.8.6, the real 303-episode
corpus, Anthropic `claude-sonnet-4-6` / `claude-haiku-4-5`, and Ollama `nomic-embed-text` —
not reasoned about.

**Automated:** 147 tests passing (`pytest`), plus 32 opt-in live router-agreement cases behind
`RUN_LIVE_ROUTER_TESTS=1`.

| # | Check | Result |
| :- | :---- | :----- |
| 1 | Artifact parser at chunk sizes 1, 2, 3, 5, 7, 13, 64, whole | Identical output at every size |
| 2 | One character per delta through a full tag (O5) | Type, title, and body all recovered |
| 3 | No byte ever dropped, across 8 fixtures × 8 chunk sizes | Holds |
| 4 | Unclosed artifact | `complete: false`, content preserved |
| 5 | Malformed `type="pdf"` | Degrades to visible text, no exception |
| 6 | Carry buffer bounded | ≤ 512 chars under a 2,000-char unterminated tag |
| 7 | Corpus parses | 303/303 episodes, 45,587 turns, 12,113 chunks |
| 8 | Guest / title / URL coverage | 303 / 303 / 299 |
| 9 | Chunk sizing | median 753 tokens against an 800 target |
| 10 | Ingest idempotency | Second run: 0 written, 96 skipped, 0.1s |
| 11 | Ingest resumability | Per-episode commit; interrupted runs resume |
| 12 | Embedding dimensionality | 768, matching `vector(768)` |
| 13 | Hybrid retrieval | RRF fuses both arms; diversity cap holds at 3/episode |
| 14 | Relevance floor (O3) | On-topic answers; off-topic declines |
| 15 | Tier 1 heuristics | 33 labelled fixtures, no misfires |
| 16 | Tier 2 agreement (O4) | 32/32 live |
| 17 | Follow-up inheritance | "make it longer" after an essay stays `ship30` |
| 18 | Classifier failure | Falls back to `qa` with the raw message |
| 19 | `skill_override` | Skips both tiers, zero model calls |
| 20 | SSE event order | `meta` first, `citations` before `done`, `done` last |
| 21 | Skill A grounded answer | Streams with valid citations |
| 22 | Skill A decline | Template text, empty citations, no model spend |
| 23 | Skill B length guard | 1,318 / 1,319 / 1,294 words — all in the 1125–1375 band |
| 24 | Skill B format | Single takeaway, 13–19 bold phrases, 10–16 bullets |
| 25 | Skill C artifact | `complete: true`, 17,165 bytes, valid standalone HTML |
| 26 | Stream/persistence byte-identity (§9.2) | 17,165 octets both paths, matching tails |
| 27 | Skill D meta | 139 words, no retrieval |
| 28 | History replay | Artifacts inline with byte counts, citations, provenance |
| 29 | Session auto-title | Set on first turn only; unchanged on the second |
| 30 | Local provider end-to-end | `status: ok`, both providers available |
| 31 | Local context window | `input_tokens` 5,609 — no silent truncation |

Checks 14, 23, 25, 26, 29, and 31 each correspond to a bug above; they exist because something was
broken, not because the box needed ticking.

---

## 6. Output

| File | Purpose |
| :--- | :------ |
| `app/utils/artifacts.py` | Streaming `<artifact>` state machine over a bounded carry buffer. |
| `app/utils/sse.py` | Event framing, heartbeats, and the headers that stop proxy buffering. |
| `app/llm/base.py` | Provider protocol, `Msg`/`Usage`, and the §11.3 timeout policies as data. |
| `app/llm/anthropic_provider.py` | Cloud. Structured-output classify, streaming, retry-before-first-token. |
| `app/llm/ollama_provider.py` | Local. NDJSON normalized to plain deltas; `num_ctx` sized to the prompt. |
| `app/llm/embeddings.py` | `OllamaEmbedder` (768) and `VoyageEmbedder` (1024), dimension-checked. |
| `app/llm/registry.py` | `get_provider()` added alongside Phase 2's availability probing. |
| `app/ingestion/{fetch,parse,chunker,pipeline}.py` | Corpus acquisition, three-format parsing, turn-aware windowing, idempotent upsert. |
| `app/agent/types.py` | Shared agent types and the §7.5 routing table as data. |
| `app/agent/prompts.py` | All four skill prompts; single source of truth. |
| `app/agent/intent_router.py` | Tiers 0/1/2, follow-up inheritance, confidence floor. |
| `app/agent/retriever.py` | Hybrid search, RRF, diversity cap, measured relevance floor. |
| `app/agent/orchestrator.py` | The pipeline and the SSE event sequence. |
| `app/routers/chat.py` | Rewritten: the Phase 2 501 seam replaced with a real stream. |
| `app/cli.py` | `ingest` implemented with `--limit-episodes`, `--corpus-dir`, `--embed-space`. |
| `tests/test_artifacts.py` | 101 parser tests, adversarially chunked (O5). |
| `tests/test_intent_router.py` | 33-message fixture suite plus live agreement checks (O4). |

`architecture.md` §7.3, §7.5, and §10.2 were updated in place — each with the measurement that
motivated the change, so the document stays the contract rather than becoming a historical artifact.

---

## 7. Open items

| # | Item | Phase |
| :- | :--- | :---- |
| O6 | **Resolved.** LangChain was evaluated and not adopted. The pipeline is classify → retrieve → prompt → stream with two providers; a framework would have added an abstraction layer over four steps that are each ~40 lines, and every provider-specific detail that actually caused trouble this phase (prefill rejection, `num_ctx`, NDJSON shape, batch embeddings) is one a framework would have hidden rather than solved. | — |
| O7 | Verify AA contrast numerically for every token pair | 4 |
| O8 | Confirm SSE passes through the production proxy unbuffered | Final |
| O10 | Rate limiting (§13, 20 req/min per client key) still unimplemented | 4 |
| O15 | `llama3.1:8b-instruct-q4_K_M` is the configured local model but was never pulled (4.7 GB); Local mode was verified against `llama3.2:1b`. Quality on Skill B at 1B is not representative. | 4 |
| O16 | The relevance floor was calibrated at ~10 episodes and spot-checked as the corpus grew. Re-measure once at the full 303 — a larger corpus raises the chance of a spurious high-similarity match for an off-topic query. | 4 |
| O17 | Orchestrator tests are end-to-end only. The citation validator and the length guard deserve unit tests with a fake provider. | 4 |
| O18 | Ingest throughput is ~4 chunks/sec (~1 hour full corpus), bounded by local embedding compute. A GPU or the Voyage path would change this materially. | — |

Items O1–O5 and O9 are closed. O1/O2 by empirical corpus verification, O3 by the floor measurement,
O4 by the router fixture suite, O5 by the adversarial parser tests, O9 by the `pytest` suite now
existing (147 tests).
