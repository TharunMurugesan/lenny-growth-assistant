/* Session history — design.md §Sidebar.
 *
 * Rename is inline in the row and delete confirms inline in the row. No modal,
 * and explicitly never a browser confirm() — the QA checklist tests for its
 * absence, because a native dialog is unstyleable, unaccessible to the app's
 * focus management, and blocks the whole tab. */

import { useEffect, useRef, useState } from 'react'
import { groupSessions } from '../hooks/useSessions.js'
import { LLMToggle } from './LLMToggle.jsx'

const THEME_LABEL = { system: 'System', light: 'Light', dark: 'Dark' }
const THEME_ICON = { system: '◐', light: '☀', dark: '☾' }

function Row({ session, active, onSelect, onRename, onDelete }) {
  const [mode, setMode] = useState('idle') // idle | menu | rename | confirm
  const [draft, setDraft] = useState(session.title)
  const inputRef = useRef(null)

  useEffect(() => {
    if (mode === 'rename') inputRef.current?.select()
  }, [mode])

  useEffect(() => setDraft(session.title), [session.title])

  const commit = () => {
    const next = draft.trim()
    if (next && next !== session.title) onRename(session.id, next)
    setMode('idle')
  }

  if (mode === 'rename') {
    return (
      <div className="srow srow--editing">
        <input
          ref={inputRef}
          className="srow__input"
          value={draft}
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') {
              setDraft(session.title)
              setMode('idle')
            }
          }}
          onBlur={commit}
          aria-label="Rename conversation"
        />
      </div>
    )
  }

  if (mode === 'confirm') {
    return (
      <div className="srow srow--confirm">
        <span className="srow__confirmtext">Delete?</span>
        <button
          type="button"
          className="btn-ghost btn-ghost--sm btn-ghost--danger"
          onClick={() => onDelete(session.id)}
        >
          Delete
        </button>
        <button
          type="button"
          className="btn-ghost btn-ghost--sm"
          onClick={() => setMode('idle')}
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <div className={`srow${active ? ' is-active' : ''}`}>
      <button type="button" className="srow__main" onClick={() => onSelect(session.id)}>
        <span className="srow__title">{session.title}</span>
      </button>

      <div className="srow__tools">
        <button
          type="button"
          className="btn-icon btn-icon--sm"
          onClick={() => setMode('rename')}
          aria-label={`Rename ${session.title}`}
          title="Rename"
        >
          ✎
        </button>
        <button
          type="button"
          className="btn-icon btn-icon--sm"
          onClick={() => setMode('confirm')}
          aria-label={`Delete ${session.title}`}
          title="Delete"
        >
          🗑
        </button>
      </div>
    </div>
  )
}

export function Sidebar({
  sessions,
  loading,
  activeId,
  onSelect,
  onNew,
  onRename,
  onDelete,
  collapsed,
  onToggleCollapse,
  provider,
  onProviderChange,
  health,
  theme,
  onCycleTheme,
}) {
  const groups = groupSessions(sessions)

  if (collapsed) {
    return (
      <div className="sidebar sidebar--collapsed">
        <button
          type="button"
          className="btn-icon"
          onClick={onToggleCollapse}
          aria-label="Expand sidebar"
          title="Expand sidebar (⌘B)"
        >
          ☰
        </button>
        <button type="button" className="btn-icon" onClick={onNew} aria-label="New chat" title="New chat (⌘K)">
          ＋
        </button>
      </div>
    )
  }

  return (
    <nav className="sidebar" aria-label="Conversation history">
      <div className="sidebar__brand">
        <span className="sidebar__mark" aria-hidden="true">
          ◆
        </span>
        <span className="sidebar__name">Lenny Growth Assistant</span>
      </div>

      <div className="sidebar__new">
        <button type="button" className="btn-primary" onClick={onNew}>
          ＋ New chat
        </button>
      </div>

      <div className="sidebar__list">
        {loading ? (
          <div className="shimmer-group" aria-label="Loading conversations">
            <div className="shimmer" />
            <div className="shimmer" />
            <div className="shimmer" />
          </div>
        ) : sessions.length === 0 ? (
          <p className="sidebar__empty">No conversations yet</p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="sgroup">
              <h2 className="sgroup__label">{group.label}</h2>
              {group.items.map((s) => (
                <Row
                  key={s.id}
                  session={s}
                  active={s.id === activeId}
                  onSelect={onSelect}
                  onRename={onRename}
                  onDelete={onDelete}
                />
              ))}
            </section>
          ))
        )}
      </div>

      <div className="sidebar__footer">
        <LLMToggle
          value={provider}
          onChange={onProviderChange}
          cloud={health.cloud}
          local={health.local}
          checking={health.checking}
        />

        <div className="sidebar__footrow">
          <button
            type="button"
            className="btn-ghost btn-ghost--sm"
            onClick={onCycleTheme}
            title={`Theme: ${THEME_LABEL[theme]} — click to change`}
          >
            {THEME_ICON[theme]} {THEME_LABEL[theme]}
          </button>
          <button
            type="button"
            className="btn-ghost btn-ghost--sm"
            onClick={onToggleCollapse}
            title="Collapse sidebar (⌘B)"
          >
            ⌄ Collapse
          </button>
        </div>
      </div>
    </nav>
  )
}
