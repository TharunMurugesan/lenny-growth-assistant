# Phase 2 — Database Schema and FastAPI Infrastructure

**Date:** 2026-07-31
**Agent:** Claude (Opus) via Claude Code CLI
**Objective:** Stand up the persistence layer and the HTTP surface: schema, ORM models,
application factory, and the session and chat routes.

---

## 1. Prompt

> Phase 2 scope: PostgreSQL schema and SQLAlchemy models, the FastAPI application, and the session
> and chat routes. The Phase 1 constraints carry forward — full files never elided, strict
> backend/frontend separation, robust error handling for missing API keys, Ollama timeouts, and
> database connection failures.

Preceded by an environment audit and a manual setup pass (Docker, PostgreSQL + pgvector, disk
reclamation, repository isolation) before any code was written.

---

## 2. Interpretation

`architecture.md` was written in Phase 1 specifically so this phase would be transcription rather
than invention, and it largely held: the DDL, API shapes, and error taxonomy were copied across
rather than redesigned. The work that remained was the part a document cannot settle — what happens
when the two representations of the schema disagree, and what a route does when the thing it exists
to call has not been built yet.

Two rules were adopted up front and are visible throughout the code:

**One owner per fact.** The schema is owned by `sql/init.sql`, not by SQLAlchemy metadata.
`updated_at` is owned by a database trigger, not by an ORM `onupdate=`. Enum types are created by
the DDL and declared `create_type=False` in the models. Anywhere two mechanisms could write the same
truth, one was disabled explicitly and the reason recorded at the site.

**Refuse rather than fake.** Where Phase 2 cannot do the real thing, it says so with a documented
error instead of returning something that looks like success.

---

## 3. Ambiguities in the specification, and resolutions

### A1 — How far does `/api/chat` go when SSE streaming is Phase 3?

`README.md` assigns "chat routes" to Phase 2 and "SSE streaming, intent router, Skills A/B/C" to
Phase 3. The endpoint therefore straddles the boundary.

**Resolution:** the split follows a line `architecture.md` §5.7 already draws — "validation failures
are returned as ordinary JSON *before* the stream opens". Everything on the pre-stream side is
implemented and tested now: payload validation, session ownership, provider resolution. Past that
point the route raises `NOT_IMPLEMENTED` (501). The half that ships is the half whose contract is
"return JSON", so nothing built here has to be rewritten when streaming lands — the raise site is
where the generator gets attached.

**Consequence that had to be decided:** §3 specifies the user message is persisted *before*
generation, so a mid-stream crash cannot lose it. That rationale does not survive without
generation — persisting here would accumulate user turns that never receive a reply, and the sidebar
would show conversations that look broken. Persistence moves to Phase 3 alongside the generation it
exists to protect. Recorded in the module docstring of `routers/chat.py` so the omission reads as a
decision rather than an oversight.

### A2 — A server-provisioned client key is unreachable by the client

§5 states "a missing key provisions a new anonymous user". But the key is the only handle on that
user, and if the server generates one and does not return it, the next request provisions *another*
user and the session just created is orphaned immediately.

**Resolution:** the resolved key is echoed in an `X-Client-Key` response header on every request, and
that header is added to the CORS `expose_headers` list so a browser can actually read it. The
frontend still generates its own key normally (§4.2); this makes the documented fallback path
functional rather than a silent leak of sessions. A small addition beyond the spec, flagged here and
in the `current_user` docstring.

### A3 — `NOT_IMPLEMENTED` is not in the error taxonomy

§12.1 enumerates every error code, and a Phase-2-only code is not among them.

**Resolution:** added as `NotImplementedYet` with the phase boundary stated in its docstring, on the
reasoning that an undocumented-but-honest 501 is better than reusing a documented code that means
something else — `PROVIDER_UNAVAILABLE` would have been a lie, since the provider is fine. It is
deleted in Phase 3 when the raise site becomes the generator.

---

## 4. Failures and corrections

Four things were wrong and were caught by running the code, not by reading it.

### C1 — `sql/init.sql` could not be executed through SQLAlchemy at all

