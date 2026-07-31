"""Pydantic v2 request/response models — the wire contract of architecture.md §5.

Input bounds are declared here rather than checked in routers, so the limits in
§13 (messages 8000 chars, titles 120, page size 200) hold on every path that
parses a payload.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_MESSAGE_CHARS = 8_000
MAX_TITLE_CHARS = 120
MAX_PAGE_SIZE = 200

ProviderName = Literal["cloud", "local"]
SkillName = Literal["qa", "ship30", "artifact", "meta"]
ArtifactType = Literal["html", "markdown"]


def _trimmed_title(v: str) -> str:
    """Trim, then cap. §5.5 specifies both, in that order."""
    return v.strip()[:MAX_TITLE_CHARS]


# --- Sessions -------------------------------------------------------------


class SessionCreate(BaseModel):
    """`POST /api/sessions` — body optional; an absent title means 'New chat'."""

    # No max_length constraint: §5.5 caps the title, it does not reject it.
    # A declared constraint would fire before the validator and turn an
    # over-long title into a 400 instead of a silently trimmed one.
    title: str | None = Field(default=None)

    @field_validator("title", mode="before")
    @classmethod
    def _clean(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        return _trimmed_title(v) or None


class SessionUpdate(BaseModel):
    """`PATCH /api/sessions/{id}`."""

    title: Annotated[str, Field(min_length=1)]

    @field_validator("title", mode="before")
    @classmethod
    def _clean(cls, v: object) -> object:
        """Trim, then cap at 120 — §5.5. Blank after trimming is still an error."""
        if not isinstance(v, str):
            return v
        cleaned = _trimmed_title(v)
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_skill: SkillName | None = None


class SessionListOut(BaseModel):
    sessions: list[SessionOut]
    next_cursor: str | None = None


# --- Messages -------------------------------------------------------------


class ArtifactOut(BaseModel):
    """Returned inline so reopening a conversation restores a working viewer."""

    type: ArtifactType
    title: str | None = None
    content: str
    bytes: int


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: Literal["user", "assistant", "system"]
    content: str
    artifact: ArtifactOut | None = None
    skill: SkillName | None = None
    provider: ProviderName | None = None
    model: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    word_count: int | None = None
    finish_reason: str | None = None
    created_at: datetime


class SessionRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str


class SessionMessagesOut(BaseModel):
    session: SessionRef
    messages: list[MessageOut]


# --- Chat -----------------------------------------------------------------


class ChatRequest(BaseModel):
    """`POST /api/chat` — architecture.md §5.7."""

    session_id: uuid.UUID
    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]
    llm_provider: ProviderName | None = None
    # `meta` is absent by design: Skill D is reached by classification only,
    # never selected by a client.
    skill_override: Literal["qa", "ship30", "artifact"] | None = None

    @field_validator("message")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        """§5.7 bounds the message *after* trimming, so trim first."""
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("message must not be blank")
        return cleaned


# --- Health ---------------------------------------------------------------


class ProviderHealth(BaseModel):
    available: bool
    model: str
    reason: str | None = None


class DatabaseHealthOut(BaseModel):
    connected: bool
    pgvector: bool = False
    chunks: dict[str, int] = Field(default_factory=dict)
    last_ingest: dict[str, Any] | None = None
    error: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    database: DatabaseHealthOut
    providers: dict[str, ProviderHealth]
    embed_space: Literal["local", "voyage"]
