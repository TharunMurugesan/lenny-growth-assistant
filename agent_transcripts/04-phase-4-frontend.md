# Phase 4 — React UI, History Sidebar, LLM Toggle, Artifact Viewer

**Date:** 2026-08-01
**Agent:** Claude (Opus) via Claude Code CLI
**Objective:** Build the frontend `design.md` specifies — three-zone layout, streaming chat,
session history, the Cloud/Local toggle, and the Artifact Viewer that renders HTML and Markdown in
place.

---

## 1. Prompt

> Phase 4 scope: React chat UI, history sidebar, LLM toggle, Artifact Viewer. The Phase 1
> constraints carry forward — full files never elided, strict backend/frontend separation, robust
> error handling, artifacts rendered natively side-by-side with the chat and never via a redirect,
> and a clear LLM toggle in both UI and backend.

`design.md` opens by stating that Phase 4 implements exactly what it describes and "any deviation
is a bug in the implementation, not a liberty." That framing was taken literally: where the
implementation departs from the document, it is recorded below with the measurement that forced it,
and `design.md` was amended rather than left to disagree with the code.

---

## 2. Interpretation

Phase 3's lesson was that constants chosen before measurement are usually wrong. Phase 4's is
narrower and stranger: **the browser has defaults that quietly override intent.** Three of the six
bugs below were not logic errors at all. They were CSS and DOM defaults doing exactly what the
platform specifies, in a direction nobody wanted:

- `align-items` defaults to `stretch`, and in a *column* flex container that stretches horizontally
  — so a pill badge became a full-width bar.
- `scrollTo({behavior: 'auto'})` resolves `auto` to the *computed CSS* `scroll-behavior`, so one
  line of CSS silently animated every follow-scroll and made autoscroll detach itself.
- An anchor with no colour rule inherits the user agent's blue/purple, which put a second and third
  accent colour on screen in a design whose first stated principle is one accent.

None of these throw. None appear in a log. All three are only findable by looking at the running UI
and asking whether what is on screen is what was specified — which is why this phase was verified in
a real browser rather than by reasoning about JSX.

The other theme was **verifying the claims the design document makes about itself**. `design.md`
asserts AA contrast in both themes. Computing all 56 token pairs found six failures, four of which
needed new values. An accessibility claim that has never been calculated is a hope, not a
commitment.

---

## 3. Ambiguities in the specification, and resolutions

### A1 — SSE over `fetch`, not `EventSource`

`design.md` and `README.md` both say "fetch + ReadableStream (SSE)" without saying why.

**Resolution and the reason:** `EventSource` cannot be used at all here. It is GET-only, so it
cannot carry the JSON body `/api/chat` requires, and it cannot set the `X-Client-Key` header that
identifies the user. The SSE framing is therefore parsed by hand over a `ReadableStream`, with the
same buffer discipline the server-side artifact parser needs — a network chunk boundary can fall
mid-frame, so only complete `\n\n`-terminated frames are ever dispatched.

### A2 — Contrast on `--text-tertiary`

WCAG exempts disabled controls from contrast requirements, and the token's stated use is
"placeholders, disabled".

**Resolution:** treated as **not** exempt. The token is also used for captions, metadata, the
sidebar group labels, list markers, and the model caption under the toggle — all of which are body
text a user is expected to read. Exempting it on a technicality would have left the most-used
secondary text in the app at 2.5:1.

### A3 — Where the artifact "lives" after a stream ends

The pane is fed by live stream state while generating, but the persisted message carries its own
artifact object with a different shape (no `streaming`, no `complete` — those are live-stream
concepts).

**Resolution:** the viewer treats absent as settled-and-whole, comparing against explicit `false`
rather than testing truthiness. Without that, an artifact reopened from a chip stayed stuck on the
Code tab forever, because `complete` was `undefined` and the auto-select branch never fired.

---

## 4. Failures and corrections

Six bugs, all found by driving the real UI in a browser.

### C1 — The skill badge stretched to the full column width

In the pre-first-token waiting state, the badge sits in a `flex-direction: column` container.
`align-items` defaults to `stretch`, which in a column container is the *horizontal* axis, so the
pill grew to ~700px.

**Correction:** `align-items: flex-start` on `.waiting`. Notable only because the same badge
rendered correctly inside the assistant message — the component was fine and its container was not,
which is the kind of bug that survives a component-level review.

### C2 — Every assistant turn rendered twice

On stream completion the app refetches the session so the transcript shows the persisted row rather
than the in-memory approximation. But the live stream state was never cleared, so for the rest of
the session both were in the transcript: the same message, twice, with the same artifact chip.