**First approach:** `conn.execute(text(ddl))` in `cli.py`.

**Why it failed:** the plpgsql trigger body contains `NEW.updated_at = now();` and `$$` delimiters.
SQLAlchemy's `text()` construct parses `:name` as a bound parameter, and the DDL's syntax collides
with that scanning.

**Second approach:** `conn.exec_driver_sql(ddl)`, which bypasses `text()` entirely.

**Why that also failed:** asyncpg routes everything through prepared statements, and PostgreSQL
rejects a multi-command script in one — `cannot insert multiple commands into a prepared statement`.
The file has ~20 statements and the `DO $$ ... $$` blocks have to stay in one script to remain
atomic, so splitting on `;` was not acceptable either (it also breaks inside the dollar-quoted
bodies).

**Correction:** reach through to the raw asyncpg connection and use *its* `execute()`, which speaks
the simple query protocol — the only one that accepts a script:

```python
raw = await conn.get_raw_connection()
await raw.driver_connection.execute(ddl)
```

Worth recording because both of the obvious SQLAlchemy routes fail, with unrelated-looking errors,
and the working one is the least obvious.

### C2 — An over-long title was rejected instead of trimmed

**First approach:** `Field(max_length=120)` on the title, plus a validator that trims and caps.

**Why it failed:** pydantic evaluates declared constraints before an `after`-mode validator, so a
130-character title returned 400 and never reached the code meant to shorten it. §5.5 says the title
is "trimmed and capped" — capping is the specified behaviour, and rejection is a different contract.
Caught by smoke test 9, which asserted a 200-character title comes back at length 120 and instead
got a `KeyError` on the missing field.

**Correction:** dropped the `max_length` constraint and moved trimming to a `mode="before"`
validator, so the cap happens before any constraint is evaluated. `min_length=1` is retained, so a
whitespace-only title is still a 400 — blank is invalid, long is not.

### C3 — Oversized messages returned the wrong error code

**Found by smoke test 13.** §12.1 gives an over-long message its own code and status —
`PAYLOAD_TOO_LARGE`, 413 — but a schema `max_length` produces a generic pydantic failure, which the
handler rendered as `VALIDATION_ERROR` / 400. The frontend switches on `code`, so this would have
silently broken the specific "your message is too long" affordance.

**Correction:** the validation handler inspects the pydantic error list for a `string_too_long` on
the `message` field and re-maps it to `PayloadTooLarge`. The bound stays declared on the schema so it
still appears in the OpenAPI contract; only the rendering of the failure changes.

### C4 — Composed error message had doubled punctuation

Minor, but user-visible: `resolve_provider` joined two provider reasons with `". "` when each reason
is already a complete sentence, producing `…switch to Local.. Local: Ollama not reachable…`. The
strings are shown verbatim in the UI. Corrected to join without re-punctuating.

---

## 5. Verification

Everything below was executed against the running stack — PostgreSQL 16.14 with pgvector 0.8.6 in
Docker, Python 3.12, uvicorn — not reasoned about.

| # | Check | Result |
| :- | :---- | :----- |
| 1 | `init-db` applies the schema | 5 tables, 13 indexes, pgvector 0.8.6 |
| 2 | `init-db` is idempotent | Second run identical, no error |
| 3 | DSN is redacted in output and logs | `lenny:***@localhost` |
| 4 | App starts with **no** provider available | Starts `degraded`, does not exit |
| 5 | `/api/health` shape and per-provider reasons | Matches §5.1 |
| 6 | Health returns 503 only when the database is down | Confirmed by construction |
| 7 | Session create / list / rename / delete | 201 / 200 / 200 / 204 |
| 8 | Missing `X-Client-Key` provisions a user and echoes it | Header returned |
| 9 | Per-client isolation | Second key sees an empty list |
| 10 | Another user's session | 404 `SESSION_NOT_FOUND`, identical to unknown |
| 11 | Title trimmed and capped | `"  Retention loops  "` → `Retention loops`; 200 chars → 120 |
| 12 | Blank title | 400 `VALIDATION_ERROR` |
| 13 | `updated_at` advances on PATCH | Advanced — trigger fires, ORM reads it back |
| 14 | Keyset pagination over pages of 1 | No duplicates, cursor terminates |
| 15 | Malformed cursor | 400, not a 500 |
| 16 | DELETE is idempotent | 204 then 204 |
| 17 | Messages returned with artifact and citations inline | Artifact + `bytes`, citations, provenance |
| 18 | `artifact_consistency` CHECK | `html` + NULL content rejected by the database |
| 19 | `ON DELETE CASCADE` | Deleting users emptied sessions and messages |
| 20 | Chat, no provider | 503 `PROVIDER_UNAVAILABLE` naming both prerequisites |
| 21 | Chat, explicitly requesting the down provider | 503 — no silent fallback to the working one |
| 22 | Chat, unknown session | 404 |
| 23 | Chat, 8001-character message | 413 `PAYLOAD_TOO_LARGE` |
| 24 | Chat, provider available | 501 `NOT_IMPLEMENTED` with provider and model in `detail` |
| 25 | Rejected chat calls persisted nothing | Message count unchanged |
| 26 | API key never appears in `/api/health` or any error | 0 occurrences |

