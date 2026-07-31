/* Session list state — design.md §Sidebar.
 *
 * Optimistic where it is safe to be: a new chat appears instantly as
 * "New chat" and is retitled when the first response completes, because
 * waiting on a round-trip to show a row the user just asked for feels broken.
 * Deletes are optimistic too, and roll back on failure. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

export function useSessions() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true)
    try {
      const data = await api.listSessions(100)
      if (!mounted.current) return
      setSessions(data.sessions || [])
      setError(null)
    } catch (err) {
      if (mounted.current) setError(err)
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const create = useCallback(async () => {
    const created = await api.createSession()
    if (mounted.current) setSessions((prev) => [created, ...prev])
    return created
  }, [])

  const rename = useCallback(async (id, title) => {
    const previous = { id, title }
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)))
    try {
      const updated = await api.renameSession(id, title)
      if (mounted.current) {
        setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, ...updated } : s)))
      }
    } catch (err) {
      // Roll back rather than leaving the sidebar showing a name the server
      // never accepted.
      if (mounted.current) {
        setSessions((prev) =>
          prev.map((s) => (s.id === previous.id ? { ...s, title: s.title } : s))
        )
        refresh({ quiet: true })
      }
      throw err
    }
  }, [refresh])

  const remove = useCallback(async (id) => {
    const snapshot = sessions
    setSessions((prev) => prev.filter((s) => s.id !== id))
    try {
      await api.deleteSession(id)
    } catch (err) {
      if (mounted.current) setSessions(snapshot)
      throw err
    }
  }, [sessions])

  /** Merge server truth for one session without refetching the whole list. */
  const patch = useCallback((id, fields) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, ...fields } : s)))
  }, [])

  return { sessions, loading, error, refresh, create, rename, remove, patch }
}

/* Grouping for the sidebar. Empty groups are not rendered — a "Previous 30
 * days" header above nothing is chrome that teaches the user nothing. */
export function groupSessions(sessions) {
  const now = Date.now()
  const day = 86_400_000
  const groups = [
    { label: 'Today', items: [] },
    { label: 'Previous 7 days', items: [] },
    { label: 'Previous 30 days', items: [] },
    { label: 'Older', items: [] },
  ]

  for (const session of sessions) {
    const age = now - new Date(session.updated_at).getTime()
    if (age < day) groups[0].items.push(session)
    else if (age < 7 * day) groups[1].items.push(session)
    else if (age < 30 * day) groups[2].items.push(session)
    else groups[3].items.push(session)
  }

  return groups.filter((g) => g.items.length > 0)
}
