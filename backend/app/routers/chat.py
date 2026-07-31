"""`POST /api/chat` — architecture.md §5.7.

The pre-stream half (payload validation, session ownership, provider
resolution) runs *before* the response opens, so those failures return ordinary
JSON. §5.7 requires this: a 4xx delivered as an SSE event leaves the client
unable to distinguish "bad request" from "bad answer".

Once the stream opens every outcome is an SSE frame, terminated by exactly one
`done` or `error`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agent.orchestrator import run_chat
from app.deps import AppSettings, CurrentUser, DbSession
from app.llm import registry
from app.models import Session
from app.schemas import ChatRequest
from app.utils.errors import SessionNotFound
from app.utils.sse import SSE_HEADERS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> StreamingResponse:
    # Ownership first: the same 404 for "no such session" and "someone else's
    # session", so this is not an existence oracle (§13).
    session = await db.scalar(
        select(Session).where(
            Session.id == payload.session_id, Session.user_id == user.id
        )
    )
    if session is None:
        raise SessionNotFound("That conversation does not exist.")

    # Raises ProviderUnavailable (503) naming the missing prerequisite. An
    # explicit provider choice is refused rather than silently satisfied by
    # the other one.
    status = await registry.resolve_provider(payload.llm_provider, settings)
    provider = registry.get_provider(status.name, settings)

    log.info(
        "chat request accepted",
        extra={
            "session_id": str(session.id),
            "provider": status.name,
            "model": status.model,
            "skill_override": payload.skill_override,
            "message_chars": len(payload.message),
        },
    )

    async def is_disconnected() -> bool:
        return await request.is_disconnected()

    stream = run_chat(
        db=db,
        settings=settings,
        provider=provider,
        session=session,
        user_message=payload.message,
        llm_provider_name=status.name,
        skill_override=payload.skill_override,
        is_disconnected=is_disconnected,
    )

    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)
