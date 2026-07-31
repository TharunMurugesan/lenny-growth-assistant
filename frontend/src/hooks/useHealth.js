/* Provider availability and corpus state — design.md §LLM toggle.
 *
 * The toggle disables what does not work rather than hiding it, and states the
 * reason. That requires real health data, not an assumption, so this polls
 * `/api/health` and is the single source for both toggle halves and the
 * "vector store is empty" first-run notice. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

const POLL_MS = 30_000

export function useHealth() {
  const [health, setHealth] = useState(null)
  const [checking, setChecking] = useState(true)
  const [unreachable, setUnreachable] = useState(false)
  const mounted = useRef(true)

  const check = useCallback(async () => {
    try {
      const data = await api.health()
      if (!mounted.current) return
      setHealth(data)
      setUnreachable(false)
    } catch (err) {
      if (!mounted.current) return
      // A 503 still carries a body describing *why* — that is more useful than
      // treating it as unreachable.
      if (err.status === 503 && err.detail) setHealth(null)
      setUnreachable(true)
    } finally {
      if (mounted.current) setChecking(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    check()
    const id = setInterval(check, POLL_MS)
    return () => {
      mounted.current = false
      clearInterval(id)
    }
  }, [check])

  const providers = health?.providers || {}
  const cloud = providers.cloud || { available: false, model: '', reason: null }
  const local = providers.local || { available: false, model: '', reason: null }

  return {
    health,
    checking,
    unreachable,
    check,
    cloud,
    local,
    anyAvailable: cloud.available || local.available,
    chunks: health?.database?.chunks?.total ?? null,
    embedSpace: health?.embed_space ?? null,
    dbConnected: health?.database?.connected ?? false,
  }
}