**Correction:** reset the stream after the refetch, and promote the finished artifact into
`openArtifact` first so the pane survives the handover. That required threading the final artifact
out of the hook through a ref — reading it from state inside `onComplete` sees a stale closure.

### C3 — Autoscroll detached itself mid-stream

The "Jump to latest" pill appeared while the user was doing nothing, and the stream stopped
following.

**Cause:** `.chat__scroll` declared `scroll-behavior: smooth`. Per spec,
`scrollTo({behavior: 'auto'})` resolves `auto` to the element's *computed* `scroll-behavior` — so
every follow-scroll became an animation, the scroll handler fired mid-flight, measured a large
distance from the bottom, and flipped the stick-to-bottom flag off. The feature disabled itself.

**Correction:** removed the CSS declaration and pass `behavior: 'instant'` explicitly for
stream-following, keeping `'smooth'` only on the jump button where it is actually wanted. The CSS
now carries a comment explaining why the obvious-looking declaration must not come back.

### C4 — Source links rendered in browser blue and purple

`.md a` set the accent colour, but the sources list is not rendered Markdown — it is React
elements — so its links fell through to the user agent stylesheet.

**Correction:** an explicit rule for `.sources__body a` including `:visited`. Small, but it is a
direct violation of the design's first principle: one accent colour, learned instantly.

### C5 — Contrast failed on six token pairs (closes O7)

All 7 text tokens were computed against all 4 surface tokens in both themes — 56 pairs. Six failed
the 4.5:1 AA threshold `design.md` commits to:

| Token | Specified | Measured | Corrected |
| :---- | :-------- | :------- | :-------- |
| `--text-tertiary` (light) | `#9A9A91` | 2.51–2.84:1 | `#6D6D67` |
| `--text-tertiary` (dark) | `#77776E` | 4.08:1 | `#8B8B82` |
| `--warning` (light) | `#B45309` | 4.44:1 | `#A84E08` |
| `--success` (light) | `#157F5A` | 4.40:1 | `#11694A` |

Each replacement is the smallest step along the same warm ramp that clears 4.5:1 against the
*darkest* surface the token actually appears on — `--bg-inset`, not `--bg-canvas`, which is what
the marginal `--warning` and `--success` misses turned on. `design.md`'s palette tables and
accessibility section were both updated. After the change: 56/56 pass.

### C6 — Three hardcoded `#fff` values

Caught by grepping for hex literals outside `tokens.css`, which is the QA checklist's first item.
Two were text on an accent fill, for which the design defines no token.

**Correction:** added `--text-on-accent` rather than leaving three literals in place — a colour
repeated in three components is precisely what the token system exists to prevent. The third, the
iframe's default background, was kept as a literal *and documented*: it is the ground an artifact
renders on when it sets none of its own, and deliberately does not follow the app theme, because
imposing the app's palette inside the frame would misrepresent what the model produced.

### A near-miss worth recording

Three separate times, a browser click appeared to do nothing and looked like an application bug —
the session row would not open. Clicking the same element programmatically worked every time. The
automation was resolving a wrapper element rather than the `<button>`; the app was correct
throughout. It is recorded because the tempting move was to "fix" working code, and the thing that
prevented it was checking whether the request ever reached the server before touching anything.

---

## 5. Verification

Driven in a real Chrome session against the running stack — FastAPI on `:8000`, Vite on `:5173`,
PostgreSQL 16.14 + pgvector 0.8.6, the full 12,113-passage corpus, Anthropic `claude-sonnet-4-6`,
and Ollama for local embeddings.

| # | Check | Result |
| :- | :---- | :----- |
| 1 | Empty state, four starter cards, corpus count | Renders; "12,113 passages indexed" |
| 2 | Skill badge before first token | `SKILL C · ARTIFACT` from the `meta` frame |
| 3 | Escalating wait labels | "Retrieving from transcripts…" at 3s |
| 4 | Send becomes Stop while streaming | Confirmed |
| 5 | Three-zone layout on artifact | Chat reflows, pane slides in |
| 6 | Code tab auto-selected while streaming | Confirmed, with line numbers and follow-scroll |
| 7 | Preview mounts after `artifact_end` | Full cohort-retention dashboard renders |
| 8 | iframe `sandbox` | `allow-scripts`, no `allow-same-origin` |
| 9 | Artifact renders on its own ground | Dark artifact inside light app chrome |
| 10 | Session auto-title from first message | Confirmed |
| 11 | History replay | 4 messages, artifact chip with byte size, no duplication |
| 12 | Reopen artifact from chip | Preview auto-selects (was stuck on Code) |
| 13 | Skill A citations | `[2] [3] [4]` inline, `Sources (4)` expands with links |
| 14 | Theme toggle | System → Light applies without reload |
| 15 | Prose measure | Exactly 720px |
| 16 | AA contrast, 56 token pairs, both themes | 56/56 pass after C5 |
| 17 | No `alert` / `confirm` / `prompt` | None in source |
| 18 | No `dangerouslySetInnerHTML` | None (comment only) |
| 19 | No hex literals outside `tokens.css` | One, documented (iframe ground) |
| 20 | Production build | Succeeds; 105 KB gzipped JS, 13 KB CSS |

