/* SSE reader for `POST /api/chat` — architecture.md §6.
 *
 * `EventSource` is not usable here: it is GET-only and cannot send the
 * `X-Client-Key` header or a JSON body. So this reads the response body as a
 * `ReadableStream` and parses the SSE framing itself.
 *
 * The framing has the same hazard as the artifact parser on the server: a
 * network chunk boundary can fall anywhere, including mid-frame or even
 * mid-`data:` line. Everything is therefore accumulated in a buffer and only
 * complete `\n\n`-terminated frames are dispatched — never a partial one.
 *
 * A 4xx arrives as ordinary JSON *before* the stream opens (§5.7), so those
 * are surfaced as ApiError rather than as a stream event. That distinction is
 * the whole reason the backend refuses to deliver validation failures as SSE.
 */

import { ApiError, BASE, headers } from './client.js'

const FRAME_SEPARATOR = /\r?\n\r?\n/

function parseFrame(raw) {
  let event = 'message'
  const dataLines = []

  for (const line of raw.split(/\r?\n/)) {
    // A line starting with ':' is a comment — the heartbeat that keeps
    // intermediaries from reaping an idle connection. Not an event.
    if (!line || line.startsWith(':')) continue

    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''))
    }
  }

  if (!dataLines.length) return null

  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null // malformed payload — drop the frame, never kill the stream
  }
}

/**
 * Open a chat stream.
 *
 * @param {object}   body     `{ session_id, message, llm_provider, skill_override }`
 * @param {object}   handlers Keyed by SSE event name. Unknown events are
 *                            ignored by design — §6 requires clients to treat
 *                            unrecognised names as no-ops for forward
 *                            compatibility.
 * @param {AbortSignal} signal Aborting is how the composer's Stop button
 *                            works; the backend sees the disconnect and
 *                            persists the partial message.
 */
export async function streamChat(body, handlers = {}, signal) {
  let response
  try {
    response = await fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause
    throw new ApiError('NETWORK_ERROR', 'Could not reach the server.', { retryable: true })
  }

  if (!response.ok) {
    // Pre-stream failure: a real JSON envelope, not an SSE frame.
    let payload = null
    try {
      payload = await response.json()
    } catch {
      /* ignore */
    }
    const err = payload?.error
    throw new ApiError(
      err?.code || 'HTTP_ERROR',
      err?.message || `Request failed (${response.status}).`,
      {
        status: response.status,
        retryable: err?.retryable ?? response.status >= 500,
        detail: err?.detail,
        requestId: err?.request_id,
      }
    )
  }

  if (!response.body) {
    throw new ApiError('STREAM_ERROR', 'The server returned no stream.', { retryable: true })
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawTerminal = false

  const dispatch = (frame) => {
    if (!frame) return
    if (frame.event === 'done' || frame.event === 'error') sawTerminal = true
    handlers[frame.event]?.(frame.data)
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      // stream:true matters — a multi-byte UTF-8 character can be split
      // across chunk boundaries and would otherwise decode as garbage.
      buffer += decoder.decode(value, { stream: true })

      let match
      while ((match = FRAME_SEPARATOR.exec(buffer))) {
        const raw = buffer.slice(0, match.index)
        buffer = buffer.slice(match.index + match[0].length)
        dispatch(parseFrame(raw))
      }
    }

    buffer += decoder.decode()
    if (buffer.trim()) dispatch(parseFrame(buffer))
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* already released */
    }
  }

  // §6 client contract: treat the stream as failed if it closes without a
  // terminal event. Silence is not success.
  if (!sawTerminal && !signal?.aborted) {
    handlers.error?.({
      code: 'STREAM_TRUNCATED',
      message: 'The connection closed before the response finished.',
      retryable: true,
    })
  }
}
