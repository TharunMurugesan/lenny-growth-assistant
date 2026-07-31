"""Typed configuration, validated once at import time.

architecture.md §12.2: a half-initialized app that returns 500s is strictly
worse than one that refuses to start with a readable reason. Every
contradiction that can be detected from configuration alone is detected here,
before the app accepts traffic.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"

ProviderName = Literal["cloud", "local"]
EmbedSpace = Literal["local", "voyage"]


class ConfigError(RuntimeError):
    """Configuration is invalid or self-contradictory. Fatal at startup."""


class Settings(BaseSettings):
    """All backend configuration. Read from the environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core -----------------------------------------------------------
    database_url: str = Field(
        ...,
        description="Async DSN, e.g. postgresql+asyncpg://lenny:lenny@localhost:5432/lenny",
    )
    app_env: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"
    default_llm_provider: ProviderName = "cloud"

    # --- Cloud provider (Anthropic) -------------------------------------
    anthropic_api_key: str | None = None
    anthropic_chat_model: str = "claude-sonnet-4-6"
    anthropic_router_model: str = "claude-haiku-4-5-20251001"
    anthropic_max_tokens: int = Field(default=4096, ge=256, le=64_000)
    cloud_timeout_seconds: int = Field(default=120, ge=1)

    # --- Local provider (Ollama) ----------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.1:8b-instruct-q4_K_M"
    ollama_embed_model: str = "nomic-embed-text"
    # Ollama defaults num_ctx to 4096 and silently truncates anything longer.
    # A Skill A prompt carries 8 retrieved chunks (~6k tokens) and Skill B
    # carries 10, so at the default the local path answers from partially
    # truncated grounding with no error and no warning — the worst failure
    # shape there is. Sized to fit the largest prompt plus its output budget.
    ollama_num_ctx: int = Field(default=16384, ge=2048)
    ollama_connect_timeout: int = Field(default=5, ge=1)
    ollama_first_token_timeout: int = Field(default=90, ge=1)
    ollama_idle_timeout: int = Field(default=120, ge=1)

    # --- Retrieval ------------------------------------------------------
    embed_space: EmbedSpace = "local"
    voyage_api_key: str | None = None
    voyage_embed_model: str = "voyage-3"
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_candidates: int = Field(default=40, ge=1, le=500)
    chunk_tokens: int = Field(default=800, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0)

    # --- Validators -----------------------------------------------------

    @field_validator("database_url")
    @classmethod
    def _must_be_async_dsn(cls, v: str) -> str:
        """Reject a sync DSN at startup rather than at first query.

        `postgresql://` silently selects psycopg2, which is not installed and
        would surface much later as an opaque driver error.
        """
        if not v.strip():
            raise ValueError("DATABASE_URL must not be empty")
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver, i.e. start with "
                "'postgresql+asyncpg://'. Got: "
                f"'{v.split('://', 1)[0]}://…'"
            )
        return v

    @field_validator("anthropic_api_key", "voyage_api_key", mode="before")
    @classmethod
    def _blank_key_is_absent(cls, v: object) -> object:
        """Treat `ANTHROPIC_API_KEY=` in a .env file as unset.

        `.env.example` ships the keys blank so the file is copyable as-is; an
        empty string must mean "no key", not "a key that is the empty string".
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("chunk_overlap_tokens")
    @classmethod
    def _overlap_below_chunk(cls, v: int, info: ValidationInfo) -> int:
        chunk = info.data.get("chunk_tokens")
        if chunk is not None and v >= chunk:
            raise ValueError(
                f"CHUNK_OVERLAP_TOKENS ({v}) must be smaller than "
                f"CHUNK_TOKENS ({chunk}); equal or greater never terminates."
            )
        return v

    @field_validator("voyage_api_key")
    @classmethod
    def _voyage_space_needs_key(cls, v: str | None, info: ValidationInfo) -> str | None:
        if info.data.get("embed_space") == "voyage" and not v:
            raise ValueError(
                "EMBED_SPACE=voyage requires VOYAGE_API_KEY. Anthropic has no "
                "embeddings endpoint, so the Voyage space cannot be queried "
                "without one. Set the key, or use EMBED_SPACE=local."
            )
        return v

    # --- Derived --------------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cloud_configured(self) -> bool:
        """Whether Cloud mode *could* work — key present and plausibly shaped.

        architecture.md §11.4: validity is discovered on first real use, not
        by spending an API request per health poll.
        """
        key = self.anthropic_api_key
        return bool(key and key.startswith("sk-ant-") and len(key) > 20)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def redacted_dsn(self) -> str:
        """The DSN with its password replaced, safe for logs and errors.

        architecture.md §13: an error message never carries a credential.
        """
        return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Raises ConfigError with a readable message on invalid configuration —
    pydantic's raw ValidationError is accurate but not friendly at 3am.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001 - re-raised as a fatal config error
        raise ConfigError(f"Invalid configuration:\n{exc}") from exc