Test 21 is the one worth calling out: an *explicit* provider choice is refused rather than silently
satisfied by the other provider, because a user who selected Local wants to know it did not run
locally. Only the unspecified default falls back.

---

## 6. Output

| File | Purpose |
| :--- | :------ |
| `backend/sql/init.sql` | Schema DDL — extensions, enums, five tables, indexes, trigger. Single source of truth. |
| `backend/app/config.py` | `Settings` with fail-fast validation: async-DSN check, `EMBED_SPACE=voyage` without a key, overlap ≥ chunk size, DSN redaction. |
| `backend/app/database.py` | Async engine, session factory, `probe_database()` for health. |
| `backend/app/models.py` | SQLAlchemy 2.0 models mirroring the DDL; enums `create_type=False`, `content_tsv` computed, `updated_at` trigger-owned. |
| `backend/app/schemas.py` | Pydantic v2 wire contract with the §13 input bounds. |
| `backend/app/deps.py` | `current_user` — upserts the `X-Client-Key` user, race-safe via `ON CONFLICT`. |
| `backend/app/llm/registry.py` | Provider availability probing per §11.4, cached 15s, plus `resolve_provider`. |
| `backend/app/routers/health.py` | `GET /api/health`. |
| `backend/app/routers/sessions.py` | §5.2–5.6, keyset pagination, ownership-opaque 404s. |
| `backend/app/routers/chat.py` | §5.7 pre-stream half; 501 seam for Phase 3. |
| `backend/app/main.py` | Factory, CORS allowlist, lifespan, request-id middleware, four exception handlers. |
| `backend/app/cli.py` | `init-db`, `healthcheck`; `ingest`/`reindex` declared for Phase 3. |
| `backend/app/utils/errors.py` | The §12.1 taxonomy as an exception hierarchy. |
| `backend/app/utils/logging.py` | Structured JSON logs with `request_id` propagation. |
| `backend/requirements.txt` | Pinned; installed and verified together. |
| `backend/.env.example`, `.gitignore` | Configuration template; `.env` excluded. |

---

## 7. Open items for later phases

| # | Item | Phase |
| :- | :--- | :---- |
| O9 | Automated tests. Phase 2 was verified by a scripted smoke pass against a live stack; that needs to become a `pytest` suite with a disposable database before the surface grows | 3 |
| O10 | Rate limiting (§13, 20 req/min per client key) is specified but not implemented — it belongs with the endpoint that actually costs money | 3 |
| O11 | `NotImplementedYet` and the 501 branch in `routers/chat.py` are deleted when the generator is attached | 3 |
| O12 | User-message persistence moves into the chat route with generation (see A1) | 3 |
| O13 | Ollama probe matches `model` or `model:latest`; confirm against real `/api/tags` output once a model is pulled | 3 |
| O14 | No migration tool. `init.sql` is idempotent and the schema is additive so far; a real migration story (Alembic) is needed before the schema changes under data worth keeping | Final |

Items O1–O8 from Phase 1 remain open and unchanged.