Checks 1, 12, 15, 16, and 19 each correspond to a bug above.

---

## 6. Output

| File | Purpose |
| :--- | :------ |
| `frontend/src/api/client.js` | REST client, `X-Client-Key` handling, §5.8 error envelope as a typed error. |
| `frontend/src/api/stream.js` | SSE parser over `ReadableStream` with frame buffering. |
| `frontend/src/hooks/useChatStream.js` | rAF-coalesced token flushing, wait-stage escalation, preview debounce. |
| `frontend/src/hooks/useSessions.js` | Optimistic create/rename/delete with rollback; sidebar grouping. |
| `frontend/src/hooks/useHealth.js` | Polls `/api/health`; the single source for toggle availability. |
| `frontend/src/hooks/usePreferences.js` | Persisted theme, provider, pane width. |
| `frontend/src/components/ArtifactViewer.jsx` | Sandboxed iframe, injected CSP, Preview/Code tabs, resize, fullscreen. |
| `frontend/src/components/Markdown.jsx` | Markdown → React elements; serif for Skill B. |
| `frontend/src/components/Message.jsx` | Skill badge, sources, artifact chip, provenance stamp. |
| `frontend/src/components/ChatPane.jsx` | Autoscroll with detach, wait states, error cards. |
| `frontend/src/components/Composer.jsx` | Auto-grow, Enter/Shift+Enter, Send↔Stop. |
| `frontend/src/components/Sidebar.jsx` | Grouped history, inline rename and inline delete confirm. |
| `frontend/src/components/LLMToggle.jsx` | Segmented control, status dots, disabled-with-reason. |
| `frontend/src/components/EmptyState.jsx` | Hero, four skill-mapped starter cards, empty-corpus notice. |
| `frontend/src/styles/tokens.css` | Every colour, radius, spacing step, duration. |
| `frontend/src/styles/app.css` | Component styles; no literals outside the token set. |

`design.md` §Design Tokens and §Accessibility were updated in place with the measured contrast
values, so the document remains the contract rather than becoming a historical artifact.

---

## 7. Open items

| # | Item | Status |
| :- | :--- | :----- |
| O7 | **Closed.** AA contrast verified numerically for all 56 token pairs in both themes; four token values corrected. | — |
| O8 | Confirm SSE passes through the production proxy unbuffered. Still open — `X-Accel-Buffering: no` is set, but nothing has been deployed behind nginx to prove it. | Deployment |
| O10 | Rate limiting (§13, 20 req/min per client key) remains unimplemented. | Backend |
| O15 | `llama3.1:8b-instruct-q4_K_M` is the configured local model but was never pulled (4.7 GB). Local mode was verified against `llama3.2:1b`; response quality at 1B is not representative of the intended local experience. | Ops |
| O16 | **Closed — and the concern was justified.** Re-measured across all 12,113 chunks with 30 queries: the on-topic/off-topic gap that justified 0.55 was an artifact of the 386-chunk sample. The classes now overlap (on-topic min 0.583 < off-topic max 0.597) and no cosine threshold separates them; mean-of-top-8 is inverted. 0.55 was kept, because raising it falsely declines covered topics and because the floor is a pre-filter, not the grounding guarantee — Skill A's prompt declines adjacent queries correctly and more specifically than the template would. Verified end to end; `architecture.md` §10.2 and `retriever.py` updated with the measurement. | — |
| O17 | Orchestrator tests are end-to-end only; the citation validator and length guard deserve unit tests with a fake provider. | Backend |
| O19 | The frontend has no automated tests. The design QA checks run here were executed by hand in a browser session; the mechanical ones (contrast, token discipline, no `alert`) are scriptable and should be. | Frontend |
| O20 | Session list virtualization past 100 rows (design.md §Sidebar) is specified but not implemented — the list currently renders every row. | Frontend |
| O21 | Responsive breakpoints are implemented in CSS but were only verified at desktop width. The < 768px drawer and overlay-sheet behaviour needs checking on a real narrow viewport. | Frontend |

Items O1–O6 and O9 closed in earlier phases.
