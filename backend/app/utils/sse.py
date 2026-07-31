"""Server-Sent Events framing — architecture.md §6.

Every frame is `event: <name>` plus a single-line JSON `data:` payload. The
single-line rule is load-bearing: a raw newline inside `data:` would be read by
the client as a frame boundary, so payloads are serialized without indentation
and with newlines escaped by the JSON encoder.
"""

from __future__ import annotations

import json
from typing import Any

HEARTBEAT_INTERVAL_SECONDS = 15.0

# The headers that actually matter for streaming. `X-Accel-Buffering` is what
# nginx needs in order to stop buffering the response; without it the stream
# arrives as one lump at the end and every token event is pointless.
SSE_HEADERS = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def frame(event: str, data: dict[str, Any]) -> str:
    """Serialize one SSE frame."""
    payload = json.dumps(data, separators=(",", ":"), default=str, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def heartbeat() -> str:
    """A bare SSE comment. Keeps intermediaries from reaping an idle stream."""
    return ": keep-alive\n\n"
