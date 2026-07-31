# The Lenny Growth Assistant — Product Requirements Document

**Status:** Approved for build
**Version:** 1.0
**Last updated:** 2026-07-30
**Source:** Formalized from `lenny_growth_assistant_spec.md` §1

---

## 1. Overview

### 1.1 Problem

Lenny's Podcast is one of the densest available bodies of practical product-management and growth
knowledge — hundreds of hours of interviews with operators who have actually shipped and scaled
products. That knowledge is effectively unsearchable. It exists as long-form audio and raw
transcripts, so answering a specific question ("how do experienced PMs decide what *not* to build?")
means either remembering which episode covered it or reading transcripts by hand.

Meanwhile, general-purpose chat assistants will answer the same question instantly and
confidently — from generic training data, with no attribution, and with no way to distinguish an
operator's hard-won position from an average of internet advice.

### 1.2 Solution

A conversational web application that treats Lenny's Podcast transcripts as its **only** source of
truth for substantive answers, and that can do three distinct things with that corpus:

1. Answer questions strictly from the transcripts, with citations, and decline when the corpus does
   not cover the question.
2. Synthesize retrieved insight into a publication-ready ~1250-word Ship30for30-style essay.
3. Generate renderable artifacts — HTML/CSS mockups, Markdown documents — displayed live beside the
   conversation.

All three run over a user-selectable LLM: **Cloud** (Anthropic Claude) or **Local** (Ollama), with no
change to behaviour or interface.

### 1.3 What makes this different

| Ordinary chat assistant | The Lenny Growth Assistant |
| :---------------------- | :------------------------- |
| Answers from general training data | Answers from a specific, cited corpus — or admits it cannot |
| One response format | Three routed skills with distinct output contracts |
| Code arrives as text to copy elsewhere | Artifacts render natively, side by side, in-app |
| Locked to one vendor | Cloud or Local, switchable per message |
| Opaque reasoning | The routed skill, provider, model, and sources are visible on every answer |

---

## 2. Users

### 2.1 Primary — the practitioner PM

A product or growth lead making a decision this week. Has heard the relevant episode, cannot
remember which one, and needs the substance in ninety seconds. Values attribution: knowing *who*
said it is part of knowing whether to trust it.

*Needs:* fast, specific, citable answers; disagreements between guests surfaced rather than
flattened.

### 2.2 Primary — the builder-in-public

Writing daily, publishing on LinkedIn or a newsletter, running out of well-grounded ideas. Wants a
first draft with a real hook and real substance behind it, not a listicle.

*Needs:* Skill B — long-form, correctly formatted, sourced, and ready to edit rather than rewrite.

### 2.3 Secondary — the privacy-constrained operator

Cannot send strategy questions to a third-party API — employer policy, an NDA, or personal
preference.

*Needs:* Local mode that is genuinely equivalent in capability, fully offline, with honest
communication about where a smaller model falls short.

### 2.4 Secondary — the technical evaluator

Reviewing this as an engineering artifact. Reads the router logic, checks whether the artifact
sandbox is actually safe, and looks for whether failure modes were designed or discovered.

*Needs:* observable routing, honest state handling, documented decisions and trade-offs.

---

## 3. Goals and Non-Goals

### 3.1 Goals

| # | Goal | Measure of success |
| :- | :--- | :----------------- |
| G1 | Answers are grounded in the transcript corpus | Every substantive answer carries citations; unsupported questions are declined rather than answered |
| G2 | Long-form output meets the Ship30for30 contract | ~1250 words with hook, bullets, bolding, and a single takeaway; real word count always reported |
| G3 | Artifacts render in-app, side by side | HTML/CSS and Markdown render in the right pane; zero external redirects |
| G4 | Cloud and Local are interchangeable | Both providers complete all three skills with streaming; switchable per message |
| G5 | Conversations persist | Sessions and messages survive restart; artifacts restore on reopen |
| G6 | Failures are legible | Every failure mode has a specific, actionable UI state — no bare spinners, no raw stack traces |
| G7 | Routing is observable | The user can see which skill handled their message, on which provider and model |

### 3.2 Non-Goals

Explicitly out of scope for v1, with reasoning:

| Non-goal | Why |
| :------- | :-- |
| User authentication | The specification's `users` table has no credential columns. Anonymous per-browser identity is sufficient and adds no auth surface. |
| Multi-user collaboration | No shared-session requirement; would drive real-time sync complexity. |
| Audio playback or timestamp deep-links | The corpus is text. Adding media hosting is a different product. |
| Corpus beyond Lenny's Podcast | Grounding claims are only defensible against a known corpus. |
| File upload / user documents | Would dilute the "strictly Lenny's insights" guarantee. |
| Editing or forking generated artifacts | View, copy, download only. An artifact editor is its own product. |
| Export to Notion, Docs, or Substack | Copy and download cover the actual need. |
| Fine-tuning | RAG delivers grounding and attribution; fine-tuning delivers neither. |
| Automatic reranking model | Marginal recall gain at top-8 for real latency and a second model dependency per provider. |
| Mobile native apps | The responsive web layout covers mobile use. |

