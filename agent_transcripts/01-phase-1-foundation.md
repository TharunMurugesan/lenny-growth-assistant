# Phase 1 — Project Foundation and Documentation

**Date:** 2026-07-30
**Agent:** Claude (Opus) via Claude Code CLI
**Objective:** Produce the structural markdown deliverables required by the submission guidelines.

---

## 1. Prompt

The operating instruction, summarized (full text preserved in the session record):

> **Role:** Staff-level full-stack AI engineer and systems architect. Build a production-ready
> full-stack application strictly named "The Lenny Growth Assistant". Do not suggest alternative
> names.
>
> **Stack:** React frontend, FastAPI backend, PostgreSQL, agent layer using LangChain or LlamaIndex
> with the Anthropic SDK and local Ollama integrations.
>
> **Strict coding constraints:**
> 1. Always provide the full piece of code — never `// rest of the code here`, `...`, or
>    `# existing code`. When modifying a file, output it whole.
> 2. Maintain strict separation of concerns between the FastAPI backend and the React frontend.
> 3. Ensure robust error handling (missing API keys, Ollama timeouts, database connection failures).
> 4. The Artifact Viewer must render native HTML/CSS and Markdown side by side with the chat. No
>    redirects to external links.
> 5. Implement a clear LLM toggle in UI and backend to switch between Cloud (Claude) and Local
>    (Ollama).
>
> **Phase 1 scope:** Create `README.md` (architecture overview, deployment steps, environment
> variables, local Ollama execution), `design.md` (UI/UX structured around Impeccable.style
> principles, clean two-pane layout), `architecture.md` (Postgres schema, API endpoints, intent
> classification routing logic). Wait for approval before Phase 2.

Reference document: `lenny_growth_assistant_spec.md`, read in full before any file was written.

---

## 2. Interpretation

Phase 1 is documentation, but not throwaway documentation. Three of the four documents are graded
deliverables, and `architecture.md` is the implementation contract for Phases 2–4. The approach
taken was to resolve every design decision now — schema, API shapes, routing tiers, artifact
protocol, error taxonomy — so that later phases are transcription rather than invention. Decisions
deferred to coding time are decisions made under pressure.

Concretely, that meant writing the DDL, the SSE event schema, the artifact tag grammar, and the
error-code table in Phase 1 rather than sketching them.

---

## 3. Ambiguities in the specification, and resolutions

### A1 — Phase 1 lists three documents; the spec requires five deliverables

The Phase 1 instruction names `README.md`, `design.md`, and `architecture.md`. Spec §7 also requires
`PRD.md` and `agent_transcripts/`.

**Resolution:** generated all five. The narrower instruction reads as an emphasis on the three
technical documents, not an exclusion of the other two, and leaving a checklist item unstarted at a
phase gate would be a worse failure than doing slightly more than asked. Flagged explicitly in the
response so the deviation was visible rather than silent.

### A2 — The spec names the Anthropic SDK for the agent layer, and pgvector for embeddings

Anthropic does not expose an embeddings endpoint. Following the spec literally leaves the vector
store with no way to be populated in Cloud mode.

**Resolution:** split the concerns. Generation and classification use the Anthropic SDK as
specified. Embeddings come from Voyage AI (`voyage-3`, 1024-d) in the cloud path and Ollama
(`nomic-embed-text`, 768-d) locally. `EMBED_SPACE` is configured independently of the chat provider,
so Cloud generation over locally-embedded chunks is a valid — and recommended, because it is
free — configuration.

**Consequence that had to be designed around:** a pgvector column has fixed dimensionality and HNSW
indexes are built per column, so 768-d and 1024-d vectors cannot share a column. Resolved with two
nullable vector columns and partial indexes (ADR-3). Recorded as a limitation in `README.md`: a
corpus must be ingested once per embedding space, and querying a space with no vectors returns an
explicit `RETRIEVAL_EMPTY` error rather than silently returning nothing.

### A3 — The spec defines three skills; three do not cover all input

Writing the routing table exposed a gap: "hi", "what can you do?", and "which model is this?" have
nowhere to go. Routed to Skill A they produce a technically correct, practically absurd answer —
that the transcripts do not discuss the assistant's own capabilities.

