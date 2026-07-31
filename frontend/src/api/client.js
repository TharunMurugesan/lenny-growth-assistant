/* REST client for the session endpoints — architecture.md §5.
 *
 * Every request carries the anonymous `X-Client-Key`. The backend upserts a
 * user against it and echoes the resolved key back in the response header, so
 * a browser that arrives without one adopts whatever the server provisioned
 * instead of orphaning a session per request. */

const BASE = import.meta.env.VITE_API_BASE_URL || '/api'
const CLIENT_KEY_STORAGE = 'lga:client-key'
const CLIENT_KEY_HEADER = 'X-Client-Key'

function makeKey() {
  const bytes = new Uint8Array(24)
  crypto.getRandomValues(bytes)
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

export function clientKey() {
  let key = null
  try {
    key = localStorage.getItem(CLIENT_KEY_STORAGE)
  } catch {
    /* private mode — fall through to an in-memory key for this tab */
  }
  if (!key) {
    key = makeKey()
    try {
      localStorage.setItem(CLIENT_KEY_STORAGE, key)
    } catch {
      /* ignore */
    }
  }
  return key
}

/** An error carrying the §5.8 envelope, so callers can switch on `code`. */
export class ApiError extends Error {
  constructor(code, message, { status, retryable = false, detail = {}, requestId } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.retryable = retryable
    this.detail = detail
    this.requestId = requestId
  }
}

export function headers(extra = {}) {
  return { [CLIENT_KEY_HEADER]: clientKey(), ...extra }
}

async function toApiError(response) {
  let body = null
  try {
    body = await response.json()
  } catch {
    /* non-JSON error body */
  }
  const err = body?.error
  if (err) {
    return new ApiError(err.code, err.message, {
      status: response.status,
      retryable: err.retryable,
      detail: err.detail,
      requestId: err.request_id,
    })
  }
  return new ApiError('HTTP_ERROR', `Request failed (${response.status}).`, {
    status: response.status,
    retryable: response.status >= 500,
  })
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      ...options,
      headers: headers({
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      }),
    })
  } catch (cause) {
    // fetch only rejects on network failure, never on an HTTP error status.
    throw new ApiError('NETWORK_ERROR', 'Could not reach the server.', {
      retryable: true,
    })
  }

  // Adopt a server-provisioned key so the next request resolves the same user.
  const echoed = response.headers.get(CLIENT_KEY_HEADER)
  if (echoed) {
    try {
      localStorage.setItem(CLIENT_KEY_STORAGE, echoed)
    } catch {
      /* ignore */
    }
  }

  if (!response.ok) throw await toApiError(response)
  if (response.status === 204) return null
  return response.json()
}

export const api = {
  health: () => request('/health'),

  listSessions: (limit = 50, cursor = null) =>
    request(`/sessions?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),

  createSession: (title) =>
    request('/sessions', {
      method: 'POST',
      body: JSON.stringify(title ? { title } : {}),
    }),

  getMessages: (sessionId) => request(`/sessions/${sessionId}/messages`),

  renameSession: (sessionId, title) =>
    request(`/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title }),
    }),

  deleteSession: (sessionId) => request(`/sessions/${sessionId}`, { method: 'DELETE' }),
}

export { BASE, CLIENT_KEY_HEADER }
