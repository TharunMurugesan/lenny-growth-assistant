"""Embedding backends — architecture.md §10.1, §11.2.

Anthropic has no embeddings endpoint, which is the whole reason `EMBED_SPACE`
is configured independently of the chat provider. Cloud-quality embeddings come
from Voyage; the local path uses Ollama and works fully offline.

The dimensionality of each backend is fixed and must match its column in
`transcript_chunks` — 768 for `embedding_local`, 1024 for `embedding_voyage`.
`DIMENSIONS` is asserted against every response rather than trusted, because a
silent dimension mismatch surfaces much later as an opaque pgvector error.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Protocol

import httpx

from app.config import Settings
from app.utils.errors import ProviderError, ProviderTimeout

log = logging.getLogger(__name__)

BATCH_SIZE = 64
MAX_RETRIES = 3


class Embedder(Protocol):
    space: str
    model: str
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


async def _backoff(attempt: int) -> None:
    await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))


class OllamaEmbedder:
    """`nomic-embed-text`, 768-d. Fully offline.

    Uses the batch `/api/embed` endpoint, which measured ~3x the throughput of
    the legacy one-prompt-per-call `/api/embeddings` on this corpus. That
    difference is the whole ingest: at the sequential rate a full run took
    about an hour. `/api/embeddings` is kept as a fallback for daemons too old
    to expose the batch route.
    """

    space = "local"
    dimensions = 768

    def __init__(self, settings: Settings) -> None:
        self.model = settings.ollama_embed_model
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.settings = settings
        self._batch_supported = True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float]] = []
        timeout = httpx.Timeout(connect=5.0, read=300.0, write=60.0, pool=5.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            for i in range(0, len(texts), BATCH_SIZE):
                batch = texts[i : i + BATCH_SIZE]
                if self._batch_supported:
                    vectors = await self._embed_batch(client, batch)
                    if vectors is not None:
                        out.extend(vectors)
                        continue
                    # Fell through: daemon has no /api/embed. Don't retry it.
                    self._batch_supported = False
                    log.info("ollama /api/embed unavailable, using /api/embeddings")
                for text in batch:
                    out.append(await self._embed_one(client, text))
        return out

    async def _embed_batch(
        self, client: httpx.AsyncClient, batch: list[str]
    ) -> list[list[float]] | None:
        """Returns None if the endpoint is absent, so the caller can fall back."""
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                vectors = response.json().get("embeddings") or []
                if len(vectors) != len(batch):
                    raise ProviderError(
                        f"Embedding batch returned {len(vectors)} vectors "
                        f"for {len(batch)} inputs."
                    )
                if vectors and len(vectors[0]) != self.dimensions:
                    raise ProviderError(
                        f"Embedding model '{self.model}' returned {len(vectors[0])} "
                        f"dimensions; the schema column expects {self.dimensions}."
                    )
                return vectors
            except ProviderError:
                raise
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ProviderError(
                    f"Ollama is not reachable at {self.base_url}. "
                    "Start it with: ollama serve"
                ) from exc
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await _backoff(attempt)

        if isinstance(last, httpx.ReadTimeout):
            raise ProviderTimeout("The local embedding model timed out.") from last
        raise ProviderError("Local embedding failed.") from last

    async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]:
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                vector = response.json().get("embedding") or []
                if len(vector) != self.dimensions:
                    raise ProviderError(
                        f"Embedding model '{self.model}' returned {len(vector)} "
                        f"dimensions; the schema column expects {self.dimensions}."
                    )
                return vector
            except ProviderError:
                raise  # a dimension mismatch is fatal, not transient
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise ProviderError(
                    f"Ollama is not reachable at {self.base_url}. "
                    "Start it with: ollama serve"
                ) from exc
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await _backoff(attempt)

        if isinstance(last, httpx.ReadTimeout):
            raise ProviderTimeout("The local embedding model timed out.") from last
        raise ProviderError("Local embedding failed.") from last


class VoyageEmbedder:
    """`voyage-3`, 1024-d. Batched, since the API accepts a list."""

    space = "voyage"
    dimensions = 1024

    def __init__(self, settings: Settings) -> None:
        self.model = settings.voyage_embed_model
        self.api_key = settings.voyage_api_key
        self.url = "https://api.voyageai.com/v1/embeddings"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise ProviderError(
                "VOYAGE_API_KEY is not set, so the voyage embedding space cannot be used."
            )

        out: list[list[float]] = []
        timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            for i in range(0, len(texts), BATCH_SIZE):
                batch = texts[i : i + BATCH_SIZE]
                out.extend(await self._embed_batch(client, batch))
        return out

    async def _embed_batch(
        self, client: httpx.AsyncClient, batch: list[str]
    ) -> list[list[float]]:
        last: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch, "input_type": "document"},
                )
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda d: d["index"])
                vectors = [d["embedding"] for d in data]
                if vectors and len(vectors[0]) != self.dimensions:
                    raise ProviderError(
                        f"Voyage model '{self.model}' returned {len(vectors[0])} "
                        f"dimensions; the schema column expects {self.dimensions}."
                    )
                return vectors
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == MAX_RETRIES - 1:
                    break
                await _backoff(attempt)
        raise ProviderError("Voyage embedding failed.") from last


def get_embedder(settings: Settings) -> Embedder:
    """Select the embedder for the configured space.

    Startup validation (§12.2) already rejects `EMBED_SPACE=voyage` without a
    key, so this cannot silently return a broken embedder.
    """
    if settings.embed_space == "voyage":
        return VoyageEmbedder(settings)
    return OllamaEmbedder(settings)
