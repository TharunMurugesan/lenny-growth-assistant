/* Conversation pane — design.md §State Coverage, §Streaming and Motion.
 *
 * Autoscroll follows the stream only while the user is within 80px of the
 * bottom. Scrolling up detaches and reveals a "Jump to latest" pill. Nothing
 * ever yanks the viewport away from something the user is reading — that is
 * the single most irritating failure a streaming UI can have. */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Message } from './Message.jsx'
import { EmptyState } from './EmptyState.jsx'
import { Composer } from './Composer.jsx'

const STICK_THRESHOLD_PX = 80

const WAIT_LABEL = {
  thinking: 'Thinking…',
  retrieving: 'Retrieving from transcripts…',
  warming: 'Warming up the local model…',
}

const WAIT_SUB = {
  warming: 'The first response after startup can take a minute.',
}

function Waiting({ stage, skill }) {
  return (
    <div className="waiting">
      {skill && <span className="badge">{skill}</span>}
      <div className="waiting__row">
        <span className="dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="waiting__label">{WAIT_LABEL[stage] || WAIT_LABEL.thinking}</span>
      </div>
      {WAIT_SUB[stage] && <p className="waiting__sub">{WAIT_SUB[stage]}</p>}
    </div>
  )
}

function ErrorCard({ error, onRetry, onSwitchProvider, otherProviderAvailable, otherProvider }) {
  const providerIssue =
    error.code === 'PROVIDER_UNAVAILABLE' ||
    error.code === 'PROVIDER_TIMEOUT' ||
    error.code === 'MODEL_NOT_FOUND' ||
    error.code === 'PROVIDER_ERROR'

  return (
    <div className="notice notice--danger" role="alert">
      <strong>{error.message}</strong>
      <div className="notice__actions">
        {error.retryable && onRetry && (
          <button type="button" className="btn-ghost btn-ghost--sm" onClick={onRetry}>
            ↻ Retry
          </button>
        )}
        {providerIssue && otherProviderAvailable && (
          <button type="button" className="btn-ghost btn-ghost--sm" onClick={onSwitchProvider}>
            Switch to {otherProvider === 'cloud' ? 'Cloud' : 'Local'}
          </button>
        )}
      </div>
    </div>
  )
}

export function ChatPane({
  messages,
  live,
  loading,
  onSend,
  onStop,
  onRegenerate,
  onOpenArtifact,
  composerValue,
  onComposerChange,
  health,
  provider,
  onProviderChange,
  onRetry,
}) {
  const scrollRef = useRef(null)
  const [stuck, setStuck] = useState(true)

  const isEmpty = messages.length === 0 && !live.streaming && !live.text && !live.meta

  // 'instant' rather than 'auto': `auto` defers to the computed CSS
  // scroll-behavior, which is exactly the trap that detached autoscroll.
  const scrollToBottom = useCallback((behavior = 'instant') => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior })
  }, [])

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    setStuck(distance <= STICK_THRESHOLD_PX)
  }, [])

  // useLayoutEffect so the scroll lands in the same frame the text paints,
  // rather than one frame late (which reads as a jitter during streaming).
  useLayoutEffect(() => {
    if (stuck) scrollToBottom()
  }, [messages, live.text, live.artifact?.content, stuck, scrollToBottom])

  useEffect(() => {
    scrollToBottom()
    setStuck(true)
  }, [messages.length === 0, scrollToBottom])

  const otherProvider = provider === 'cloud' ? 'local' : 'cloud'
  const otherAvailable = health[otherProvider]?.available

  const providerBlocked = !health.checking && !health.anyAvailable

  return (
    <main className="chat">
      <div className="chat__scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat__column">
          {loading ? (
            <div className="skeleton-group" aria-label="Loading conversation">
              <div className="skeleton" style={{ width: '60%' }} />
              <div className="skeleton" style={{ width: '85%' }} />
            </div>
          ) : isEmpty ? (
            <EmptyState
              onPick={(prompt, skill) => onSend(prompt, skill)}
              chunks={health.chunks}
              dbConnected={health.dbConnected}
            />
          ) : (
            <div className="chat__log" role="log" aria-live="polite" aria-relevant="additions">
              {messages.map((m) => (
                <Message
                  key={m.id}
                  message={m}
                  onOpenArtifact={() => onOpenArtifact(m.artifact)}
                  onRegenerate={m.role === 'assistant' ? () => onRegenerate(m) : undefined}
                />
              ))}

              {/* The in-flight turn. Rendered separately from persisted
                  history so the transcript above it never re-renders per
                  token. */}
              {(live.streaming || live.text || live.artifact) && (
                <>
                  {!live.text && !live.artifact && (
                    <Waiting stage={live.waitStage} skill={live.meta?.skill && SKILL_TEXT[live.meta.skill]} />
                  )}
                  {(live.text || live.artifact) && (
                    <Message
                      message={{
                        id: 'live',
                        role: 'assistant',
                        content: live.text,
                        skill: live.meta?.skill,
                        provider: live.meta?.provider,
                        model: live.meta?.model,
                        citations: live.citations,
                        word_count: live.usage?.word_count,
                        artifact: live.artifact,
                        finish_reason: live.finishReason,
                      }}
                      streaming={live.streaming}
                      onOpenArtifact={() => onOpenArtifact(live.artifact)}
                    />
                  )}
                </>
              )}

              {live.error && (
                <ErrorCard
                  error={live.error}
                  onRetry={onRetry}
                  onSwitchProvider={() => onProviderChange(otherProvider)}
                  otherProviderAvailable={otherAvailable}
                  otherProvider={otherProvider}
                />
              )}
            </div>
          )}
        </div>
      </div>

      {!stuck && (
        <button
          type="button"
          className="jump"
          onClick={() => {
            scrollToBottom('smooth')
            setStuck(true)
          }}
        >
          ↓ Jump to latest
        </button>
      )}

      <div className="chat__footer">
        <div className="chat__column">
          {health.unreachable && (
            <div className="notice notice--warning notice--inline" role="alert">
              Cannot reach the server. Check that the backend is running on port 8000.
            </div>
          )}
          {providerBlocked && !health.unreachable && (
            <div className="notice notice--warning notice--inline" role="alert">
              No LLM provider is available. Set <code>ANTHROPIC_API_KEY</code> for Cloud, or start
              Ollama for Local.
            </div>
          )}

          <Composer
            value={composerValue}
            onChange={onComposerChange}
            onSend={(text) => onSend(text, null)}
            onStop={onStop}
            streaming={live.streaming}
            disabled={providerBlocked || health.unreachable}
            placeholder={
              providerBlocked
                ? 'No provider available — configure one to start a conversation.'
                : undefined
            }
          />
        </div>
      </div>
    </main>
  )
}

const SKILL_TEXT = {
  qa: 'Skill A · Grounded Q&A',
  ship30: 'Skill B · Ship30for30',
  artifact: 'Skill C · Artifact',
  meta: 'About this assistant',
}
