# The Lenny Growth Assistant

> A conversational AI workspace that answers product-management and growth questions **strictly from
> the transcripts of Lenny's Podcast**, writes Ship30for30-style essays, and renders generated
> HTML/CSS and Markdown **live, side-by-side with the chat** — never in an external tab.
>
> The entire pipeline — classification, embeddings, and generation — switches between **Cloud**
> (Anthropic Claude) and **Local** (Ollama) with a single toggle.

---

## Table of Contents

1. [Project Overview & Objective](#1-project-overview--objective)
2. [The Tech Stack & "The Why"](#2-the-tech-stack--the-why)
3. [Architecture & Working Process (Data Flow)](#3-architecture--working-process-data-flow)
4. [Agentic Skills & Routing](#4-agentic-skills--routing)
5. [Manual Setup & Execution Guide](#5-manual-setup--execution-guide)
6. [Environment Variables Reference](#6-environment-variables-reference)
7. [API Surface](#7-api-surface)
8. [Repository Layout](#8-repository-layout)
9. [Error Handling & Troubleshooting](#9-error-handling--troubleshooting)
10. [Deployment](#10-deployment)
11. [Verified Configuration & Deliverables](#11-verified-configuration--deliverables)
12. [Future Enhancements](#12-future-enhancements)

---

## 1. Project Overview & Objective

### The problem

Lenny's Podcast is one of the richest sources of product and growth thinking available — hundreds of
hours of interviews with people who built Airbnb, Stripe, Figma, Notion, and Reddit. But it is
*audio*. You cannot ask it a question. You cannot ask *"what did guests actually say about deciding
what **not** to build?"* and get an answer with sources.

### What this application does

It turns that corpus into something you can interrogate, and then act on.

| Capability | What it means in practice |
| :--------- | :------------------------ |
| **Grounded Q&A** | Ask a product or growth question. The system searches **303 episodes / 12,113 indexed excerpts**, answers *only* from them, cites the episode and guest, and — critically — **says so plainly when the corpus does not cover your question** rather than inventing an answer. |
| **Ship30for30 essays** | Ask for an essay and it produces roughly **1,250 words** in the Ship30for30 style: a sharp hook, short paragraphs, bullet clusters, bolded phrases for skimmability, and one clear takeaway. The word count is measured after generation and reported honestly. |
| **Artifacts** | Ask it to build something and it emits a complete, self-contained HTML page or Markdown document, which renders **live in a pane beside the chat** as it is written. |
| **Cloud / Local toggle** | Flip between Anthropic Claude and a local Ollama model. Local mode runs **entirely offline** — no request leaves your machine. |

### The design principle behind all of it

**Honesty over the appearance of competence.** A system that confidently fabricates is worse than
one that admits a gap. That idea recurs throughout this codebase: the retrieval layer has a
relevance floor, the Q&A prompt is instructed to decline rather than guess, the essay generator
reports its *real* word count even when it misses the target, and the UI disables an unavailable
provider and states exactly why instead of hiding it.

---

## 2. The Tech Stack & "The Why"

If you are new to full-stack development, this is the important section. Each choice below solves a
specific problem — knowing *why* matters more than knowing *what*.

### Frontend — React 18 + Vite

**What it is:** React is a JavaScript library for building interfaces out of reusable pieces called
*components*. Vite serves your code during development and bundles it for production.

**Why we chose it:**

- **The UI changes constantly.** When an AI response streams in, text arrives dozens of times per
  second. React's model — *describe what the screen should look like for a given state, and let
  React compute the minimal DOM changes* — is exactly right for this. Hand-writing that with plain
  DOM manipulation would be painful and slow.
- **The Artifact Viewer needs component isolation.** Rendering AI-generated HTML safely means
  putting it in a *sandboxed iframe* and re-mounting it cleanly when content changes. React's `key`
  prop makes "throw this away and build a fresh one" a one-line operation.
- **Vite is fast.** It starts in under a second and updates the browser the instant you save,
  which matters enormously when iterating on a design.

> **Beginner note — why not plain HTML and JavaScript?** You could build this without React. But you
> would end up writing your own system for *"when this data changes, update these five places on
> screen"* — and that system **is** React. Use the one debugged by millions of people.

### Backend — Python 3.12 + FastAPI

**What it is:** FastAPI is a modern Python framework for building APIs — the layer that receives
requests from the browser and responds with data.

**Why we chose it:**

- **Python is where the AI ecosystem lives.** The official Anthropic SDK, database drivers, and
  every text-processing library you would want are Python-first. Another language means fighting
  the ecosystem.
- **FastAPI is asynchronous — this is the crucial one.** When the app waits on Claude to generate a
  response (which can take 60 seconds), a traditional synchronous server would block an entire
  worker doing nothing. FastAPI uses `async`/`await`, so one process holds hundreds of waiting
  connections while doing useful work. For an app whose main job is *waiting on slow AI calls*,
  this is not a nice-to-have.
- **Streaming is first-class.** `StreamingResponse` pushes tokens to the browser as they are
  generated, producing the typewriter effect instead of a 60-second blank screen.
- **Validation is automatic.** Declare the shape of your data once as a Python class; FastAPI
  validates every incoming request against it and rejects malformed ones with a clear error —
  before your code runs.

### Database — PostgreSQL 16 + pgvector

**What it is:** PostgreSQL is a relational database — data in tables with enforced relationships.
`pgvector` is an extension that teaches it to store and search *embeddings*.

**Why we chose it:**

- **Conversations are genuinely relational.** A user has many sessions; a session has many
  messages. That is a textbook relational shape, and the database can *enforce* it: delete a
  session and its messages go automatically (`ON DELETE CASCADE`), so orphaned rows are impossible
  rather than merely unlikely.
- **One database instead of two.** Many RAG applications run Postgres *and* a separate vector
  database (Pinecone, Weaviate, Chroma). With `pgvector` the transcript embeddings live alongside
  the conversations: one connection, one backup, one transaction boundary, one thing to install.
- **Real constraints catch real bugs.** A `CHECK` constraint makes "this message is typed as HTML
  but has no content" *impossible to store*. That is a guarantee, not a convention the frontend has
  to remember in three places.

> **Beginner note — what is an embedding?** An embedding turns text into a list of numbers (here,
> 768 of them) capturing its *meaning*. Two passages about customer retention end up with similar
> number-lists even if they share no words. Searching for meaning becomes searching for nearby
> points — which is what `pgvector` does, fast.

### AI / Agent layer — Anthropic Claude + Ollama

We deliberately use the **raw Anthropic SDK** rather than a framework like LangChain. The pipeline
is four steps (classify → retrieve → prompt → stream), and every provider-specific detail that
actually caused difficulty during development — streaming event shapes, context-window limits, JSON
schema quirks — is one a framework would have hidden rather than solved.

| | **Cloud (Anthropic Claude)** | **Local (Ollama)** |
| :-- | :-- | :-- |
| Where it runs | Anthropic's servers | Your machine |
| Needs internet | Yes | No |
| Cost | Per token | Free |
| Speed | Fast (~2s to first token) | Slower; a cold model takes 30–90s to load |
| Quality | Higher | Lower, especially on long-form structure |
| Privacy | Data leaves your machine | Nothing leaves your machine |
| Used for | `claude-sonnet-4-6` generation, `claude-haiku-4-5` routing | Chat generation **and** embeddings |

**Why support both?** They solve different problems. Cloud gives the best answers. Local gives
privacy, zero cost, and offline operation — someone working on confidential product strategy may
*need* it. The toggle is per-request, so you can even mix providers within one conversation, and
each message records which one produced it.

> **An important asymmetry.** Anthropic does not offer an embeddings endpoint. So even in Cloud
> mode, embeddings come from elsewhere — Ollama's `nomic-embed-text` locally, or Voyage AI. This is
> why `EMBED_SPACE` is configured *separately* from the chat provider, and why **Cloud generation
> over locally-computed embeddings** is the recommended default: best answers, zero embedding cost.

---

## 3. Architecture & Working Process (Data Flow)

### The big picture

Three processes and one database. **The browser never talks to an AI provider directly** — every
model call goes through FastAPI. API keys stay server-side, and the provider toggle is enforced in
exactly one place.

```
┌──────────────────────────────────────────────────────────────────────┐
│  BROWSER — React + Vite                                              │
│                                                                      │
│   Sidebar          Chat Pane              Artifact Viewer            │
│   sessions,        messages, composer,    Preview | Code tabs,       │
│   New Chat         LLM toggle             sandboxed iframe           │
│                          │                                           │
│                          │ fetch + ReadableStream (SSE)              │
└──────────────────────────┼───────────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FASTAPI BACKEND                                                     │
│                                                                      │
│   routers/     health.py · sessions.py · chat.py (streaming)         │
│        ▼                                                             │
│   agent/       Intent Router → Retriever → Skill → Artifact Parser   │
│        ▼                                                             │
│   llm/         AnthropicProvider  |  OllamaProvider                  │
└────────┬──────────────────────┬─────────────────────┬────────────────┘
         ▼                      ▼                     ▼
┌────────────────────┐  ┌────────────────┐  ┌────────────────────┐
│ PostgreSQL         │  │ Anthropic API  │  │ Ollama (localhost) │
│ + pgvector         │  │ (cloud)        │  │ (local, offline)   │
│ 12,113 excerpts    │  └────────────────┘  └────────────────────┘
└────────────────────┘
```

### The lifecycle of one message, step by step

Follow a single question — *"How do great PMs decide what not to build?"* — end to end.

**Step 1 — The browser sends the message.**
React `POST`s to `/api/chat` with the session ID, your text, and the selected provider. It uses
`fetch` with a readable stream rather than the browser's built-in `EventSource`, because
`EventSource` can only make GET requests and cannot send the identifying header this app uses.

**Step 2 — The backend validates *before* opening the stream.**
Is the message between 1 and 8,000 characters? Does this session exist, and does it belong to you?
Is the requested provider actually available? These return ordinary JSON errors. The ordering
matters: once a stream is open everything must be a stream event, and a client cannot easily tell
"your request was malformed" from "the answer went wrong".

**Step 3 — The user's message is saved immediately.**
Before any AI call. If the server crashes mid-generation, your question is not lost.

**Step 4 — The Intent Router picks a Skill.** *(see [Section 4](#4-agentic-skills--routing))*
This is the agentic decision — which tool to use. It runs in tiers, cheapest first, so obvious cases
cost nothing.

**Step 5 — Retrieval finds the relevant excerpts.**
Two searches run over the 12,113 excerpts and are **fused**:

- **Semantic search** — the question becomes 768 numbers, and `pgvector` finds passages whose
  embeddings are closest. This catches *meaning*: "keeping users around" matches "churn reduction"
  despite sharing no words.
- **Keyword search** — Postgres full-text search. This catches *exact terms* semantic search is
  fuzzy about: an acronym like "PLG", or a guest's name.

They are combined with **Reciprocal Rank Fusion**, which merges two ranked lists using only
positions — so two incompatible scoring scales need no tuning to be comparable. Then two filters:

- **Diversity cap** — at most 3 excerpts per episode, so one well-matched ten-minute stretch cannot
  fill every slot and make one guest's opinion look like consensus.
- **Relevance floor** — excerpts that simply are not close enough are dropped, which is what makes
  the honest "I don't have this" answer reachable at all.

**Step 6 — The prompt is built.**
Retrieved excerpts are wrapped in `<transcripts>` tags, and every system prompt states that content
inside those tags is **data, never instructions**. Transcripts are third-party text; sooner or later
one will contain something shaped like a command, and this is the defence.

**Step 7 — Generation streams back.**
The provider streams text. Each fragment passes through an **artifact parser** — a small state
machine watching for `<artifact>` tags. This is subtler than it sounds: a model emits `<arti`, then
`fact type="ht`, then `ml">`. No single fragment contains the whole tag, so naive matching fails and
tag fragments leak into the chat as visible garbage. The parser holds back any trailing text that
could still become a tag until it knows.

Prose becomes `token` events; artifact source becomes `artifact_delta` events — **two separate
channels**, so the chat pane never shows raw HTML and the viewer never shows prose.

**Step 8 — The browser renders as it arrives.**
Incoming tokens are buffered and flushed once per animation frame. Without this, a fast stream
triggers dozens of React re-renders per second and the typewriter effect visibly stutters.

**Step 9 — Finishing up.**
The complete reply is saved with everything needed to replay it: which skill ran, which provider and
model, the citations, the word count, and *why* it stopped. Press **Stop** mid-stream and the
partial text is still saved, marked as stopped.

---

## 4. Agentic Skills & Routing

An "agent" here means the system chooses **which tool to use** rather than doing one fixed thing.

### The skills

| Skill | Triggered by | Retrieval | Output |
| :---- | :----------- | :-------- | :----- |
| **A — Grounded Q&A** | A question about product or growth | Top 8 excerpts | Prose with `[1] [2]` citations. **Declines if the corpus doesn't cover it.** |
| **B — Ship30for30** | A request for an essay or long-form post | Top 10 excerpts | ~1,250-word essay: hook, short paragraphs, bullets, bold, one takeaway |
| **C — Artifact** | A request to *build* something | Top 4, only if the request is topical | Complete HTML page or Markdown document, rendered live |
| **D — Meta** *(beyond spec)* | "Who are you?", "What can you do?" | None | Short capability description |

> **Why Skill D exists.** With only three skills, "hi" and "what can you do?" had nowhere to go.
> Routed to Skill A they produced a technically correct but absurd reply: *that the transcripts do
> not discuss the assistant's own capabilities*. A fourth skill costing a few hundred tokens fixes
> it. It is flagged as an addition beyond the specification wherever it appears.

### How the router decides — three tiers, cheapest first

```
User message
     │
     ▼
TIER 0 — Guardrails and override                          ~0 ms, no AI call
     │  Empty or over-length? Reject.
     │  Did the user explicitly pick a skill? Use it — an explicit choice is
     │  never second-guessed. (This is what the starter cards on the home
     │  screen do.)
     ▼
TIER 1 — Deterministic keyword patterns                   ~0 ms, no AI call
     │  "1250 word", "write an essay"      → Ship30for30
     │  "html", "dashboard", "mockup"      → Artifact
     │  "who are you", "hello"             → Meta
     │
     │  Precision-first: a pattern fires ONLY when unambiguous. If a message
     │  matches both essay AND html patterns, this tier deliberately abstains
     │  rather than guess — a wrong guess skips the tier that would be right.
     ▼
TIER 2 — Small-model classifier                    ~800 ms, one cheap AI call
        Runs on the fast, cheap model. Returns structured JSON.
```

### Why an AI tier is worth its latency

Tier 2 does **two** jobs, and the second is what makes conversations work:

1. **Classification** into one of the four skills, with a confidence score.
2. **Query rewriting** — it rewrites your message into a standalone search query.

Consider the follow-up *"make it longer"*. Searched literally, that retrieves nothing useful — the
words carry no topic. Rewritten against the conversation it becomes *"why retention beats
acquisition for early-stage growth"*, and retrieval works. **This single field is the difference
between follow-up questions working and failing.**

There is also **skill inheritance**: short modifiers like "make it longer" or "try again" keep the
*previous* skill. Without it, "make it longer" after an essay gets re-classified as a question and
returns a 200-word answer.

### When things go wrong, it degrades rather than fails

| Failure | Behaviour |
| :------ | :-------- |
| Classifier errors or times out | Default to Q&A with the raw message. Q&A is the most constrained skill, so a misroute into it is the safest one. |
| Confidence below 0.6 | Same — default to Q&A. |
| Embeddings unavailable mid-request | Fall back to keyword search alone and flag the answer as degraded. Weaker grounding beats no answer, but the user is told which they got. |
| Nothing clears the relevance floor | Return an honest "not covered in this corpus" with suggested rephrasings. **This is a success path, not an error.** |
| Essay comes in short | One continuation pass, then accept and report the true count. Never claim compliance it does not have. |

---

## 5. Manual Setup & Execution Guide

> **Time required:** about 20 minutes, plus a one-time transcript ingest. Use `--limit-episodes 25`
> to cut the ingest to roughly 5 minutes while evaluating.

### 5.1 Prerequisites

| Requirement | Version | Check with | Install |
| :---------- | :------ | :--------- | :------ |
| **Python** | 3.12 recommended (3.11 works) | `python3.12 --version` | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| **Node.js** | 20 LTS or newer | `node --version` | [nodejs.org](https://nodejs.org/) or `brew install node` |
| **Docker** | any recent | `docker --version` | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |
| **Ollama** | 0.3 or newer | `ollama --version` | [ollama.com](https://ollama.com/download) or `brew install ollama` |
| **Git** | any | `git --version` | Pre-installed on macOS and Linux |

> **Do you need an Anthropic API key?** **No.** The application runs fully without one — Cloud mode
> reports itself unavailable, the UI disables that half of the toggle with an explanation, and
> **Local mode works completely**. A key only unlocks the higher-quality Cloud path.

---

### 5.2 Get the code

```bash
git clone <repository-url>
cd Project
```

---

### 5.3 Database setup (PostgreSQL + pgvector)

The fastest path is the official `pgvector` image, which ships the extension pre-built:

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

Wait a few seconds, then enable the extension:

```bash
docker exec -it lenny-postgres psql -U lenny -d lenny -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**Verify** — this single command proves the database half is ready:

```bash
docker exec -it lenny-postgres psql -U lenny -d lenny -c \
  "SELECT current_setting('server_version') AS pg, extversion AS pgvector FROM pg_extension WHERE extname='vector';"
```

Expect `16.x` and `0.8.x`.

> **After a reboot** Docker does not restart it automatically: `docker start lenny-postgres`.
>
> **Prefer Supabase or Railway?** Both work — they ship `pgvector`. Create a project, run
> `CREATE EXTENSION vector;` once, and point `DATABASE_URL` at it. Local Docker is the default here
> because evaluation is meant to happen locally: a container needs no account, no shared
> credentials, and no network round-trip on every one of the 12,113 vector lookups.

---

### 5.4 Ollama setup (local model)

Start the daemon — leave this running in its own terminal:

```bash
ollama serve
```

In a second terminal, pull the models:

```bash
# Embeddings — REQUIRED. Nothing can be ingested or searched without this.
ollama pull nomic-embed-text                   # ~275 MB

# Local chat generation — pick ONE:
ollama pull llama3.2:1b                        # ~1.3 GB — runs on 8 GB RAM. START HERE.
ollama pull llama3.1:8b-instruct-q4_K_M        # ~4.9 GB — better prose, needs 16 GB RAM
```

Confirm the daemon is reachable:

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool
```

> **Which chat model should an evaluator pull?** Start with **`llama3.2:1b`** — it is quick to
> download, adequate for Q&A, and is what the recorded test runs used. Only reach for
> `llama3.1:8b-instruct-q4_K_M` if you have **16 GB of RAM or more**; at 4-bit quantisation it needs
> around 5 GB resident and will time out while loading on an 8 GB machine. Whichever you choose, set
> `OLLAMA_CHAT_MODEL` to match in the next step — a mismatch is the single most common local-mode
> failure.

---

### 5.5 Backend setup

```bash
cd backend

# 1. Create an isolated Python environment
python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create your configuration
cp .env.example .env
```

Now **edit `backend/.env`**. Defaults work as-is for local-only operation. Two lines are worth
checking:

```bash
# Leave BLANK to run Local-only. Paste a key to enable Cloud mode.
ANTHROPIC_API_KEY=

# MUST match a model you actually pulled in step 5.4.
# llama3.2:1b runs on ~8 GB RAM. Use the 8B model only if you have 16 GB or more.
OLLAMA_CHAT_MODEL=llama3.2:1b
```

Create the tables, indexes, and triggers:

```bash
python -m app.cli init-db
```

Expect `5 tables, 13 indexes, pgvector 0.8.6`. Safe to re-run.

Check everything is wired up before going further:

```bash
python -m app.cli healthcheck
```

---

### 5.6 Ingest the transcripts

This clones the corpus, splits it into overlapping passages, embeds each one, and stores them.

```bash
# FASTER FOR EVALUATION — 25 episodes, about 5 minutes. Fully functional,
# just a smaller knowledge base. Recommended for a first run.
python -m app.cli ingest --source github --limit-episodes 25

# Full corpus — 303 episodes, ~12,100 passages, roughly an hour on a laptop.
python -m app.cli ingest --source github
```

The ingest is **idempotent and resumable**: unchanged passages are never re-embedded, so
interrupting with `Ctrl+C` and re-running costs nothing. Progress is committed per episode.

---

### 5.7 Start the backend

```bash
# from backend/, with the venv active
uvicorn app.main:app --reload --port 8000
```

Verify in another terminal:

```bash
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

A healthy response tells you exactly which capabilities are live:

```json
{
  "status": "ok",
  "database": { "connected": true, "pgvector": true,
                "chunks": { "total": 12113, "local": 12113, "voyage": 0 } },
  "providers": {
    "cloud": { "available": true, "model": "claude-sonnet-4-6", "reason": null },
    "local": { "available": true, "model": "llama3.2:1b", "reason": null }
  },
  "embed_space": "local"
}
```

> `"status": "degraded"` means the database is fine but at least one provider is unavailable — the
> app still works. Each provider's `reason` field states precisely what to fix.

---

### 5.8 Start the frontend

In a **new terminal**:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

> Vite proxies `/api` to `http://localhost:8000`, so there is no CORS configuration to do in
> development.

---

### 5.9 Try it — four things worth testing

| # | Do this | What proves it works |
| :- | :------ | :------------------- |
| 1 | Click **"Ask a question about retention loops"** | Streams an answer with a **Sources** block naming real episodes and guests |
| 2 | Click **"Build a metrics dashboard mockup"** | Artifact pane slides in, source streams into the **Code** tab, then **Preview** mounts a live rendering |
| 3 | Click **"Write a Ship30for30 essay on PMF"** | ~1,250-word essay with the word count beside the badge (1–2 minutes on Cloud) |
| 4 | Switch the toggle to **Local**, then ask a question | Same pipeline, entirely on your machine — the provider stamp under the reply confirms it |

---

## 6. Environment Variables Reference

All backend configuration lives in `backend/.env`. It is validated once at startup — bad or
contradictory configuration fails immediately with a readable message rather than surfacing later as
a mysterious 500.

### Core

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `DATABASE_URL` | **Yes** | — | `postgresql+asyncpg://lenny:lenny@localhost:5432/lenny` |
| `APP_ENV` | No | `development` | `development` \| `production` |
| `LOG_LEVEL` | No | `INFO` | Standard Python log level |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Comma-separated allowed origins |
| `DEFAULT_LLM_PROVIDER` | No | `cloud` | Used when a request does not specify one |

### Cloud provider (Anthropic)

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `ANTHROPIC_API_KEY` | For Cloud | — | Absent ⇒ Cloud unavailable; app still runs |
| `ANTHROPIC_CHAT_MODEL` | No | `claude-sonnet-4-6` | Main generation model |
| `ANTHROPIC_ROUTER_MODEL` | No | `claude-haiku-4-5-20251001` | Small, fast model for classification |
| `ANTHROPIC_MAX_TOKENS` | No | `4096` | Upper bound per response |
| `CLOUD_TIMEOUT_SECONDS` | No | `120` | Per-request ceiling |

### Local provider (Ollama)

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_CHAT_MODEL` | No | `llama3.2:1b` | **Must be pulled first.** The 8B alternative needs ~5 GB RAM resident — see [Verified Configuration](#11-verified-configuration--deliverables) |
| `OLLAMA_EMBED_MODEL` | No | `nomic-embed-text` | 768-dimensional embeddings |
| `OLLAMA_NUM_CTX` | No | `16384` | Context window. Ollama defaults to 4096 and **silently truncates** longer prompts, which would cut retrieved transcripts out of the prompt entirely |
| `OLLAMA_CONNECT_TIMEOUT` | No | `5` | Short by design — a dead daemon should fail fast |
| `OLLAMA_FIRST_TOKEN_TIMEOUT` | No | `90` | Generous — a cold model load can take a minute |
| `OLLAMA_IDLE_TIMEOUT` | No | `120` | Max gap between tokens once streaming |

### Retrieval

| Variable | Required | Default | Description |
| :------- | :------- | :------ | :---------- |
| `EMBED_SPACE` | No | `local` | `local` (Ollama, 768-d) \| `voyage` (1024-d) |
| `VOYAGE_API_KEY` | If `voyage` | — | Anthropic has no embeddings endpoint |
| `VOYAGE_EMBED_MODEL` | No | `voyage-3` | 1024-dimensional |
| `RETRIEVAL_TOP_K` | No | `8` | Excerpts passed to the model after fusion |
| `RETRIEVAL_CANDIDATES` | No | `40` | Candidates pulled per search arm before fusion |
| `CHUNK_TOKENS` | No | `800` | Target passage size at ingestion |
| `CHUNK_OVERLAP_TOKENS` | No | `120` | Overlap between adjacent passages |

> **Never commit `.env`.** It is git-ignored. `.env.example` ships with blank keys and is the file
> that belongs in version control.

---

## 7. API Surface

Base path `/api`. JSON in, JSON out — except `/api/chat`, which streams Server-Sent Events.

| Method | Endpoint | Purpose |
| :----- | :------- | :------ |
| `GET` | `/api/health` | What works right now: database, corpus size, per-provider availability |
| `POST` | `/api/sessions` | Start a new chat session |
| `GET` | `/api/sessions` | List sessions, newest first (paginated) |
| `GET` | `/api/sessions/{id}/messages` | Full history, artifacts included inline |
| `PATCH` | `/api/sessions/{id}` | Rename a session |
| `DELETE` | `/api/sessions/{id}` | Delete a session and its messages |
| `POST` | `/api/chat` | Send a message; streams the reply |

Interactive documentation is at **http://localhost:8000/docs** while the server runs in development
mode.

### Streaming events

`/api/chat` emits named events in a guaranteed order — `meta` always first, `done` always last, and
exactly one of `done` or `error` ends every stream:

| Event | Meaning |
| :---- | :------ |
| `meta` | Which skill was chosen, which provider and model. Arrives *before* any text. |
| `token` | A fragment of prose |
| `artifact_start` / `artifact_delta` / `artifact_end` | Artifact lifecycle |
| `citations` | The sources actually used |
| `usage` | Token counts, latency, word count |
| `done` / `error` | Terminal |

---

## 8. Repository Layout

```
.
├── README.md                       # this file
├── PRD.md                          # product requirements
├── design.md                       # UI/UX design system
├── architecture.md                 # DB schema, API contracts, routing logic, ADRs
├── lenny_growth_assistant_spec.md  # original brief
├── agent_transcripts/              # development logs, including failures
│
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI factory, CORS, lifespan, error handlers
│   │   ├── config.py               # settings, validated at startup
│   │   ├── database.py             # async engine, session factory, health probe
│   │   ├── models.py               # SQLAlchemy ORM models
│   │   ├── schemas.py              # request/response validation
│   │   ├── cli.py                  # init-db, ingest, healthcheck
│   │   ├── routers/                # health, sessions, chat
│   │   ├── agent/                  # router, retriever, prompts, orchestrator
│   │   ├── llm/                    # provider interface, Anthropic, Ollama, embeddings
│   │   ├── ingestion/              # fetch, parse, chunk, pipeline
│   │   └── utils/                  # artifact parser, errors, SSE, logging
│   ├── scripts/                    # measurement and verification scripts
│   ├── tests/                      # 147 automated tests
│   ├── sql/init.sql                # schema DDL — single source of truth
│   └── requirements.txt
│
└── frontend/
    ├── src/
    │   ├── api/                    # REST client, SSE reader
    │   ├── hooks/                  # useChatStream, useSessions, useHealth
    │   ├── components/             # Sidebar, ChatPane, ArtifactViewer, ...
    │   └── styles/                 # design tokens, component CSS
    └── package.json
```

---

## 9. Error Handling & Troubleshooting

### Designed failure behaviour

| Situation | What happens |
| :-------- | :----------- |
| No `ANTHROPIC_API_KEY` | App starts. Cloud reported unavailable with the reason. Local works fully. |
| Ollama not running | Local disabled in the UI with "Ollama not reachable at localhost:11434". Cloud works fully. |
| Local model not pulled | Detected at health-check time, before you send a message. |
| Neither provider available | History stays browsable; the composer is disabled with an explanation. |
| Database unreachable | The app **refuses to start**, logging the connection string with the password redacted. A half-working app returning 500s is worse than one that will not start. |
| Vector store empty | The home screen says ingestion has not run and gives the exact command. |
| You press Stop | Partial reply is saved and marked `Stopped`. |

### Common problems

| Symptom | Cause and fix |
| :------ | :------------ |
| `connection refused` on port 5432 | Postgres is not running → `docker start lenny-postgres` |
| `extension "vector" is not available` | Wrong image. Use `pgvector/pgvector:pg16`, not plain `postgres` |
| `RETRIEVAL_EMPTY` when asking a question | Ingestion has not run → `python -m app.cli ingest --source github` |
| Local answers ignore the transcripts | `OLLAMA_NUM_CTX` too low for your model; the prompt is being truncated |
| `model 'x' not found` | `OLLAMA_CHAT_MODEL` does not match anything in `ollama list` |
| First local reply takes ~60s | Normal — Ollama is loading weights from disk. Later replies are fast. |
| Local request times out before any token | The model does not fit in RAM. An 8B model at q4 needs ~5 GB resident; switch `OLLAMA_CHAT_MODEL` to `llama3.2:1b`. |
| Frontend shows "Cannot reach the server" | The backend is not running on port 8000 |
| `ModuleNotFoundError` on startup | The virtual environment is not active → `source .venv/bin/activate` |

---

## 10. Deployment

Development runs three processes. Production collapses to two plus a managed database.

| Component | Suggested host | Notes |
| :-------- | :------------- | :---- |
| Frontend | Vercel, Netlify, any static host | `npm run build` → `dist/`. Set `VITE_API_BASE_URL` to the backend origin. |
| Backend | Railway, Fly.io, Render, any container host | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Database | Supabase, Railway, Neon | All ship `pgvector`. Run `CREATE EXTENSION vector;` once, then `init-db`. |
| Ollama | — | **Cannot be reached from a cloud backend.** Local mode requires the backend to run on the same machine or network as the daemon. Deployed instances report Local as unavailable and the UI disables that half of the toggle. |

**One deployment-specific gotcha.** SSE must not be buffered by a reverse proxy, or the stream
arrives as one lump at the end and every token event is pointless. The backend sets
`X-Accel-Buffering: no` for nginx; other proxies may need their own equivalent.

---

## 11. Verified Configuration & Deliverables

So an evaluator knows exactly what was exercised rather than inferring it:

| | Verified on |
| :-- | :-- |
| Python | 3.12.0 |
| PostgreSQL | 16.14 (`pgvector/pgvector:pg16` in Docker) + pgvector 0.8.6 |
| Node | 22.17 |
| Corpus | 303 episodes → 12,113 passages, fully embedded |
| Cloud | `claude-sonnet-4-6` (generation), `claude-haiku-4-5` (routing) |
| Local embeddings | `nomic-embed-text` (768-d) |
| Local generation | **`llama3.2:1b`** — see the caveat below |
| Automated tests | 147 passing |
| Development machine RAM | 8 GB |

**An honest caveat on the local model.** `llama3.1:8b-instruct-q4_K_M` was pulled and tested, and
it **did not run on the development machine**: an 8B model at 4-bit quantisation needs roughly 5 GB
resident, plus the 16K context window, and the machine has 8 GB of RAM total. The request timed out
before the first token while the model was still loading. Every end-to-end run recorded in
`agent_transcripts/` therefore used **`llama3.2:1b`**, which runs comfortably in the same footprint.

This is why `.env.example` defaults to `llama3.2:1b` rather than the larger model. If your machine
has **16 GB of RAM or more**, `llama3.1:8b-instruct-q4_K_M` will produce noticeably better
Ship30for30 prose and is worth switching to — the provider code is model-agnostic and nothing else
changes. The relevant guidance from the brief is *"any model that runs comfortably on your laptop"*,
and on this hardware that is the 1B.

### Project documentation

| File | Contents |
| :--- | :------- |
| `PRD.md` | Product requirements: personas, user stories, 50 numbered functional requirements |
| `architecture.md` | Full database DDL, API contracts, routing logic, artifact protocol, 10 ADRs |
| `design.md` | Design tokens, component specs, accessibility, design QA checklist |
| `agent_transcripts/` | Development logs — including **the failures and how they were corrected** |

The transcripts are deliberately not a highlight reel. They record roughly thirty corrections made
during development, including several where the specification itself turned out to be wrong when
measured — a relevance threshold that never rejected anything, an output budget too small for its
own deliverable, and four colour tokens that failed the accessibility standard the design document
claimed to meet.

---

## 12. Future Enhancements

Concrete next steps, roughly ordered by ratio of learning to effort.

### Good first projects

- **Export a conversation** to Markdown or PDF. Teaches data transformation and file downloads end
  to end, and touches every layer without needing to understand the AI pipeline.
- **Search your own conversations.** The database already has full-text search infrastructure for
  transcripts; pointing it at the `messages` table is a satisfying reuse of something already built.
- **Show retrieval scores in the UI.** The API already returns a relevance score per citation. Put
  it on screen. Suddenly *why* the AI said something becomes visible — one of the most useful things
  you can build into an AI product.

### Intermediate

- **Multi-turn artifact editing.** Each artifact is currently generated fresh. Letting a user say
  "make the header blue" and patching the existing artifact means passing the previous artifact back
  into context and diffing the result.
- **Real authentication.** The app uses anonymous browser-generated keys. Adding proper accounts is
  well-scoped, and the schema was deliberately built so an auth user ID can replace the anonymous
  key without a migration.
- **Rate limiting.** Currently unimplemented. A token bucket per user on the chat endpoint is the
  classic introduction to protecting an expensive endpoint.
- **A frontend test suite.** The backend has 147 tests; the frontend has none. Contrast checks and
  design-token discipline are mechanically verifiable and would be a strong first contribution.

### Ambitious

- **Reranking.** After hybrid search returns 40 candidates, a cross-encoder could re-score them for
  genuine relevance rather than similarity. One of the highest-leverage improvements available to
  any RAG system.
- **Multi-corpus support.** Nothing in the retrieval layer is specific to Lenny's Podcast. Adding a
  `corpus` column and a selector would let the same engine answer over any transcript collection.
- **Evaluation harness.** Build a labelled set of questions with known-good answers and measure
  retrieval precision and answer faithfulness on every change. This is the difference between "it
  seems better" and "it *is* better" — and what separates a demo from a product.
- **Voice input and output.** Transcribe spoken questions and read answers back. The podcast source
  material makes this a natural fit.

---

## License & Attribution

Transcript content belongs to its original creators. The corpus is sourced from
[`ChatPRD/lennys-podcast-transcripts`](https://github.com/ChatPRD/lennys-podcast-transcripts) and is
cloned at ingestion time — it is never redistributed in this repository.
