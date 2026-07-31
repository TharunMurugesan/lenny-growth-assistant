"""Provider protocol and shared types — architecture.md §11.1.

One protocol, two implementations. Nothing above `llm/` knows which is active:
`stream_chat` yields plain text deltas, and provider-specific event shapes —
Anthropic's typed stream events, Ollama's newline-delimited JSON — are
normalized inside each implementation. The orchestrator and the artifact parser
therefore have exactly one input format to handle.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Msg:
    """One conversation turn, provider-agnostic."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Usage:
    """Token accounting, normalized across providers."""

    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass
class StreamResult:
    """Terminal state of a stream, filled in by the provider as it finishes."""

    usage: Usage
    finish_reason: str = "stop"


# Timeout/retry policy per architecture.md §11.3. Held as data rather than
# scattered literals so the two providers stay comparable at a glance.
@dataclass(frozen=True)
class TimeoutPolicy:
    connect: float
    first_token: float
    idle: float
    total: float
    retries: int
    backoff: tuple[float, ...]


CLOUD_TIMEOUTS = TimeoutPolicy(
    connect=10.0, first_token=30.0, idle=60.0, total=120.0, retries=2, backoff=(1.0, 4.0)
)
LOCAL_TIMEOUTS = TimeoutPolicy(
    # A dead local daemon should fail instantly; a cold model load can take a
    # minute or more, hence the very different first_token budget.
    connect=5.0, first_token=90.0, idle=120.0, total=300.0, retries=1, backoff=(2.0,)
)


@runtime_checkable
class LLMProvider(Protocol):
    """What the agent layer is allowed to assume about a provider."""

    name: Literal["cloud", "local"]
    chat_model: str

    async def classify(self, system: str, user: str, schema_hint: dict[str, Any]) -> dict[str, Any]:
        """Return a parsed JSON object. Raises on unrecoverable failure."""
        ...

    def stream_chat(
        self,
        system: str,
        messages: list[Msg],
        *,
        temperature: float,
        max_tokens: int,
        result: StreamResult,
    ) -> AsyncIterator[str]:
        """Yield plain text deltas. Fills `result` as the stream terminates."""
        ...

    async def complete(
        self, system: str, messages: list[Msg], *, temperature: float, max_tokens: int
    ) -> str:
        """Non-streaming completion. Used by the Skill B length-repair pass."""
        ...
