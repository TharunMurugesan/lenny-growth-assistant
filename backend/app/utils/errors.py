"""Error taxonomy — architecture.md §12.1.

One exception hierarchy carrying a stable machine-readable `code`, the HTTP
status it maps to, and whether a retry could plausibly succeed. Routers raise
these; a single handler in main.py renders the envelope from §5.8.

The `message` on every one of these is written to be displayed to a user
verbatim. It never contains a secret, a DSN with credentials, or a stack trace.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base for every expected failure. Carries its own HTTP mapping."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_envelope(self, request_id: str) -> dict[str, Any]:
        """Render the §5.8 error envelope."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "detail": self.detail,
                "request_id": request_id,
            }
        }


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 400


class SessionNotFound(AppError):
    """Unknown session, or one owned by another client key.

    architecture.md §13: both cases return this identical error, so the
    endpoint cannot be used to enumerate which session ids exist.
    """

    code = "SESSION_NOT_FOUND"
    http_status = 404


class ProviderUnavailable(AppError):
    code = "PROVIDER_UNAVAILABLE"
    http_status = 503


class ModelNotFound(AppError):
    code = "MODEL_NOT_FOUND"
    http_status = 503


class ProviderTimeout(AppError):
    code = "PROVIDER_TIMEOUT"
    http_status = 504
    retryable = True


class ProviderError(AppError):
    code = "PROVIDER_ERROR"
    http_status = 502
    retryable = True


class RateLimited(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    retryable = True


class DatabaseUnavailable(AppError):
    code = "DATABASE_UNAVAILABLE"
    http_status = 503
    retryable = True


class PgVectorMissing(AppError):
    code = "PGVECTOR_MISSING"
    http_status = 500


class RetrievalEmpty(AppError):
    code = "RETRIEVAL_EMPTY"
    http_status = 409


class PayloadTooLarge(AppError):
    code = "PAYLOAD_TOO_LARGE"
    http_status = 413


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    http_status = 500


class NotImplementedYet(AppError):
    """A route whose contract is fixed but whose implementation lands later.

    Phase 2 only. `POST /api/chat` validates and authorizes fully, then raises
    this instead of streaming, because generation is Phase 3. Preferable to a
    stub that fabricates an answer: the client sees an honest, documented
    refusal rather than a fake success.
    """

    code = "NOT_IMPLEMENTED"
    http_status = 501
