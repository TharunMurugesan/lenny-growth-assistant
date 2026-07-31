"""FastAPI application factory — CORS, lifespan, exception handlers.

Startup is fail-fast (architecture.md §12.2): invalid configuration or an
unreachable database refuses to start, with a readable reason. A missing LLM
provider does *not* — history stays browsable and the toggle explains itself,
which is the degradation ladder in §12.3.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import APP_VERSION, ConfigError, Settings, get_settings
from app.database import dispose_engine, init_engine, probe_database
from app.llm import registry
from app.routers import chat, health, sessions
from app.schemas import MAX_MESSAGE_CHARS
from app.utils.errors import AppError, InternalError, PayloadTooLarge, ValidationError
from app.utils.logging import configure_logging, new_request_id, request_id_ctx

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()

    engine = init_engine(settings)
    probe = await probe_database(engine)

    if not probe.connected:
        raise ConfigError(
            "Cannot reach the database at "
            f"{settings.redacted_dsn()}. Is PostgreSQL running?\n"
            "  docker start lenny-postgres"
        )
    if not probe.pgvector:
        raise ConfigError(
            "The 'vector' extension is missing from "
            f"{settings.redacted_dsn()}.\n"
            "  python -m app.cli init-db"
        )

    statuses = await registry.get_all_statuses(settings)
    available = [n for n, s in statuses.items() if s.available]
    if not available:
        # Explicitly not fatal — §12.3 keeps history browsable with the
        # composer disabled rather than taking the whole app down.
        log.warning(
            "no LLM provider available; starting in degraded mode",
            extra={n: s.reason for n, s in statuses.items()},
        )

    log.info(
        "startup complete",
        extra={
            "version": APP_VERSION,
            "env": settings.app_env,
            "providers_available": available,
            "embed_space": settings.embed_space,
            "chunks": probe.chunks.get("total", 0),
        },
    )

    yield

    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.is_production)

    app = FastAPI(
        title="The Lenny Growth Assistant",
        version=APP_VERSION,
        lifespan=lifespan,
        # Interactive docs are a development affordance, not a production
        # surface.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # explicit allowlist, never "*"
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Client-Key"],
        expose_headers=["X-Client-Key", REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Generate a correlation id, bind it for logging, return it in the response."""
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_request_id()
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_ctx.reset(token)

    # --- Exception handlers: one envelope shape for every failure (§5.8) ---

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = request_id_ctx.get()
        log.warning(
            "request failed",
            extra={"code": exc.code, "status": exc.http_status, "path": request.url.path},
        )
        return JSONResponse(
            status_code=exc.http_status, content=exc.to_envelope(request_id)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Flatten pydantic's error list into one displayable sentence.

        An over-long `message` is re-mapped to 413 PAYLOAD_TOO_LARGE, because
        §12.1 gives it its own code and status. The bound stays declared on the
        schema so it appears in the OpenAPI contract; only the rendering of the
        failure differs.
        """
        problems = [
            f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}"
            for err in exc.errors()
        ]

        oversize = any(
            err["type"] == "string_too_long" and err["loc"][-1] == "message"
            for err in exc.errors()
        )
        error: AppError
        if oversize:
            error = PayloadTooLarge(
                f"Your message is too long. The limit is {MAX_MESSAGE_CHARS:,} characters.",
                detail={"max_chars": MAX_MESSAGE_CHARS},
            )
        else:
            error = ValidationError(
                "; ".join(problems) or "The request payload is invalid.",
                detail={"fields": problems},
            )

        return JSONResponse(
            status_code=error.http_status,
            content=error.to_envelope(request_id_ctx.get()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Keep framework-raised 404/405 in the same envelope as everything else."""
        error = AppError(str(exc.detail))
        error.code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        error.http_status = exc.status_code
        return JSONResponse(
            status_code=exc.status_code,
            content=error.to_envelope(request_id_ctx.get()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Log the stack trace; never return one (§12.1)."""
        log.exception("unhandled exception", extra={"path": request.url.path})
        error = InternalError("Something went wrong on our end.")
        return JSONResponse(
            status_code=error.http_status,
            content=error.to_envelope(request_id_ctx.get()),
        )

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)

    return app


app = create_app()
