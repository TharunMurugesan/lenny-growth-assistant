# The Lenny Growth Assistant

An AI-powered conversational web application that grounds product-management and growth
answers in Lenny's Podcast transcripts, synthesizes Ship30for30-style long-form essays, and
renders generated HTML/CSS and Markdown **natively, side-by-side with the chat** — never via an
external viewer.

The application is LLM-agnostic: a single toggle switches the entire pipeline (classification,
embeddings, generation) between **Cloud** (Anthropic Claude) and **Local** (Ollama) processing.

---

## Table of Contents

1. [Build Status](#build-status)
2. [What It Does](#what-it-does)
3. [Architecture Overview](#architecture-overview)
4. [Repository Layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [Quickstart](#quickstart)
7. [Environment Variables](#environment-variables)
8. [Running with Local Ollama](#running-with-local-ollama)
9. [The LLM Toggle](#the-llm-toggle)
10. [Transcript Ingestion](#transcript-ingestion)
11. [API Surface](#api-surface)
12. [Deployment](#deployment)
13. [Error Handling and Failure Modes](#error-handling-and-failure-modes)
14. [Troubleshooting](#troubleshooting)
15. [Deliverables Checklist](#deliverables-checklist)

---

## Build Status

This repository is being built in four approved phases. This table is the honest current state —
it is updated as each phase is completed and verified.

| Phase | Scope | Status |
| :---- | :---- | :----- |
| **1** | Project foundation and documentation (`README.md`, `design.md`, `architecture.md`, `PRD.md`, `agent_transcripts/`) | ✅ Complete |
| **2** | PostgreSQL schema + SQLAlchemy models, FastAPI application, session and chat routes | ✅ Complete |
| **3** | Transcript ingestion into the vector store, intent router, Skills A/B/C, SSE streaming | ⬜ Not started |
| **4** | React chat UI, history sidebar, LLM toggle, Artifact Viewer | ⬜ Not started |

The backend runs today: the schema applies, the app starts, and `/api/health`, `/api/sessions`
and the validation half of `/api/chat` are live and verified against PostgreSQL 16 + pgvector
0.8.6. **`POST /api/chat` does not yet generate an answer** — it validates the payload, checks
session ownership, resolves the provider, and then returns `501 NOT_IMPLEMENTED`. Generation,
retrieval and SSE streaming arrive in Phase 3, and the frontend in Phase 4; those sections below
still describe the target system rather than shipped behaviour.

---

## What It Does

| Capability | Behaviour |
| :--------- | :-------- |
| **Conversational interface** | ChatGPT-style layout: collapsible session history on the left, chat in the centre, Artifact Viewer on the right. New Chat, auto-titled sessions, full message history. |
| **Skill A — Grounded Q&A** | Retrieves transcript chunks via hybrid search (pgvector + lexical), answers *strictly* from retrieved context, cites episode and guest, and explicitly declines when the corpus does not cover the question. |
| **Skill B — Ship30for30 essay** | Produces a ~1250-word essay with a strong hook, short punchy paragraphs, bullet clusters, bolded key phrases, and a single clear takeaway. Length is validated after generation. |
| **Skill C — Artifact generation** | Emits HTML/CSS or Markdown wrapped in `<artifact type="…">` tags. The backend parses these out of the token stream and the frontend renders them live in the right-hand pane. |
| **LLM agnosticism** | Per-request `llm_provider` of `cloud` or `local`. Cloud uses the Anthropic SDK; local uses Ollama. Both paths stream. |

---

## Architecture Overview

Three processes and one database. The React app never talks to an LLM provider directly — every
model call is brokered by FastAPI, so API keys stay server-side and the provider toggle is
enforced in one place.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  Browser — React 18 + Vite                                                    │
│                                                                               │
│   ┌──────────────┐   ┌────────────────────────┐   ┌────────────────────────┐  │
│   │  Sidebar     │   │  Chat Pane             │   │  Artifact Viewer       │  │
│   │  sessions,   │   │  messages, composer,   │   │  Preview | Code tabs,  │  │
│   │  New Chat    │   │  LLM toggle            │   │  sandboxed iframe /    │  │
│   │              │   │                        │   │  Markdown renderer     │  │
│   └──────────────┘   └────────────────────────┘   └────────────────────────┘  │
│            │                     │  fetch + ReadableStream (SSE)              │
└────────────┼─────────────────────┼─────────────────────────────────────────────┘
             │                     │
             ▼                     ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│  FastAPI (Python 3.11+, Uvicorn)                                              │
│                                                                               │
│   routers/          sessions.py · chat.py (SSE) · health.py                   │
│        │                                                                      │
│        ▼                                                                      │
│   agent/  ┌────────────────┐   ┌──────────────────┐   ┌───────────────────┐   │
│           │ Intent Router  │──▶│ Retriever (RAG)  │──▶│ Skill Executor    │   │
│           │ heuristics +   │   │ hybrid search +  │   │ A: Q&A            │   │
│           │ LLM fallback   │   │ RRF fusion       │   │ B: Ship30for30    │   │
│           └────────────────┘   └──────────────────┘   │ C: Artifact       │   │
│                                                       └───────────────────┘   │
│        │                                                      │               │
│        ▼                                                      ▼               │
│   llm/  LLMProvider  ─────┬──────────────▶  AnthropicProvider  (cloud)        │
│         (single interface) └──────────────▶  OllamaProvider     (local)       │
│                                                                               │
│   utils/artifacts.py  streaming <artifact> tag state machine                   │
└───────────────────────────────────────────────────────────────────────────────┘
             │                                    │                    │
             ▼                                    ▼                    ▼
┌────────────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│ PostgreSQL 15+ + pgvector  │   │ Anthropic API      │   │ Ollama (localhost) │
│ users · sessions ·         │   │ Claude models      │   │ chat + embeddings  │
│ messages · transcript_     │   │ Voyage embeddings  │   │ fully offline      │
│ chunks (HNSW + GIN)        │   └────────────────────┘   └────────────────────┘
└────────────────────────────┘
```

Design decisions and their rationale live in [`architecture.md`](./architecture.md) (see the ADR
section at the end of that document).

---

## Repository Layout

```
.
├── README.md                       # this file
├── PRD.md                          # formalized product requirements
├── design.md                       # UI/UX design system and layout
├── architecture.md                 # DB schema, API contracts, routing logic
├── lenny_growth_assistant_spec.md  # original master specification
├── agent_transcripts/              # prompt logs, failures, corrections
│
├── backend/                        # Phase 2–3
│   ├── app/
│   │   ├── main.py                 # FastAPI app factory, CORS, lifespan
│   │   ├── config.py               # pydantic-settings configuration
│   │   ├── database.py             # async engine + session factory
│   │   ├── models.py               # SQLAlchemy ORM models
│   │   ├── schemas.py              # Pydantic request/response models
│   │   ├── routers/                # sessions, chat, health
│   │   ├── agent/                  # router, retriever, skills, orchestrator
│   │   ├── llm/                    # provider interface, Anthropic, Ollama
│   │   ├── ingestion/              # transcript fetch, chunk, embed
│   │   └── utils/                  # artifact parser, error types
│   ├── sql/init.sql                # schema DDL (pgvector, enums, indexes)
│   ├── requirements.txt
│   └── .env.example
│
└── frontend/                       # Phase 4
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── api/                    # REST client + SSE stream reader
        ├── hooks/                  # useChatStream, useSessions
        ├── components/             # Sidebar, ChatPane, ArtifactViewer, LLMToggle
        └── styles/                 # design tokens + component CSS
```

---

## Prerequisites

| Requirement | Version | Notes |
| :---------- | :------ | :---- |
| Python | 3.11 or 3.12 | 3.13+ is untested against the pinned dependency set. |
| Node.js | 20 LTS or newer | Vite 5 requires Node 18+; 20 LTS is what this is developed on. |
| PostgreSQL | 15 or newer | Must have the `vector` extension available. |
| Docker | any recent | Optional, but the fastest route to Postgres + pgvector. |
| Ollama | 0.3 or newer | Only needed for Local mode. |

An `ANTHROPIC_API_KEY` is required for Cloud mode. **It is not required to run the app** — with no
key present, the backend starts normally, reports Cloud mode as unavailable on `/api/health`, the
UI disables the Cloud side of the toggle with an explanatory tooltip, and Local mode works fully.

---

## Quickstart

### 1. Database

Fastest path — the official pgvector image, which ships the extension pre-built:

```bash
docker run -d \
  --name lenny-postgres \
  -e POSTGRES_USER=lenny \
  -e POSTGRES_PASSWORD=lenny \
  -e POSTGRES_DB=lenny \
  -p 5432:5432 \
  -v lenny_pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

Using an existing PostgreSQL instance instead? Enable the extension once per database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Backend

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env                 # then edit .env — see the table below
python -m app.cli init-db            # creates enums, tables, and vector indexes

uvicorn app.main:app --reload --port 8000
```

Verify the service and its dependencies:

```bash
curl -s http://localhost:8000/api/health | python -m json.tool
```

A healthy response tells you exactly which capabilities are live:

```json
{
  "status": "ok",
  "database": { "connected": true, "pgvector": true, "chunks_indexed": 18432 },
  "providers": {
    "cloud": { "available": true,  "model": "claude-sonnet-4-6" },
    "local": { "available": true,  "model": "llama3.1:8b-instruct-q4_K_M" }
  }
}
```

### 3. Knowledge base

```bash
# Clone the transcript corpus, chunk it, embed it, and store it in Postgres.
python -m app.cli ingest --source github --embed-space local
```

See [Transcript Ingestion](#transcript-ingestion) for options and cost/time expectations.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Vite proxies `/api` to `http://localhost:8000`, so there is no CORS configuration to do in
development. For production builds set `VITE_API_BASE_URL` to the deployed backend origin.

---

## Environment Variables

All backend configuration is read once at startup into a typed `Settings` object
(`pydantic-settings`). Invalid or contradictory configuration fails fast with a readable message
rather than surfacing later as a 500.

### Core

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `DATABASE_URL` | ✅ | — | Async DSN, e.g. `postgresql+asyncpg://lenny:lenny@localhost:5432/lenny`. |
| `APP_ENV` | — | `development` | `development` \| `production`. Controls docs exposure and log format. |
| `LOG_LEVEL` | — | `INFO` | Standard Python log level. |
| `CORS_ORIGINS` | — | `http://localhost:5173` | Comma-separated allowed origins. |
| `DEFAULT_LLM_PROVIDER` | — | `cloud` | Provider used when a request omits `llm_provider`. Falls back to `local` if Cloud is unavailable. |

### Cloud provider (Anthropic)

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `ANTHROPIC_API_KEY` | for Cloud mode | — | Absent ⇒ Cloud mode is reported unavailable; the app still runs in Local mode. |
| `ANTHROPIC_CHAT_MODEL` | — | `claude-sonnet-4-6` | Main generation model. `claude-opus-4-8` for the deepest synthesis. |
| `ANTHROPIC_ROUTER_MODEL` | — | `claude-haiku-4-5-20251001` | Small, fast model for intent classification and session titling. |
| `ANTHROPIC_MAX_TOKENS` | — `4096` | | Upper bound per response. Ship30for30 essays need ≥ 3000. |
| `CLOUD_TIMEOUT_SECONDS` | — | `120` | Per-request ceiling for the Anthropic client. |

### Local provider (Ollama)

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `OLLAMA_BASE_URL` | — | `http://localhost:11434` | Ollama HTTP endpoint. |
| `OLLAMA_CHAT_MODEL` | — | `llama3.1:8b-instruct-q4_K_M` | Must be pulled locally first. |
| `OLLAMA_EMBED_MODEL` | — | `nomic-embed-text` | 768-dimensional embeddings. |
| `OLLAMA_CONNECT_TIMEOUT` | — | `5` | Seconds to establish a connection. Short by design: a dead daemon should fail immediately. |
| `OLLAMA_FIRST_TOKEN_TIMEOUT` | — | `90` | Generous, because a cold model load can take a minute or more. |
| `OLLAMA_IDLE_TIMEOUT` | — | `120` | Max gap between tokens once streaming has begun. |

### Retrieval

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `EMBED_SPACE` | — | `local` | `local` (Ollama, 768-d) \| `voyage` (1024-d). Selects which embedding column is queried. |
| `VOYAGE_API_KEY` | if `EMBED_SPACE=voyage` | — | Voyage AI key. Anthropic has no embeddings endpoint, so Cloud-quality embeddings come from Voyage. |
| `VOYAGE_EMBED_MODEL` | — | `voyage-3` | 1024-dimensional embeddings. |
| `RETRIEVAL_TOP_K` | — | `8` | Chunks passed to the model after fusion. |
| `RETRIEVAL_CANDIDATES` | — | `40` | Candidates pulled from each retrieval arm before fusion. |
| `CHUNK_TOKENS` | — | `800` | Target chunk size at ingestion. |
| `CHUNK_OVERLAP_TOKENS` | — | `120` | Overlap between adjacent chunks. |

### Frontend

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `VITE_API_BASE_URL` | production only | `/api` (proxied) | Backend origin for deployed builds. |

---

## Running with Local Ollama

Local mode runs the **entire** pipeline offline — intent classification, embeddings, and
generation. No request leaves the machine.

### 1. Install and start Ollama

```bash
# macOS
brew install ollama
ollama serve                # or launch the menubar app, which starts the daemon for you

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Pull the models

```bash
ollama pull llama3.1:8b-instruct-q4_K_M   # generation  (~4.7 GB)
ollama pull nomic-embed-text              # embeddings  (~275 MB)
```

Have more VRAM? `qwen2.5:14b-instruct` produces noticeably better Ship30for30 prose. Point
`OLLAMA_CHAT_MODEL` at it — nothing else changes.

### 3. Confirm the daemon is reachable

```bash
curl -s http://localhost:11434/api/tags | python -m json.tool
```

### 4. Ingest with local embeddings

```bash
EMBED_SPACE=local python -m app.cli ingest --source github --embed-space local
```

### 5. Use Local mode

Set the UI toggle to **Local**, or send `"llm_provider": "local"` to `/api/chat`.

### Constraints you should know about

- **Embedding spaces are not interchangeable.** A query embedded with `nomic-embed-text` (768-d)
  cannot search vectors written by `voyage-3` (1024-d). The schema stores both in separate
  columns; ingest once per space you intend to use. Requesting a space with no vectors present
  returns a clear `RETRIEVAL_EMPTY` error rather than silently returning nothing.
- **Cold starts are slow.** The first request after Ollama loads a model can take 30–90 seconds.
  `OLLAMA_FIRST_TOKEN_TIMEOUT` accounts for this; the UI shows a "warming up the local model"
  state instead of an indeterminate spinner.
- **A cloud-hosted backend cannot reach your laptop's Ollama.** Local mode requires the backend
  process to run on the same machine or network as the daemon. If the backend is deployed and
  `OLLAMA_BASE_URL` is unreachable, `/api/health` reports Local as unavailable and the UI disables
  that half of the toggle.
- **Small models drift from format constraints.** An 8B model will not hit 1250 words as reliably
  as Claude. The Ship30for30 length guard performs at most one continuation pass, then returns the
  best result with an honest word count in the response metadata.

---

## The LLM Toggle

The toggle is a first-class request parameter, not a global server setting — two users, or two
consecutive messages in one session, can use different providers.

```
UI toggle  ──▶  POST /api/chat { "llm_provider": "cloud" | "local" }
                        │
                        ▼
                get_provider(name)  ──▶  raises ProviderUnavailable if not configured
                        │
                        ▼
        ┌───────────────┴────────────────┐
        ▼                                ▼
AnthropicProvider                  OllamaProvider
  .classify()                        .classify()
  .stream_chat()                     .stream_chat()
  .embed()                           .embed()
```

Both providers implement one interface, so the router, retriever, and skill executors are provider-agnostic. Behaviour:

- `GET /api/health` reports availability per provider; the UI reads this on load and disables
  whichever half is not usable, with the reason in a tooltip.
- Requesting an unavailable provider returns **503** with `code: "PROVIDER_UNAVAILABLE"` and a
  message naming the missing prerequisite (no API key, daemon unreachable, model not pulled).
- The provider and model actually used are echoed in the SSE `meta` event and persisted on the
  message row, so history shows how each answer was produced.

---

## Transcript Ingestion

Source corpus: `https://github.com/ChatPRD/lennys-podcast-transcripts`.

```bash
# Clone or refresh the corpus, then chunk, embed, and store.
python -m app.cli ingest --source github --embed-space local

# Re-embed already-stored text into a second space (no re-download, no re-chunk).
python -m app.cli ingest --embed-space voyage --skip-fetch

# Bound the run while developing.
python -m app.cli ingest --limit-episodes 25
```

Pipeline: fetch → parse (episode title, guest, source URL) → chunk on speaker-turn boundaries at
~800 tokens with 120-token overlap → embed in batches → upsert into `transcript_chunks` keyed by
`(episode_slug, chunk_index)`.

The run is **idempotent and resumable**. Content hashes are compared before re-embedding, so an
interrupted ingest can be re-run without duplicating rows or paying for the same embeddings twice.
Progress, token counts, and per-episode failures are logged; one malformed transcript does not
abort the run.

Rough expectations on a laptop with `nomic-embed-text`: tens of minutes for the full corpus,
dominated by embedding throughput. Voyage embeddings are much faster but metered.

---

## API Surface

Full request/response contracts, the SSE event schema, and error codes are in
[`architecture.md`](./architecture.md). Summary:

| Method | Path | Purpose |
| :----- | :--- | :------ |
| `GET` | `/api/health` | Service, database, and per-provider availability. |
| `POST` | `/api/sessions` | Create a chat session. |
| `GET` | `/api/sessions` | List sessions for the history sidebar, newest first. |
| `GET` | `/api/sessions/{session_id}/messages` | Full message history, including artifacts. |
| `PATCH` | `/api/sessions/{session_id}` | Rename a session. |
| `DELETE` | `/api/sessions/{session_id}` | Delete a session and cascade its messages. |
| `POST` | `/api/chat` | Send a message; responds with an SSE stream of tokens, artifact deltas, citations, and metadata. |

Interactive OpenAPI docs are served at `/docs` when `APP_ENV=development` and are disabled in
production.

---

## Deployment

Reference topology:

| Component | Host | Notes |
| :-------- | :--- | :---- |
| PostgreSQL + pgvector | Supabase or Railway | Both ship pgvector. Run `CREATE EXTENSION vector;` once, then `init-db`. |
| FastAPI backend | Railway, Fly.io, or Render | Container image; set env vars from the table above. |
| React frontend | Vercel or Netlify | Static build; set `VITE_API_BASE_URL` to the backend origin. |

```bash
# Backend container
docker build -t lenny-backend ./backend
docker run -p 8000:8000 --env-file backend/.env lenny-backend

# Frontend production build
cd frontend && npm run build      # emits dist/
```

Deployment notes worth stating plainly:

- Run `python -m app.cli init-db` and the ingest step once against the production database before
  first use. An empty vector store yields honest "no grounding available" answers, not crashes.
- `CORS_ORIGINS` must list the deployed frontend origin exactly, scheme included.
- SSE requires response buffering to be **off** at every proxy in front of the backend
  (`proxy_buffering off;` in nginx; Cloudflare needs streaming enabled). With buffering on, the
  stream arrives as one delayed blob and the typewriter effect disappears.
- Local mode is unavailable to a cloud-hosted backend unless Ollama is reachable from it. This is
  expected; the UI reflects it rather than failing mysteriously.

---

## Error Handling and Failure Modes

Every failure below is handled deliberately, surfaces a stable machine-readable `code`, and
renders as a readable message in the UI.

| Failure | Detection | Behaviour |
| :------ | :-------- | :-------- |
| `ANTHROPIC_API_KEY` missing | Startup config validation | App starts. Cloud reported unavailable on `/api/health`; toggle half disabled; Local mode fully usable. |
| Invalid or revoked API key | `401` from Anthropic | `503 PROVIDER_UNAVAILABLE`, key never echoed in logs or responses. |
| Anthropic rate limit | `429` | Up to 2 retries with exponential backoff and jitter, then `429 RATE_LIMITED` with `retryable: true`. |
| Ollama daemon down | Connection refused within `OLLAMA_CONNECT_TIMEOUT` | `503 OLLAMA_UNREACHABLE` with the exact start command in the message. |
| Ollama model not pulled | `404` from `/api/chat` | `503 MODEL_NOT_FOUND` naming the required `ollama pull` command. |
| Ollama cold-start exceeds timeout | No first token before `OLLAMA_FIRST_TOKEN_TIMEOUT` | `504 PROVIDER_TIMEOUT`; UI offers retry and suggests a smaller model. |
| Stream stalls mid-response | Idle gap exceeds `*_IDLE_TIMEOUT` | Partial text is preserved and persisted, `error` SSE event emitted, message marked incomplete. Never a silent truncation. |
| Database unreachable at startup | Connection probe in lifespan | Startup fails loudly with the sanitized DSN — never a half-initialized app serving 500s. |
| Database drops mid-request | `asyncpg` exception | Pool retry once; on failure `503 DATABASE_UNAVAILABLE`. Streaming responses flush what was generated before persisting. |
| `pgvector` extension absent | `init-db` probe | Actionable error with the `CREATE EXTENSION` statement, rather than a cryptic type error. |
| Vector store empty for the requested space | Count query before retrieval | `409 RETRIEVAL_EMPTY` naming the ingest command to run. |
| No chunk clears the relevance floor | Post-fusion score check | Skill A declines honestly: it states the corpus does not cover the question instead of inventing an answer. |
| Malformed or unclosed `<artifact>` tag | Streaming parser at stream end | Unterminated artifacts are closed and flushed with a warning flag; text is never lost. |
| Client disconnects mid-stream | `request.is_disconnected()` | Generation is cancelled promptly and the partial assistant message is persisted. |

---

## Troubleshooting

**`extension "vector" is not available`** — Your Postgres build lacks pgvector. Use the
`pgvector/pgvector:pg16` image, or install `postgresql-16-pgvector` on the host.

**`connection refused` on port 11434** — Ollama is not running. Start it with `ollama serve` and
confirm with `curl http://localhost:11434/api/tags`.

**Responses arrive all at once instead of streaming** — A proxy is buffering. Disable response
buffering for `/api/chat`. In development, confirm Vite's proxy has `changeOrigin: true` and no
compression middleware sits in front of the endpoint.

**Answers say the corpus does not cover the question, for everything** — Ingestion has not run for
the active `EMBED_SPACE`. Check `chunks_indexed` on `/api/health`, then run the ingest command with
the matching `--embed-space`.

**Ship30for30 essays come out short in Local mode** — Expected with an 8B model. Raise
`OLLAMA_CHAT_MODEL` to a 14B-class model, or use Cloud mode for length-critical work. The returned
metadata always reports the real word count.

**Artifact pane stays empty** — The model produced prose without artifact tags. Ask explicitly for
HTML, CSS, or a Markdown document; Skill C only triggers on artifact-shaped intent.

---

## Deliverables Checklist

Tracks §7 of the master specification.

- [x] `README.md` — architecture overview, deployment steps, env vars, dependency installation
- [x] `design.md` — UI/UX design structure and rationale
- [x] `PRD.md` — formalized product requirements
- [x] `architecture.md` — DB schema, API endpoints, agent routing logic
- [x] `agent_transcripts/` — prompt logs including failures and corrections
- [ ] Full working codebase (FastAPI + React) — Phases 2–4
- [ ] 2–3 minute YouTube demo video — manual step after Phase 4

---

## License and Attribution

Transcript content originates from `ChatPRD/lennys-podcast-transcripts` and remains the property of
its respective owners. This application is a retrieval and synthesis interface over that corpus,
built as a technical assessment submission.