**Resolution:** added Skill D (`meta`), which answers from a static capability description with no
retrieval. Flagged as an addition beyond the spec everywhere it appears (`architecture.md` §7.5,
§8.4; `PRD.md` FR-4.7 at *Could* priority) so a reviewer can distinguish required from judged.

### A4 — `users` table has no credential columns

Spec §3 defines `users` as `id` and `created_at` only, and no authentication is mentioned anywhere.
But sessions are per-user, which requires *some* identity.

**Resolution:** anonymous identity via an opaque `client_key` generated in the browser, stored in
`localStorage`, sent as `X-Client-Key`, upserted server-side. Per-browser isolation with zero auth
surface, and a real auth subject id substitutes for it later with no schema change (ADR-9). Stated
trade-off: clearing browser storage orphans history.

### A5 — "Impeccable.style principles" is a reference without a definition

**Resolution:** rather than assert specifics about a site not consulted during this phase, the
design philosophy section states plainly that the seven principles are *our reading* of the brief,
and each is written as a rule the implementation is actually held to (one accent colour, hierarchy
through space rather than lines, three radii / three shadows / three durations). A design QA
checklist at the end of `design.md` makes each principle verifiable instead of aspirational.

---

## 4. Failures and corrections

Approaches taken and then reversed while writing these documents.

### C1 — Sanitized HTML injection → sandboxed iframe

**First approach:** render HTML artifacts by sanitizing the model output (DOMPurify-style) and
injecting it into a `div`. Attractive because it inherits app styling and avoids iframe overhead.

**Why it failed:** any sanitizer configured strictly enough to be safe strips `<style>` blocks and
all scripts — which is precisely the content that makes a generated mockup worth previewing. A
sanitizer loose enough to keep them is no longer a security boundary. The approach fails at both
ends simultaneously.

**Correction:** `srcdoc` iframe with `sandbox="allow-scripts"` and deliberately **no**
`allow-same-origin`. Scripts execute, so interactive mockups work; the frame has an opaque origin
and cannot reach the parent DOM, `localStorage`, or the session. Plus an injected CSP blocking
network access so an artifact cannot exfiltrate or beacon. Recorded as ADR-7. The follow-on
consequence — artifacts cannot load remote fonts or images — became an explicit rule in the Skill C
prompt, because a mockup that silently renders unstyled is a worse outcome than one that never
tried.

### C2 — Naive artifact tag detection → carry-buffer state machine

**First approach:** on each streamed chunk, check for `<artifact` and `</artifact>` with substring
matching.

**Why it failed:** tokens split mid-tag. A model emits `<arti`, then `fact type="ht`, then `ml">`.
No individual chunk contains the tag, so detection never fires and tag fragments leak into the chat
pane as visible garbage.

**Correction:** an incremental state machine (`TEXT` → `MAYBE_OPEN` → `IN_ARTIFACT` →
`MAYBE_CLOSE`) over a carry buffer that holds back any trailing substring which is still a viable
prefix of a tag. Bounded at 512 characters so a malformed tag flushes as text instead of stalling
the stream or growing memory without bound. End-of-stream flush guarantees no byte the model
produced is ever dropped. Documented in `architecture.md` §9.2.

### C3 — Preview re-rendering per token → code-first streaming

**First approach:** update the Artifact Viewer's Preview tab on every `artifact_delta`, for maximum
liveness.

**Why it failed:** re-mounting an iframe per token thrashes, and a half-written `<div>` with an
unclosed `<style>` block previews as garbage. The "live" effect actively looks broken.

**Correction:** the Code tab streams during generation and is auto-selected on `artifact_start`;
Preview mounts on `artifact_end` after a 150ms debounce and is then auto-selected. The user still
watches the artifact assemble — just in the representation where partial content is meaningful.

### C4 — LLM-only intent classification → two-tier routing

**First approach:** classify every message with a model call, as the cleanest single code path.

**Why it failed:** it adds 250–600ms to *every* message, including ones where intent is
unmistakable. "Build me an HTML dashboard" does not need a model to be understood, and time to first
token is the metric the interface lives or dies on.

**Correction:** Tier 1 deterministic heuristics (precision-first: fire only when unambiguous, ~0ms)
ahead of a Tier 2 small-model classifier for everything else, with `qa` as the low-confidence
default because it is the most constrained skill and therefore the safest misroute. ADR-4. Accepted
cost: two code paths that must agree, mitigated by a shared route-decision fixture suite in Phase 3.

