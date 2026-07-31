"""Local provider — Ollama over HTTP.

Ollama streams newline-delimited JSON rather than typed events, so the
normalization to plain text deltas happens here (§11.1). Nothing above `llm/`
should ever see an Ollama-shaped payload.

Timeouts are deliberately asymmetric with the cloud provider (§11.3): a dead
daemon should fail in 5 seconds, but a cold model load legitimately takes 90.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx

from app.config import Settings
from app.llm.base import LOCAL_TIMEOUTS, Msg, StreamResult, Usage
from app.utils.errors import ModelNotFound, ProviderError, ProviderTimeout

log = logging.getLogger(__name__)


class OllamaProvider:
    name: Literal["cloud", "local"] = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.chat_model = settings.ollama_chat_model
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.timeouts = LOCAL_TIMEOUTS
        self.num_ctx = settings.ollama_num_ctx

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.timeouts.connect,
            read=self.timeouts.first_token,
            write=self.timeouts.connect,
            pool=self.timeouts.connect,
        )

    @staticmethod
    def _translate(exc: Exception, base_url: str) -> Exception:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return ProviderError(
                f"Ollama is not reachable at {base_url}. Start it with: ollama serve",
                detail={"provider": "local"},
            )
        if isinstance(exc, (httpx.ReadTimeout, httpx.PoolTimeout, asyncio.TimeoutError)):
            return ProviderTimeout(
                "The local model did not respond in time. It may still be loading.",
                detail={"provider": "local"},
            )
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            return ModelNotFound(
                "The configured local model is not pulled.",
                detail={"provider": "local"},
            )
        return ProviderError("The local model call failed.", detail={"provider": "local"})

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.timeouts.backoff[min(attempt, len(self.timeouts.backoff) - 1)]
        await asyncio.sleep(base + random.uniform(0, 0.5))

    # --- classification -------------------------------------------------

    async def classify(
        self, system: str, user: str, schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        """Ollama's structured-output equivalent is `format: <json schema>`."""
        payload = {
            "model": self.chat_model,
            "stream": False,
            "format": schema_hint,
            "options": {"temperature": 0, "num_predict": 128},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError("The local classifier returned unreadable output.") from exc
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, self.settings.ollama_base_url) from exc

    # --- streaming ------------------------------------------------------

    async def stream_chat(
        self,
        system: str,
        messages: list[Msg],
        *,
        temperature: float,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.chat_model,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
            "messages": [{"role": "system", "content": system}]
            + [m.as_dict() for m in messages],
        }

        for attempt in range(self.timeouts.retries + 1):
            emitted = False
            try:
                timeout = httpx.Timeout(
                    connect=self.timeouts.connect,
                    read=self.timeouts.idle,  # gap between deltas once streaming
                    write=self.timeouts.connect,
                    pool=self.timeouts.connect,
                )
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST", f"{self.base_url}/api/chat", json=payload
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue  # tolerate a partial line rather than dying

                            chunk = event.get("message", {}).get("content", "")
                            if chunk:
                                emitted = True
                                yield chunk

                            if event.get("done"):
                                result.usage = Usage(
                                    input_tokens=event.get("prompt_eval_count", 0) or 0,
                                    output_tokens=event.get("eval_count", 0) or 0,
                                )
                                reason = event.get("done_reason", "stop")
                                result.finish_reason = (
                                    "max_tokens" if reason == "length" else "stop"
                                )
                return
            except Exception as exc:  # noqa: BLE001
                # Same rule as cloud: never restart a stream that already
                # delivered text to the user.
                if emitted or attempt == self.timeouts.retries:
                    raise self._translate(exc, self.settings.ollama_base_url) from exc
                log.info(
                    "retrying local stream before first token",
                    extra={"attempt": attempt + 1, "error": type(exc).__name__},
                )
                await self._sleep_backoff(attempt)

    # --- non-streaming --------------------------------------------------

    async def complete(
        self, system: str, messages: list[Msg], *, temperature: float, max_tokens: int
    ) -> str:
        payload = {
            "model": self.chat_model,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": self.num_ctx,
            },
            "messages": [{"role": "system", "content": system}]
            + [m.as_dict() for m in messages],
        }
        try:
            timeout = httpx.Timeout(
                connect=self.timeouts.connect,
                read=self.timeouts.total,
                write=self.timeouts.connect,
                pool=self.timeouts.connect,
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                return response.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc, self.settings.ollama_base_url) from exc