---

## 4. User Stories and Acceptance Criteria

### US-1 — Ask a grounded question

> As a PM, I want to ask a question about growth and get an answer drawn only from Lenny's
> Podcast, with sources, so I can trust and verify it.

- **Given** an indexed corpus, **when** I ask a question it covers, **then** I receive a streamed
  answer with `[n]` markers and an expandable source list naming episode and guest.
- **When** the corpus does *not* cover my question, **then** the assistant says so plainly and
  suggests reformulations. It does not answer from general knowledge.
- **When** guests disagree, **then** both positions appear, attributed by name.
- Citations shown correspond only to excerpts actually used in the answer.

### US-2 — Generate a Ship30for30 essay

> As a builder-in-public, I want a ~1250-word essay on a topic, grounded in the podcast, so I have
> a strong draft to edit.

- Output is 1250 words ±10%; the true count is displayed.
- It opens with a 1–2 sentence hook that makes a specific claim, not a generic preamble.
- It contains at least two bullet clusters and 5–8 bolded key phrases.
- It ends with exactly one `The takeaway:` line.
- Claims trace to the corpus; named guests are attributed inline.
- If the model falls materially short, one repair pass runs and the final count is reported
  honestly — never overstated.

### US-3 — Generate a renderable artifact

> As a PM, I want to ask for a dashboard mockup and see it rendered next to the chat, not as code
> I have to take elsewhere.

- The right pane opens automatically when an artifact begins streaming.
- Preview and Code tabs are both available; Code streams live, Preview mounts on completion.
- HTML renders with its own CSS and any inline scripts working.
- Markdown renders as formatted prose, not raw text.
- Copy and Download work; the pane can be closed and reopened from the message without loss.
- No action ever navigates away from the application.

### US-4 — Switch between Cloud and Local

> As a privacy-constrained operator, I want to run everything locally, and switch back when I want
> maximum quality.

- A toggle is visible at all times with the resolved model named beneath it.
- The selection applies to the next message immediately; no reload, no restart.
- An unavailable provider is disabled with a tooltip stating the specific reason.
- Local mode issues no external network request — classification, embeddings, and generation are all
  local.
- Each message records and displays which provider and model produced it.

### US-5 — Manage conversation history

> As a returning user, I want my conversations saved and findable.

- **New chat** creates an empty session immediately.
- Sessions list newest-first, grouped Today / Previous 7 days / Previous 30 days / Older.
- A session is auto-titled from the first exchange; it can be renamed and deleted.
- Reopening a session restores full history including working artifacts.
- Deleting asks for inline confirmation and removes all messages.

### US-6 — Understand what the system is doing

> As a user, I want to know how an answer was produced.

- A skill badge appears before the first token: Skill A, B, or C.
- Provider and model are stamped on every assistant message.
- Retrieved sources are inspectable.
- Word count is shown for Skill B.
- An incomplete or stopped response is labelled as such and never presented as finished.

---

## 5. Functional Requirements

Numbered for traceability. Each maps to a section of `architecture.md`.

### 5.1 Conversation

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-1.1 | Create a chat session | Must |
| FR-1.2 | List sessions newest-first with date grouping | Must |
| FR-1.3 | Retrieve full message history for a session, artifacts inline | Must |
| FR-1.4 | Auto-title a session from its first exchange | Must |
| FR-1.5 | Rename a session | Should |
| FR-1.6 | Delete a session, cascading its messages | Should |
| FR-1.7 | Persist user and assistant messages, including partial responses | Must |
| FR-1.8 | Stream assistant responses token by token | Must |
| FR-1.9 | Allow the user to stop an in-flight response, preserving partial text | Should |

### 5.2 Retrieval

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-2.1 | Ingest transcripts from `ChatPRD/lennys-podcast-transcripts` | Must |
| FR-2.2 | Chunk on speaker-turn boundaries with overlap, retaining episode and guest metadata | Must |
| FR-2.3 | Store chunks and vectors in Postgres with pgvector | Must |
| FR-2.4 | Support both a local (768-d) and a cloud (1024-d) embedding space | Must |
| FR-2.5 | Hybrid retrieval — vector plus lexical, fused by reciprocal rank | Should |
| FR-2.6 | Cap chunks per episode to force cross-episode synthesis | Should |
| FR-2.7 | Apply a relevance floor so irrelevant context is dropped, not summarized | Must |
| FR-2.8 | Idempotent, resumable ingestion via content hashing | Should |

