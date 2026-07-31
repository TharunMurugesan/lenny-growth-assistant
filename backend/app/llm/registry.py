"""Provider registry and availability probing — architecture.md §11.4.

`get_provider()` returns something that can actually generate; `get_status()`
answers whether it could, cheaply enough to call on every health poll.

Cloud availability is answered without a network call — a key's validity is
discovered on first real use rather than spending an API request per health
poll. Local availability checks both that the daemon answers *and* that the
configured model is pulled, because "daemon up, model missing" is the most
common local misconfiguration and produces a confusing 404 otherwise.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.utils.errors import ProviderUnavailable

log = logging.getLogger(__name__)

PROBE_CACHE_TTL_SECONDS = 15.0


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    model: str
    reason: str | None = None


_cache: dict[str, tuple[float, ProviderStatus]] = {}


def _cached(key: str) -> ProviderStatus | None:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < PROBE_CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _store(key: str, status: ProviderStatus) -> ProviderStatus:
    _cache[key] = (time.monotonic(), status)
    return status


def reset_probe_cache() -> None:
    """Drop cached probes. Used by tests and by `cli healthcheck`."""
    _cache.clear()


def probe_cloud(settings: Settings) -> ProviderStatus:
    """No network call — key presence and shape only."""
    model = settings.anthropic_chat_model
    if not settings.anthropic_api_key:
        return ProviderStatus(
            name="cloud",
            available=False,
            model=model,
            reason=(
                "ANTHROPIC_API_KEY is not set. Set it to enable Cloud mode, "
                "or switch to Local."
            ),
        )
    if not settings.cloud_configured:
        return ProviderStatus(
            name="cloud",
            available=False,
            model=model,
            reason=(
                "ANTHROPIC_API_KEY does not look like an Anthropic key "
                "(expected an 'sk-ant-' prefix)."
            ),
        )
    return ProviderStatus(name="cloud", available=True, model=model)


async def probe_local(settings: Settings) -> ProviderStatus:
    """`GET {OLLAMA_BASE_URL}/api/tags`, then confirm the chat model is present."""
    model = settings.ollama_chat_model
    url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.ollama_connect_timeout)
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        log.info("ollama probe failed", extra={"url": url, "error": type(exc).__name__})
        return ProviderStatus(
            name="local",
            available=False,
            model=model,
            reason=f"Ollama not reachable at {settings.ollama_base_url}",
        )
    except ValueError:
        return ProviderStatus(
            name="local",
            available=False,
            model=model,
            reason=f"Ollama at {settings.ollama_base_url} returned an unreadable response.",
        )

    # Ollama reports "llama3.1:8b" as "llama3.1:8b"; an untagged configured
    # name should still match the ":latest" the daemon reports back.
    installed = {m.get("name", "") for m in payload.get("models", [])}
    wanted = {model, f"{model}:latest"}
    if not (installed & wanted):
        return ProviderStatus(
            name="local",
            available=False,
            model=model,
            reason=(
                f"Ollama is running but the model '{model}' is not pulled. "
                f"Run: ollama pull {model}"
            ),
        )

    return ProviderStatus(name="local", available=True, model=model)


async def get_status(name: str, settings: Settings) -> ProviderStatus:
    """Availability for one provider, cached for 15 seconds."""
    hit = _cached(name)
    if hit is not None:
        return hit
    status = probe_cloud(settings) if name == "cloud" else await probe_local(settings)
    return _store(name, status)


async def get_all_statuses(settings: Settings) -> dict[str, ProviderStatus]:
    return {
        "cloud": await get_status("cloud", settings),
        "local": await get_status("local", settings),
    }


def get_provider(name: str, settings: Settings) -> Any:
    """Construct a usable provider by name.

    Imported lazily so that `/api/health` — which only needs `get_status` —
    never pays for constructing an SDK client, and so a broken optional
    dependency cannot take down the health endpoint.
    """
    if name == "cloud":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if name == "local":
        from app.llm.ollama_provider import OllamaProvider

        return OllamaProvider(settings)
    raise ProviderUnavailable(f"Unknown provider '{name}'.", detail={"provider": name})


async def resolve_provider(
    requested: str | None, settings: Settings
) -> ProviderStatus:
    """Pick the provider for a chat request — architecture.md §5.7.

    An explicit request is honoured or refused; it never silently falls back,
    because a user who chose Local wants to know it did not run locally. Only
    the *default* falls back, since no choice was expressed.
    """
    statuses = await get_all_statuses(settings)

    if requested is not None:
        status = statuses[requested]
        if not status.available:
            raise ProviderUnavailable(
                status.reason or f"The {requested} provider is unavailable.",
                detail={"provider": requested},
            )
        return status

    preferred = statuses[settings.default_llm_provider]
    if preferred.available:
        return preferred

    other_name = "local" if settings.default_llm_provider == "cloud" else "cloud"
    other = statuses[other_name]
    if other.available:
        log.info(
            "default provider unavailable, falling back",
            extra={"from": settings.default_llm_provider, "to": other_name},
        )
        return other

    # The per-provider reasons are already complete sentences, so they are
    # joined rather than punctuated again.
    raise ProviderUnavailable(
        "No LLM provider is available. "
        f"Cloud: {statuses['cloud'].reason} "
        f"Local: {statuses['local'].reason}",
        detail={"cloud": statuses["cloud"].reason, "local": statuses["local"].reason},
    )
