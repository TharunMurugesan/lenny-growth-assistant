"""Session CRUD — architecture.md §5.2 through §5.6.

Every read and write is filtered by the resolved `user_id`. An unknown session
and another user's session produce the identical 404, so the endpoint cannot be
used to enumerate which ids exist (§13).
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Message, Session
from app.schemas import (
    MAX_PAGE_SIZE,
    ArtifactOut,
    MessageOut,
    SessionCreate,
    SessionListOut,
    SessionMessagesOut,
    SessionOut,
    SessionRef,
    SessionUpdate,
)
from app.utils.errors import SessionNotFound, ValidationError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

DEFAULT_PAGE_SIZE = 50


# --- Keyset cursor --------------------------------------------------------
# Offset pagination skips or duplicates rows when the ordering column changes
# mid-scroll, and `updated_at` changes on every single turn. The cursor carries
# the full sort key — (updated_at, id) — so the next page resumes exactly where
# the last one ended even if rows have been reordered in between.


def _encode_cursor(updated_at: datetime, session_id: uuid.UUID) -> str:
    raw = f"{updated_at.isoformat()}|{session_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationError(
            "The pagination cursor is malformed. Request the first page without a cursor."
        ) from exc


def _message_count_subquery(session_id_col):  # type: ignore[no-untyped-def]
    return (
        select(func.count(Message.id))
        .where(Message.session_id == session_id_col)
        .correlate_except(Message)
        .scalar_subquery()
    )


def _last_skill_subquery(session_id_col):  # type: ignore[no-untyped-def]
    return (
        select(Message.skill)
        .where(Message.session_id == session_id_col, Message.skill.is_not(None))
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate_except(Message)
        .scalar_subquery()
    )


async def _load_owned_session(
    session_id: uuid.UUID, user_id: uuid.UUID, db: DbSession
) -> Session:
    """Fetch a session or raise the ownership-opaque 404."""
    row = await db.scalar(
        select(Session).where(Session.id == session_id, Session.user_id == user_id)
    )
    if row is None:
        raise SessionNotFound("That conversation does not exist.")
    return row


# --- 5.2 Create -----------------------------------------------------------


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    user: CurrentUser,
    db: DbSession,
    payload: SessionCreate | None = None,
) -> SessionOut:
    session = Session(user_id=user.id)
    if payload and payload.title:
        session.title = payload.title

    db.add(session)
    await db.flush()
    await db.refresh(session)

    log.info("session created", extra={"session_id": str(session.id)})
    return SessionOut(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
        last_skill=None,
    )


# --- 5.3 List -------------------------------------------------------------


@router.get("", response_model=SessionListOut)
async def list_sessions(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> SessionListOut:
    stmt = (
        select(
            Session,
            _message_count_subquery(Session.id).label("message_count"),
            _last_skill_subquery(Session.id).label("last_skill"),
        )
        .where(Session.user_id == user.id)
        .order_by(Session.updated_at.desc(), Session.id.desc())
        # One extra row is the cheapest way to know whether a next page exists
        # without a second COUNT query.
        .limit(limit + 1)
    )

    if cursor:
        cur_updated, cur_id = _decode_cursor(cursor)
        stmt = stmt.where(
            (Session.updated_at, Session.id) < (cur_updated, cur_id)
        )

    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    sessions = [
        SessionOut(
            id=row.Session.id,
            title=row.Session.title,
            created_at=row.Session.created_at,
            updated_at=row.Session.updated_at,
            message_count=row.message_count or 0,
            last_skill=row.last_skill,
        )
        for row in rows
    ]

    next_cursor = (
        _encode_cursor(rows[-1].Session.updated_at, rows[-1].Session.id)
        if has_more and rows
        else None
    )
    return SessionListOut(sessions=sessions, next_cursor=next_cursor)


# --- 5.4 Messages ---------------------------------------------------------


@router.get("/{session_id}/messages", response_model=SessionMessagesOut)
async def get_session_messages(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> SessionMessagesOut:
    session = await db.scalar(
        select(Session)
        .where(Session.id == session_id, Session.user_id == user.id)
        .options(selectinload(Session.messages))
    )
    if session is None:
        raise SessionNotFound("That conversation does not exist.")

    messages = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            # Inline, so reopening a past conversation restores a working
            # Artifact Viewer without a second round-trip.
            artifact=(
                ArtifactOut(
                    type=m.artifact_type,
                    title=m.artifact_title,
                    content=m.artifact_content or "",
                    bytes=len((m.artifact_content or "").encode("utf-8")),
                )
                if m.has_artifact
                else None
            ),
            skill=m.skill,
            provider=m.provider,
            model=m.model,
            citations=m.citations or [],
            word_count=m.word_count,
            finish_reason=m.finish_reason,
            created_at=m.created_at,
        )
        for m in session.messages  # relationship is ordered by created_at ASC
    ]

    return SessionMessagesOut(
        session=SessionRef(id=session.id, title=session.title), messages=messages
    )


# --- 5.5 Rename -----------------------------------------------------------


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdate,
    user: CurrentUser,
    db: DbSession,
) -> SessionOut:
    session = await _load_owned_session(session_id, user.id, db)
    session.title = payload.title

    await db.flush()
    # updated_at is set by trg_sessions_touch, so it must be read back rather
    # than assumed.
    await db.refresh(session)

    count = await db.scalar(
        select(func.count(Message.id)).where(Message.session_id == session.id)
    )
    last_skill = await db.scalar(
        select(Message.skill)
        .where(Message.session_id == session.id, Message.skill.is_not(None))
        .order_by(Message.created_at.desc())
        .limit(1)
    )

    return SessionOut(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=count or 0,
        last_skill=last_skill,
    )


# --- 5.6 Delete -----------------------------------------------------------


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """Idempotent: deleting an already-deleted session also returns 204.

    Messages go by cascade. No 404 here — a client retrying a delete it already
    completed has achieved what it asked for.
    """
    await db.execute(
        delete(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