### 5.3 Agent routing

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-3.1 | Classify every message into `qa`, `ship30`, `artifact`, or `meta` before generation | Must |
| FR-3.2 | Resolve unambiguous intent by deterministic heuristics, with no model call | Should |
| FR-3.3 | Fall back to a small-model classifier producing structured JSON | Must |
| FR-3.4 | Default to grounded Q&A when confidence is below threshold | Must |
| FR-3.5 | Rewrite follow-up messages into standalone retrieval queries | Must |
| FR-3.6 | Inherit the previous skill for short modifier follow-ups | Should |
| FR-3.7 | Honour an explicit `skill_override` from the client | Should |
| FR-3.8 | Persist and expose the routed skill on each message | Must |

### 5.4 Skills

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-4.1 | Skill A answers strictly from retrieved context with `[n]` citations | Must |
| FR-4.2 | Skill A declines honestly when grounding is unavailable | Must |
| FR-4.3 | Skill B produces 1250 words ±10% with hook, bullets, bolding, single takeaway | Must |
| FR-4.4 | Skill B measures word count and performs at most one repair pass | Should |
| FR-4.5 | Skill C wraps output in `<artifact type="…" title="…">` tags | Must |
| FR-4.6 | Skill C HTML is a self-contained document with no external references | Must |
| FR-4.7 | Skill D answers capability questions without retrieval | Could |

### 5.5 LLM abstraction

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-5.1 | Accept `llm_provider` per request | Must |
| FR-5.2 | Implement Cloud via the Anthropic SDK with streaming | Must |
| FR-5.3 | Implement Local via Ollama with streaming | Must |
| FR-5.4 | Normalize both providers behind one interface | Must |
| FR-5.5 | Report per-provider availability with a specific reason when unavailable | Must |
| FR-5.6 | Apply provider-appropriate timeouts and bounded retries | Must |
| FR-5.7 | Never retry after the first token has been delivered | Must |
| FR-5.8 | Persist provider and model on each message | Should |

### 5.6 Artifacts

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-6.1 | Parse `<artifact>` tags incrementally, tolerating splits across token boundaries | Must |
| FR-6.2 | Emit prose and artifact content on separate stream channels | Must |
| FR-6.3 | Render HTML in a sandboxed iframe without same-origin access | Must |
| FR-6.4 | Render Markdown as React elements, never raw HTML injection | Must |
| FR-6.5 | Provide Preview and Code tabs, with Code streaming live | Must |
| FR-6.6 | Support copy, download, reload, fullscreen, and resize | Should |
| FR-6.7 | Persist artifacts so they restore when a session is reopened | Must |
| FR-6.8 | Close unterminated artifacts at stream end and flag them incomplete | Must |

### 5.7 Interface

| ID | Requirement | Priority |
| :- | :---------- | :------- |
| FR-7.1 | Two-pane layout with collapsible history sidebar and conditional artifact pane | Must |
| FR-7.2 | Visible Cloud/Local toggle showing the resolved model | Must |
| FR-7.3 | Skill badge on every assistant message | Should |
| FR-7.4 | Expandable source list for grounded answers | Should |
| FR-7.5 | Dark mode with a system-preference default | Should |
| FR-7.6 | Designed state for every async and failure condition | Must |
| FR-7.7 | Full keyboard operation with visible focus states | Should |
| FR-7.8 | Responsive from 360px to wide desktop | Should |

---

## 6. Non-Functional Requirements

| ID | Requirement | Target |
| :- | :---------- | :----- |
| NFR-1 | Time to first token, Cloud, warm | < 1.5s p50 |
| NFR-2 | Time to first token, Local, warm model | < 6s p50 |
| NFR-3 | Session list load | < 300ms p95 |
| NFR-4 | Retrieval (embed + hybrid search + fusion) | < 250ms p95 |
| NFR-5 | Streaming render smoothness | One React commit per animation frame maximum |
| NFR-6 | Runs with no `ANTHROPIC_API_KEY` present | Local mode fully functional, Cloud clearly disabled |
| NFR-7 | Runs fully offline in Local mode | Zero external network requests |
| NFR-8 | Secrets never appear in logs, errors, or API responses | Absolute |
| NFR-9 | Artifact HTML cannot access the parent origin, storage, or session | Absolute |
| NFR-10 | Unhandled exceptions never return a stack trace to the client | Absolute |
| NFR-11 | Backend is stateless and horizontally scalable | All state in Postgres |
| NFR-12 | Ingestion is resumable after interruption | No duplicate rows, no repeated embedding spend |
| NFR-13 | Body text meets WCAG AA contrast in both themes | ≥ 4.5:1 |
| NFR-14 | `prefers-reduced-motion` removes non-essential motion | Honoured |
| NFR-15 | No browser `alert`, `confirm`, or `prompt` anywhere | Absolute |