### C5 — Follow-up turns silently broke retrieval

**Found while writing the routing table, not while coding.** Embedding a follow-up verbatim retrieves
nothing useful: "make it longer" and "what about B2C?" carry no topical signal on their own, so
hybrid search returns noise and the answer degrades — with no error to indicate why.

**Correction, two parts:** (1) the Tier 2 classifier emits a `search_query` field containing a
standalone, pronoun-resolved rewrite of the user's message, which costs nothing extra since the
model call is already happening (ADR-5); (2) short modifier follow-ups inherit the previous message's
skill rather than being reclassified, so "make it longer" after an essay does not return a 200-word
Q&A answer.

### C6 — Word-count iteration loop → one repair pass, then report honestly

**First approach:** loop the Ship30for30 generation until the word count lands inside 1250 ±10%.

**Why it failed:** unbounded latency and token spend for a soft constraint, and every additional
pass is another opportunity to drift away from the retrieved source material. A local 8B model may
never converge.

**Correction:** measure once; if materially short (< 1125), one targeted continuation pass; then
accept and report the true count in the `usage` event and on the message row. The UI shows the real
number and turns it amber when short. ADR-10. The reasoning: overstating compliance is a worse
product failure than missing the target.

### C7 — Retry-on-failure applied uniformly → no retries after first token

**Caught while writing the timeout table.** A blanket retry policy would restart a stream that had
already delivered text, duplicating content the user has read.

**Correction:** retries apply only before the first token. After that, a failure becomes a terminal
`error` event with the partial text preserved and persisted under an honest `finish_reason`.

---

## 5. Output

| File | Purpose |
| :--- | :------ |
| `README.md` | Architecture overview, repo layout, quickstart, full environment-variable reference, local Ollama guide, deployment topology, failure-mode matrix, troubleshooting, deliverables checklist. |
| `design.md` | Seven design principles, layout system with ASCII wireframes, complete light/dark token sets, typography scale, component specifications, Artifact Viewer security and streaming behaviour, state coverage table, responsive rules, accessibility, design QA checklist. |
| `architecture.md` | System context, module layout, request lifecycle, full Postgres DDL with rationale, API contracts, SSE protocol, two-tier routing, four skill specifications, artifact grammar and parser, RAG pipeline, provider abstraction, error taxonomy, security model, observability, performance budgets, ten ADRs. |
| `PRD.md` | Problem, four personas, goals with non-goals and reasoning, six user stories with acceptance criteria, 50 numbered functional requirements, 15 NFRs with targets, success metrics, milestones, risk register, open questions with current positions. |
| `agent_transcripts/README.md` | Folder conventions and log format. |
| `agent_transcripts/01-phase-1-foundation.md` | This log. |

Cross-document consistency was checked deliberately: `PRD.md` requirement IDs map to
`architecture.md` sections, `design.md` states match the `architecture.md` error taxonomy, and the
`README.md` environment table matches the settings referenced throughout.

---

## 6. Open items for later phases

| # | Item | Phase |
| :- | :--- | :---- |
| O1 | Confirm the actual file structure of `ChatPRD/lennys-podcast-transcripts` — the parser is designed to be tolerant, but real format may need adjustment | 3 |
| O2 | Confirm whether guest names are reliably derivable from filenames or need in-content extraction | 3 |
| O3 | Measure real HNSW recall at `ef_search = 64` against this corpus size; tune if the relevance floor rejects too aggressively | 3 |
| O4 | Build the route-decision fixture suite (≥ 30 labelled messages) that keeps Tier 1 and Tier 2 in agreement | 3 |
| O5 | Verify the artifact parser against adversarial chunk splits — one character per delta through a full tag | 3 |
| O6 | Decide whether LangChain is load-bearing or ceremonial. The pipeline (classify → retrieve → prompt → stream) is thin enough that direct SDK calls may be clearer than an abstraction layer. Evaluate at implementation time rather than committing now | 3 |
| O7 | Verify AA contrast numerically for every text/background token pair rather than by eye | 4 |
| O8 | Confirm SSE passes through the intended production proxy unbuffered | Final |

Item O6 is the one worth flagging to the reviewer: the spec permits "LangChain or LlamaIndex", and
the honest engineering position is that a four-stage pipeline with two providers may not benefit
from a framework. That call is made in Phase 3 with the code in front of us, not asserted in
Phase 1.
