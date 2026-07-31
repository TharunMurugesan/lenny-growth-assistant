"""`GET /api/health` — architecture.md §5.1.

The single place to answer "what works right now?". Reports capability rather
than a bare liveness bit, because the UI uses it to decide which half of the
LLM toggle to disable and why.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.config import APP_VERSION
from app.database import get_engine_or_none, probe_database
from app.deps import AppSettings
from app.llm import registry
from app.schemas import DatabaseHealthOut, HealthOut, ProviderHealth

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(response: Response, settings: AppSettings) -> HealthOut:
    """Always 200 unless the database is down, in which case 503.

    A monitoring probe should not page because an *optional* provider is
    missing — that is `degraded`, and the app is still useful in that state.
    """
    engine = get_engine_or_none()
    if engine is None:
        db_health = DatabaseHealthOut(
            connected=False, error="Database engine is not initialized."
        )
    else:
        probe = await probe_database(engine)
        db_health = DatabaseHealthOut(
            connected=probe.connected,
            pgvector=probe.pgvector,
            chunks=probe.chunks,
            last_ingest=probe.last_ingest,
            error=probe.error,
        )

    statuses = await registry.get_all_statuses(settings)
    providers = {
        name: ProviderHealth(
            available=s.available, model=s.model, reason=s.reason
        )
        for name, s in statuses.items()
    }

    if not db_health.connected or not db_health.pgvector:
        overall = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not all(s.available for s in statuses.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return HealthOut(
        status=overall,
        version=APP_VERSION,
        database=db_health,
        providers=providers,
        embed_space=settings.embed_space,
    )
