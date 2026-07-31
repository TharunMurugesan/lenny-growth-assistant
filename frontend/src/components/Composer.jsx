/* Composer — design.md §Composer.
 *
 * Two rules that matter more than they look:
 *
 *  - The field never locks while a request is in flight. A user who thinks of
 *    their follow-up mid-stream should be able to type it.
 *  - While streaming, Send becomes Stop. Aborting the fetch drops the
 *    connection, the backend detects the disconnect, and the partial message
 *    is persisted with finish_reason=client_disconnect — so stopping keeps
 *    what was already written instead of discarding it. */

import { useEffect, useRef } from 'react'

const MAX_HEIGHT = 200
const MAX_CHARS = 8000

export function Composer({ value, onChange, onSend, onStop, streaming, disabled, placeholder }) {
  const ref = useRef(null)

  // Auto-grow to 200px, then scroll. A long prompt stays editable without
  // swallowing the transcript above it.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const submit = () => {
    const text = value.trim()
    if (!text || streaming || disabled) return
    onSend(text)
  }

  const onKeyDown = (e) => {
    // Enter sends; Shift+Enter is a newline. Cmd/Ctrl+Enter also sends, since
    // that is muscle memory from every other composer.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  const over = value.length > MAX_CHARS

  return (
    <div className="composer-wrap">
      <div className={`composer${disabled ? ' is-disabled' : ''}`}>
        <textarea
          ref={ref}
          className="composer__input"
          id="composer-input"
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder || 'Ask about growth, retention, PMF…'}
          disabled={disabled}
          aria-label="Message"
        />

        {streaming ? (
          <button
            type="button"
            className="composer__send composer__send--stop"
            onClick={onStop}
            aria-label="Stop generating"
            title="Stop — the partial response is kept."
          >
            <span className="composer__stopicon" aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className="composer__send"
            onClick={submit}
            disabled={!value.trim() || disabled || over}
            aria-label="Send message"
          >
            ↑
          </button>
        )}
      </div>

      {over && (
        <div className="composer__hint composer__hint--warn" role="alert">
          {value.length.toLocaleString()} / {MAX_CHARS.toLocaleString()} characters — shorten
          the message to send it.
        </div>
      )}
    </div>
  )
}
