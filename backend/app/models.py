"""SQLAlchemy 2.0 declarative models — mirrors sql/init.sql exactly.

These models describe the schema for ORM access; they never create it.
`python -m app.cli init-db` executes `sql/init.sql`, which is the single source
of truth (see the header of that file for why).

Consequences of that split, enforced below:
  * every enum is declared with `create_type=False` — the DDL owns the types;
  * `content_tsv` is `Computed(...)`, so SQLAlchemy reads it and never writes it;
  * `updated_at` carries no `onupdate=` — the database trigger owns it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Enum types -----------------------------------------------------------
# create_type=False: sql/init.sql creates these. Left at the default, metadata
# operations would try to CREATE TYPE and fail against a live database.

MessageRoleEnum = ENUM(
    "user", "assistant", "system", name="message_role", create_type=False
)
ArtifactTypeEnum = ENUM(
    "none", "html", "markdown", name="artifact_type", create_type=False
)
LLMProviderEnum = ENUM("cloud", "local", name="llm_provider", create_type=False)
SkillNameEnum = ENUM(
    "qa", "ship30", "artifact", "meta", name="skill_name", create_type=False
)


class User(Base):
    """Anonymous identity keyed by an opaque `client_key` — architecture.md §4.2."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    client_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Session(Base):
    """One conversation."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user_recent", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="New chat"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # No onupdate=: trg_sessions_touch owns this column. Setting it here too
    # would be a second source of truth for the sidebar's ordering key.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions")
    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )


class Message(Base):
    """One turn. Artifacts are stored inline — architecture.md §4.4."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "(artifact_type = 'none' AND artifact_content IS NULL) OR "
            "(artifact_type <> 'none' AND artifact_content IS NOT NULL)",
            name="artifact_consistency",
        ),
        Index("idx_messages_session_time", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(MessageRoleEnum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    artifact_type: Mapped[str] = mapped_column(
        ArtifactTypeEnum, nullable=False, server_default="none"
    )
    artifact_content: Mapped[str | None] = mapped_column(Text)
    artifact_title: Mapped[str | None] = mapped_column(Text)

    # Provenance: how this answer was produced. Lets history stamp the skill
    # and model badge on messages generated before a config change.
    skill: Mapped[str | None] = mapped_column(SkillNameEnum)
    provider: Mapped[str | None] = mapped_column(LLMProviderEnum)
    model: Mapped[str | None] = mapped_column(Text)

    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    token_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    word_count: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[Session] = relationship(back_populates="messages")

    @property
    def has_artifact(self) -> bool:
        return self.artifact_type != "none" and self.artifact_content is not None


class TranscriptChunk(Base):
    """The knowledge base. Standalone — no FK to conversation data."""

    __tablename__ = "transcript_chunks"
    __table_args__ = (
        UniqueConstraint("episode_slug", "chunk_index", name="uq_chunk"),
        Index("idx_chunks_episode", "episode_slug", "chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    episode_slug: Mapped[str] = mapped_column(Text, nullable=False)
    episode_title: Mapped[str] = mapped_column(Text, nullable=False)
    guest: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Makes ingestion idempotent: unchanged text is never re-embedded.
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    speakers: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    # Two columns, not one: pgvector dimensionality is fixed per column, and
    # nomic-embed-text (768) and voyage-3 (1024) cannot share one.
    embedding_local: Mapped[list[float] | None] = mapped_column(Vector(768))
    embedding_voyage: Mapped[list[float] | None] = mapped_column(Vector(1024))

    # Generated column: Postgres keeps it consistent with `content`, and
    # Computed() stops SQLAlchemy ever including it in an INSERT or UPDATE.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestRun(Base):
    """Operational log for `transcript_chunks` — architecture.md §4.6."""

    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    embed_space: Mapped[str] = mapped_column(String, nullable=False)
    embed_model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="running"
    )
    episodes_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    chunks_written: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    chunks_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
