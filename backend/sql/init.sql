-- The Lenny Growth Assistant — schema DDL
-- Mirrors architecture.md §4. This file is the single source of truth for the
-- schema; app/models.py mirrors it for ORM access but never creates it.
--
-- Applied by:  python -m app.cli init-db
-- Idempotent:  safe to re-run against an existing database.
--
-- Why raw DDL rather than SQLAlchemy's create_all(): three constructs here have
-- no clean declarative expression — a GENERATED tsvector column, partial HNSW
-- indexes, and a plpgsql trigger. Splitting the schema across two mechanisms
-- would guarantee drift, so all of it lives here.

-- ---------------------------------------------------------------------------
-- 4.1 Extensions and enums
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;

DO $$ BEGIN
    CREATE TYPE message_role  AS ENUM ('user', 'assistant', 'system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE artifact_type AS ENUM ('none', 'html', 'markdown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE llm_provider  AS ENUM ('cloud', 'local');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE skill_name    AS ENUM ('qa', 'ship30', 'artifact', 'meta');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------------
-- 4.2 users — anonymous identity via an opaque client_key (X-Client-Key)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    client_key  TEXT        UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4.3 sessions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT        NOT NULL DEFAULT 'New chat',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Serves the sidebar query directly: the only hot read path on this table.
CREATE INDEX IF NOT EXISTS idx_sessions_user_recent
    ON sessions (user_id, updated_at DESC);

-- ---------------------------------------------------------------------------
-- 4.4 messages
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS messages (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID          NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role             message_role  NOT NULL,
    content          TEXT          NOT NULL DEFAULT '',
    artifact_type    artifact_type NOT NULL DEFAULT 'none',
    artifact_content TEXT,
    artifact_title   TEXT,
    skill            skill_name,
    provider         llm_provider,
    model            TEXT,
    citations        JSONB         NOT NULL DEFAULT '[]'::jsonb,
    token_usage      JSONB,
    word_count       INTEGER,
    finish_reason    TEXT,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT now(),

    -- Makes "typed as HTML but empty" unrepresentable, rather than a frontend
    -- guard that has to be remembered in three places.
    CONSTRAINT artifact_consistency CHECK (
        (artifact_type =  'none' AND artifact_content IS NULL) OR
        (artifact_type <> 'none' AND artifact_content IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_messages_session_time
    ON messages (session_id, created_at);

-- ---------------------------------------------------------------------------
-- 4.5 transcript_chunks — the knowledge base, both embedding spaces side by side
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS transcript_chunks (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_slug     TEXT        NOT NULL,
    episode_title    TEXT        NOT NULL,
    guest            TEXT,
    source_url       TEXT,
    chunk_index      INTEGER     NOT NULL,
    content          TEXT        NOT NULL,
    content_hash     TEXT        NOT NULL,
    token_count      INTEGER     NOT NULL,
    speakers         TEXT[]      NOT NULL DEFAULT '{}',
    embedding_local  vector(768),
    embedding_voyage vector(1024),
    content_tsv      tsvector GENERATED ALWAYS AS
                         (to_tsvector('english', content)) STORED,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_chunk UNIQUE (episode_slug, chunk_index)
);

-- Partial HNSW indexes: a pgvector column has fixed dimensionality, so 768-d
-- and 1024-d vectors cannot share a column or an index.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_local
    ON transcript_chunks USING hnsw (embedding_local vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding_local IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_voyage
    ON transcript_chunks USING hnsw (embedding_voyage vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE embedding_voyage IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_tsv
    ON transcript_chunks USING gin (content_tsv);

CREATE INDEX IF NOT EXISTS idx_chunks_episode
    ON transcript_chunks (episode_slug, chunk_index);

-- ---------------------------------------------------------------------------
-- 4.6 ingest_runs — operational log; /api/health reports the latest per space
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingest_runs (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    embed_space    TEXT        NOT NULL,
    embed_model    TEXT        NOT NULL,
    status         TEXT        NOT NULL DEFAULT 'running',
    episodes_seen  INTEGER     NOT NULL DEFAULT 0,
    chunks_written INTEGER     NOT NULL DEFAULT 0,
    chunks_skipped INTEGER     NOT NULL DEFAULT 0,
    error          TEXT,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- 4.7 updated_at trigger
-- Enforced in the database, not the ORM: sidebar ordering depends on
-- updated_at, and a code path that forgets to set it corrupts that ordering
-- silently.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sessions_touch ON sessions;
CREATE TRIGGER trg_sessions_touch BEFORE UPDATE ON sessions
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS trg_chunks_touch ON transcript_chunks;
CREATE TRIGGER trg_chunks_touch BEFORE UPDATE ON transcript_chunks
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
