"""Shared FastAPI dependencies.

The important one is `current_user`: it turns the opaque `X-Client-Key` header
into a `users` row, which is the anchor for every ownership check in the app.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, Header, Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import db_session
from app.models import User
from app.utils.errors import ValidationError

log = logging.getLogger(__name__)

CLIENT_KEY_HEADER = "X-Client-Key"
MIN_CLIENT_KEY_CHARS = 8
MAX_CLIENT_KEY_CHARS = 128

DbSession = Annotated[AsyncSession, Depends(db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def current_user(
    request: Request,
    response: Response,
    session: DbSession,
    x_client_key: Annotated[str | None, Header(alias=CLIENT_KEY_HEADER)] = None,
) -> User:
    """Resolve — or provision — the anonymous user for this request.

    architecture.md §4.2/§5: the frontend generates an opaque key on first load
    and sends it on every request; a missing key provisions a new anonymous
    user. When we provision one, the key is echoed back in the `X-Client-Key`
    response header so the client can adopt and persist it — without that, a
    server-generated key would be unreachable and its sessions orphaned on the
    next request.
    """
    client_key = (x_client_key or "").strip()

    if client_key:
        if len(client_key) < MIN_CLIENT_KEY_CHARS or len(client_key) > MAX_CLIENT_KEY_CHARS:
            raise ValidationError(
                f"{CLIENT_KEY_HEADER} must be between {MIN_CLIENT_KEY_CHARS} and "
                f"{MAX_CLIENT_KEY_CHARS} characters."
            )
    else:
        client_key = secrets.token_urlsafe(24)
        log.info("provisioned anonymous user", extra={"path": request.url.path})

    # Upsert rather than SELECT-then-INSERT: two tabs opening at once with the
    # same fresh key would otherwise race into a unique violation. DO UPDATE
    # (not DO NOTHING) so RETURNING yields a row on the conflict path too.
    stmt = (
        pg_insert(User)
        .values(client_key=client_key)
        .on_conflict_do_update(
            index_elements=[User.client_key],
            set_={"client_key": client_key},
        )
        .returning(User)
    )
    user = (await session.execute(stmt)).scalar_one()

    response.headers[CLIENT_KEY_HEADER] = client_key
    return user


CurrentUser = Annotated[User, Depends(current_user)]
