"""Async engine, session factory, and the database health probe.

Nothing above this module constructs an engine; the rest of the app takes an
`AsyncSession` from the `db_session` dependency.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.utils.errors import DatabaseUnavailable

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine. Called once from the lifespan handler."""
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=5,
        # Recycle below typical idle-connection reapers so a pooled connection
        # is never handed out already dead.
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create the process-wide engine and session factory."""
    global _engine, _session_factory
    settings = settings or get_settings()
    if _engine is None:
        _engine = create_engine(settings)
        _session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        log.info("database engine created", extra={"dsn": settings.redacted_dsn()})
    return _engine


async def dispose_engine() -> None:
    """Close every pooled connection. Called on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        log.info("database engine disposed")


def get_engine_or_none() -> AsyncEngine | None:
    """The engine if initialized, else None.

    `/api/health` must be able to report "engine not initialized" rather than
    raise, so it cannot use a strict accessor.
    """
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("init_engine() must be called before requesting a session")
    return _session_factory


async def db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session, committing on clean exit.

    A driver-level failure is translated to DatabaseUnavailable here so no
    router has to know what an `SQLAlchemyError` is.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        log.error("database error", exc_info=exc)
        raise DatabaseUnavailable(
            "The database is not reachable right now. Please retry shortly."
        ) from exc
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@dataclass
class DatabaseHealth:
    """What `/api/health` reports about the database — architecture.md §5.1."""

    connected: bool
    pgvector: bool = False
    chunks: dict[str, int] = field(default_factory=dict)
    last_ingest: dict[str, Any] | None = None
    error: str | None = None


async def probe_database(engine: AsyncEngine) -> DatabaseHealth:
    """Answer "what works right now?" for the database half of §5.1.

    Never raises: a health endpoint that 500s tells an operator nothing. A
    failure is reported as `connected: false` with a redacted reason.
    """
    try:
        async with engine.connect() as conn:
            has_vector = bool(
                await conn.scalar(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
            )
            if not has_vector:
                return DatabaseHealth(
                    connected=True,
                    pgvector=False,
                    error="The 'vector' extension is not installed in this database.",
                )

            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT count(*)                                   AS total,
                               count(embedding_local)                     AS local,
                               count(embedding_voyage)                    AS voyage
                        FROM transcript_chunks
                        """
                    )
                )
            ).one()

            last = (
                await conn.execute(
                    text(
                        """
                        SELECT embed_space, status, finished_at
                        FROM ingest_runs
                        WHERE status = 'success'
                        ORDER BY finished_at DESC NULLS LAST
                        LIMIT 1
                        """
                    )
                )
            ).one_or_none()

        return DatabaseHealth(
            connected=True,
            pgvector=True,
            chunks={
                "total": counts.total,
                "local": counts.local,
                "voyage": counts.voyage,
            },
            last_ingest=(
                {
                    "embed_space": last.embed_space,
                    "status": last.status,
                    "finished_at": last.finished_at,
                }
                if last
                else None
            ),
        )
    except SQLAlchemyError as exc:
        log.error("database probe failed", exc_info=exc)
        return DatabaseHealth(
            connected=False,
            error="Database connection failed. Check that PostgreSQL is running.",
        )
