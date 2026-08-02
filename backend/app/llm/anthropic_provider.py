"""Cloud provider — the Anthropic SDK.

Deviation from architecture.md §7.3 worth stating plainly: the spec asks for a
prefilled `{` on the classifier so the response is JSON from the first token.
**Assistant-turn prefill returns a 400 on Sonnet 4.6 and the whole 4.6+ family.**
It happens to still work on the configured Haiku router model, but building on
it would mean the app breaks the moment someone points `ANTHROPIC_ROUTER_MODEL`
at Sonnet. Structured outputs (`output_config.format`) are the supported
replacement and give a stronger guarantee than a prefill ever did — the schema
is enforced rather than merely encouraged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from typing import Any, Literal

import anthropic

from app.config import Settings
from app.llm.base import CLOUD_TIMEOUTS, Msg, StreamResult, Usage
from app.utils.errors import ProviderError, ProviderTimeout, RateLimited

log = logging.getLogger(__name__)


class AnthropicProvider:
    name: Literal["cloud", "local"] = "cloud"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.chat_model = settings.anthropic_chat_model
        self.router_model = settings.anthropic_router_model
        self.timeouts = CLOUD_TIMEOUTS
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=float(settings.cloud_timeout_seconds),
            max_retries=0,  # retries are handled here so they can stop at first token
        )

    # --- error mapping --------------------------------------------------

    @staticmethod
    def _translate(exc: Exception) -> Exception:
        """Map SDK exceptions onto the §12.1 taxonomy.

        Nothing from the provider's response body is passed through — §13
        requires error messages be constructed for display.
        """
        if isinstance(exc, anthropic.AuthenticationError):
            return ProviderError(
                "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY.",
                detail={"provider": "cloud"},
            )
        if isinstance(exc, anthropic.RateLimitError):
            return RateLimited(
                "Anthropic is rate limiting this key. Try again shortly.",
                detail={"provider": "cloud"},
            )
        if isinstance(exc, (anthropic.APITimeoutError, asyncio.TimeoutError)):
            return ProviderTimeout(
                "The Anthropic API did not respond in time.", detail={"provider": "cloud"}
            )
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderError(
                f"Anthropic returned an error (HTTP {exc.status_code}).",
                detail={"provider": "cloud"},
            )
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError(
                "Could not reach the Anthropic API. Check network connectivity.",
                detail={"provider": "cloud"},
            )
        return ProviderError("The Anthropic API call failed.", detail={"provider": "cloud"})

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        """§11.3: retries apply to connection errors, 429, and 5xx only."""
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return True
        if isinstance(exc, anthropic.RateLimitError):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return exc.status_code >= 500
        return False

    async def _sleep_backoff(self, attempt: int) -> None:
        base = self.timeouts.backoff[min(attempt, len(self.timeouts.backoff) - 1)]
        await asyncio.sleep(base + random.uniform(0, 0.5))  # jitter avoids retry storms

    # --- classification -------------------------------------------------

    async def classify(
        self, system: str, user: str, schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        """Structured-output classification on the small, fast router model."""
        last: Exception | None = None
        for attempt in range(self.timeouts.retries + 1):
            try:
                response = await self._client.messages.create(
                    model=self.router_model,
                    # §7.3 specifies 128, sized for a terse prefilled reply.
                    # The structured-output schema also carries `search_query`
                    # and `rationale`, and at 128 the JSON object was
                    # occasionally truncated before its closing brace — which
                    # surfaced as an unparseable-classifier fallback to qa on
                    # roughly 1 message in 16. Cheap headroom on a Haiku call.
                    max_tokens=400,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_config={"format": {"type": "json_schema", "schema": schema_hint}},
                )
                text = next(
                    (b.text for b in response.content if getattr(b, "type", "") == "text"), ""
                )
                return json.loads(text)
            except json.JSONDecodeError as exc:
                # Not retryable — the model answered, just not usably. The
                # router treats this as low confidence and defaults to qa.
                raise ProviderError("The classifier returned unreadable output.") from exc
            except Exception as exc:  # noqa: BLE001 - translated below
                last = exc
                if not self._retryable(exc) or attempt == self.timeouts.retries:
                    raise self._translate(exc) from exc
                await self._sleep_backoff(attempt)
        raise self._translate(last or RuntimeError("classify failed"))

    # --- streaming ------------------------------------------------------

    async def stream_chat(
        self,
        system: str,
        messages: list[Msg],
        *,
        temperature: float,
        max_tokens: int,
        result: StreamResult,
        prefill: str = "",
    ) -> AsyncIterator[str]:
        """Yield text deltas.

        §11.3: **retries stop once the first token has been emitted.**
        Restarting mid-stream would duplicate text the user has already read,
        so after first token a failure becomes terminal.
        """
        payload = [m.as_dict() for m in messages]
        # Anthropic prefills the same way — a trailing assistant turn is
        # continued rather than answered. Sonnet follows the artifact
        # instruction unaided, so this stays unused in practice; it exists so
        # both providers honour one interface instead of one growing a special
        # case the orchestrator has to know about.
        if prefill:
            payload.append({"role": "assistant", "content": prefill})

        for attempt in range(self.timeouts.retries + 1):
            emitted = False
            try:
                async with self._client.messages.stream(
                    model=self.chat_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=payload,
                ) as stream:
                    async for chunk in stream.text_stream:
                        if chunk:
                            emitted = True
                            yield chunk

                    final = await stream.get_final_message()
                    result.usage = Usage(
                        input_tokens=final.usage.input_tokens,
                        output_tokens=final.usage.output_tokens,
                    )
                    result.finish_reason = (
                        "max_tokens" if final.stop_reason == "max_tokens" else "stop"
                    )
                return
            except Exception as exc:  # noqa: BLE001 - translated below
                if emitted or not self._retryable(exc) or attempt == self.timeouts.retries:
                    raise self._translate(exc) from exc
                log.info(
                    "retrying cloud stream before first token",
                    extra={"attempt": attempt + 1, "error": type(exc).__name__},
                )
                await self._sleep_backoff(attempt)

    # --- non-streaming --------------------------------------------------

    async def complete(
        self, system: str, messages: list[Msg], *, temperature: float, max_tokens: int
    ) -> str:
        try:
            response = await self._client.messages.create(
                model=self.chat_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[m.as_dict() for m in messages],
            )
            return "".join(
                b.text for b in response.content if getattr(b, "type", "") == "text"
            )
        except Exception as exc:  # noqa: BLE001
            raise self._translate(exc) from exc
