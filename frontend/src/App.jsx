/* Application shell — wires the three zones together.
 *
 * Zone 3 is conditional (design.md §Layout System): the artifact pane does not
 * exist until a message contains an artifact, never appears empty, and closing
 * it does not destroy anything — the chip on the message reopens it. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api/client.js'
import { useChatStream } from './hooks/useChatStream.js'
import { useHealth } from './hooks/useHealth.js'
import { useSessions } from './hooks/useSessions.js'
import { usePersistent, useTheme } from './hooks/usePreferences.js'
import { Sidebar } from './components/Sidebar.jsx'
import { ChatPane } from './components/ChatPane.jsx'
import { ArtifactViewer } from './components/ArtifactViewer.jsx'

export default function App() {
  const health = useHealth()
  const sessions = useSessions()
  const theme = useTheme()

  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [composer, setComposer] = useState('')
  const [openArtifact, setOpenArtifact] = useState(null)
  // Id of an artifact the user closed. Tracked separately from `openArtifact`
  // because during a stream the pane is fed by `stream.artifact`, so clearing
  // `openArtifact` alone would not close it.
  const [dismissed, setDismissed] = useState(null)
  const [collapsed, setCollapsed] = usePersistent('lga:sidebar-collapsed', false)
  const [paneWidth, setPaneWidth] = usePersistent('lga:artifact-width', 44)
  const [provider, setProvider] = usePersistent('lga:provider', 'cloud')

  const lastSent = useRef(null)

  const reloadMessages = useCallback(async (sessionId) => {
    if (!sessionId) return
    try {
      const data = await api.getMessages(sessionId)
      setMessages(data.messages || [])
    } catch {
      /* surfaced by the health banner */
    }
  }, [])

  const stream = useChatStream({
    onComplete: async (final) => {
      // Refetch so what the user sees is the persisted row — the same bytes
      // history will replay — rather than the in-memory approximation the
      // stream built.
      //
      // Then *reset the stream*. Without this the turn renders twice: once
      // from live state and once from the refetched history, because both are
      // in the transcript simultaneously. The live artifact is promoted into
      // `openArtifact` first so the pane keeps showing it across the handover.
      await reloadMessages(activeId)
      if (final?.artifact?.content) setOpenArtifact(final.artifact)
      stream.reset()
      sessions.refresh({ quiet: true })
    },
  })

  // Follow the toggle onto whichever provider is actually available, so a
  // stored preference for a provider that has since gone away does not leave
  // the composer permanently blocked.
  useEffect(() => {
    if (health.checking) return
    if (!health[provider]?.available && health.anyAvailable) {
      setProvider(health.cloud.available ? 'cloud' : 'local')
    }
  }, [health.checking, health.cloud.available, health.local.available, provider])

  const selectSession = useCallback(
    async (id) => {
      setActiveId(id)
      setOpenArtifact(null)
      stream.reset()
      setLoadingMessages(true)
      try {
        const data = await api.getMessages(id)
        setMessages(data.messages || [])
      } catch {
        setMessages([])
      } finally {
        setLoadingMessages(false)
      }
    },
    [stream]
  )

  const newChat = useCallback(async () => {
    stream.reset()
    setOpenArtifact(null)
    setMessages([])
    setComposer('')
    try {
      const created = await sessions.create()
      setActiveId(created.id)
    } catch {
      /* surfaced by the banner */
    }
  }, [sessions, stream])

  const send = useCallback(
    async (text, skillOverride) => {
      if (!text?.trim()) return

      let sessionId = activeId
      if (!sessionId) {
        const created = await sessions.create()
        sessionId = created.id
        setActiveId(sessionId)
      }

      // Optimistic user turn — the message appears the instant it is sent,
      // and is replaced by the persisted row on completion.
      setMessages((prev) => [
        ...prev,
        { id: `local-${Date.now()}`, role: 'user', content: text, created_at: new Date().toISOString() },
      ])
      setComposer('')
      lastSent.current = { text, skillOverride, sessionId }

      await stream.send({ sessionId, message: text, provider, skillOverride })
    },
    [activeId, provider, sessions, stream]
  )

  const retry = useCallback(() => {
    const last = lastSent.current
    if (!last) return
    stream.send({
      sessionId: last.sessionId,
      message: last.text,
      provider,
      skillOverride: last.skillOverride,
    })
  }, [provider, stream])

  const regenerate = useCallback(
    (assistantMessage) => {
      const index = messages.findIndex((m) => m.id === assistantMessage.id)
      const priorUser = [...messages.slice(0, index)].reverse().find((m) => m.role === 'user')
      if (priorUser) send(priorUser.content, null)
    },
    [messages, send]
  )

  // The pane shows the live artifact while one is streaming, otherwise
  // whatever the user last opened from a chip. `dismissed` tracks an artifact
  // the user closed: without it, closing the live pane does nothing, because
  // `openArtifact` is not what is being displayed during a stream.
  const artifact = useMemo(() => {
    const candidate = stream.artifact || openArtifact
    if (!candidate) return null
    return candidate.id && candidate.id === dismissed ? null : candidate
  }, [stream.artifact, openArtifact, dismissed])

  const closeArtifact = useCallback(() => {
    // Dismiss by id rather than clearing state — §Layout System requires the
    // artifact survive being closed so its chip can reopen it.
    if (stream.artifact?.id) setDismissed(stream.artifact.id)
    setOpenArtifact(null)
  }, [stream.artifact?.id])

  useEffect(() => {
    if (stream.artifact) {
      setOpenArtifact(null)
      setDismissed(null) // a new artifact is never born dismissed
    }
  }, [stream.artifact?.id])

  // Keyboard map — design.md §Accessibility.
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        newChat()
      } else if (mod && e.key.toLowerCase() === 'b') {
        e.preventDefault()
        setCollapsed((v) => !v)
      } else if (mod && e.key === '/') {
        e.preventDefault()
        document.getElementById('composer-input')?.focus()
      } else if (e.key === 'Escape' && artifact) {
        closeArtifact()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [newChat, setCollapsed, artifact, closeArtifact])

  const live = useMemo(
    () => ({
      streaming: stream.streaming,
      waitStage: stream.waitStage,
      text: stream.text,
      meta: stream.meta,
      artifact: stream.artifact,
      citations: stream.citations,
      usage: stream.usage,
      error: stream.error,
      finishReason: stream.finishReason,
    }),
    [stream]
  )

  return (
    <div className={`app${artifact ? ' app--artifact' : ''}`}>
      <Sidebar
        sessions={sessions.sessions}
        loading={sessions.loading}
        activeId={activeId}
        onSelect={selectSession}
        onNew={newChat}
        onRename={sessions.rename}
        onDelete={async (id) => {
          await sessions.remove(id)
          if (id === activeId) {
            setActiveId(null)
            setMessages([])
            stream.reset()
          }
        }}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        provider={provider}
        onProviderChange={setProvider}
        health={health}
        theme={theme.preference}
        onCycleTheme={theme.cycle}
      />

      <ChatPane
        messages={messages}
        live={live}
        loading={loadingMessages}
        onSend={send}
        onStop={stream.stop}
        onRegenerate={regenerate}
        onOpenArtifact={(a) => {
          if (!a) return
          setDismissed(null)
          setOpenArtifact(a)
        }}
        composerValue={composer}
        onComposerChange={setComposer}
        health={health}
        provider={provider}
        onProviderChange={setProvider}
        onRetry={retry}
      />

      {artifact && (
        <ArtifactViewer
          artifact={artifact}
          width={paneWidth}
          onResize={setPaneWidth}
          onClose={closeArtifact}
        />
      )}
    </div>
  )
}