---

## 7. Success Metrics

Product quality is judged on grounding and format compliance, not engagement.

| Metric | Target | How measured |
| :----- | :----- | :----------- |
| Citation coverage | ≥ 95% of Skill A answers carry ≥ 1 valid citation | Citation count on message rows |
| Honest refusal rate | Off-corpus questions are declined, not answered | Held-out set of 20 out-of-domain questions |
| Ship30for30 length compliance | ≥ 80% of Cloud essays land within 1250 ±10% | `word_count` on message rows |
| Artifact render success | ≥ 95% of HTML artifacts render without a blank frame | Manual review of a 20-artifact sample |
| Router accuracy | ≥ 90% correct on a labelled set of 30 messages | Fixture-based route-decision tests |
| Provider parity | All three skills complete end-to-end on both providers | Manual matrix walk before sign-off |
| Failure legibility | Every code in the error taxonomy renders a specific UI state | Induced-failure walkthrough |

---

## 8. Milestones

| Phase | Deliverable | Exit criteria |
| :---- | :---------- | :------------ |
| **1** | Foundation documentation | `README.md`, `design.md`, `architecture.md`, `PRD.md`, `agent_transcripts/` complete and internally consistent |
| **2** | Database and backend infrastructure | Schema applies cleanly; `/api/health` truthful; session CRUD works end to end |
| **3** | Agent, RAG, and streaming | Corpus ingested; router hits ≥ 90% on fixtures; all three skills stream over SSE on both providers |
| **4** | Frontend and Artifact Viewer | Full chat UI, working toggle, artifacts rendering live; every designed state reachable |
| **Final** | Submission | Deliverables checklist complete; 2–3 minute demo recorded |

---

## 9. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
| :--- | :----- | :--------- | :--------- |
| Local 8B model misses the 1250-word target | Skill B under-delivers in Local mode | High | One repair pass; honest word-count reporting; document that a 14B-class model does better |
| Small models produce malformed `<artifact>` tags | Artifact pane stays empty | Medium | Explicit format rules in the prompt; parser closes unterminated tags and flags them; source always recoverable from the Code tab |
| Transcript corpus structure changes upstream | Ingestion breaks | Medium | Tolerant parser, per-episode error isolation, one bad file never fails the run |
| Embedding-space mismatch between ingest and query | Silent empty retrieval | Medium | Separate columns per space; explicit `RETRIEVAL_EMPTY` error naming the fix; counts per space on `/api/health` |
| Ollama cold start looks like a hang | User abandons the request | High | 90s first-token allowance plus an escalating "warming up the local model" state |
| Proxy buffering defeats SSE | Streaming appears broken in production | Medium | `X-Accel-Buffering: no`; documented deployment requirement |
| Prompt injection via transcript content | Model follows instructions from the corpus | Low | Delimited context, explicit data-not-instruction framing, artifact tags honoured only from the output stream |
| Artifact HTML attempts to reach the app or network | Security incident | Low | Sandboxed iframe with an opaque origin and a network-blocking CSP |
| Cloud API cost during development | Budget overrun | Medium | Local embeddings as the default; small model for classification; `--limit-episodes` during ingest |

---

## 10. Open Questions

Tracked and resolved as phases land, rather than left implicit.

| # | Question | Current position |
| :- | :------- | :--------------- |
| Q1 | Should the default embedding space be local or Voyage? | **Local.** Free, offline, adequate at this corpus size; Voyage remains configurable. |
| Q2 | Should Cloud default to Sonnet or Opus? | **Sonnet 4.6.** Latency and cost suit a streaming chat UI; Opus 4.8 is a one-variable change for deepest synthesis. |
| Q3 | Should the user be able to force a skill from the UI? | Yes, via the empty-state starter cards; `skill_override` exists in the API for a future explicit selector. |
| Q4 | How many artifacts may one response contain? | Exactly one. Multiple per response complicates the pane for no clear benefit; multiple per *conversation* is supported. |
| Q5 | Should conversation history be sent to the model? | Last 6 messages, trimmed by token budget — enough for follow-ups without diluting retrieved context. |
| Q6 | Is reranking worth adding? | Not in v1 (ADR-3 rationale). Revisit if floor-rejection metrics show recall problems. |
