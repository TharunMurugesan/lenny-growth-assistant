/* Cloud / Local toggle — design.md §LLM toggle.
 *
 * A segmented control rather than a switch, because both options and both
 * states should be legible at a glance without interacting.
 *
 * The honesty rule: an unavailable provider is **disabled, not hidden**, and
 * the tooltip states the fix ("No ANTHROPIC_API_KEY configured", "Ollama not
 * reachable at localhost:11434"). Hiding it would leave the user wondering
 * whether the feature exists; disabling it with a reason tells them exactly
 * what to do. Availability comes from GET /api/health — never assumed. */

const OPTIONS = [
  { id: 'cloud', label: 'Cloud', icon: '☁' },
  { id: 'local', label: 'Local', icon: '▣' },
]

export function LLMToggle({ value, onChange, cloud, local, checking }) {
  const status = { cloud, local }

  return (
    <div className="llm">
      <div className="llm__track" role="radiogroup" aria-label="Processing location">
        {OPTIONS.map((opt) => {
          const info = status[opt.id] || {}
          const available = !!info.available
          const active = value === opt.id

          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={!available}
              title={available ? `${opt.label} — ${info.model || ''}` : info.reason || 'Unavailable'}
              className={`llm__opt${active ? ' is-active' : ''}${
                available ? '' : ' is-unavailable'
              }`}
              onClick={() => available && onChange(opt.id)}
            >
              <span
                className={`dot ${
                  checking ? 'dot--checking' : available ? 'dot--ok' : 'dot--down'
                }`}
                aria-hidden="true"
              />
              <span className="llm__icon" aria-hidden="true">
                {opt.icon}
              </span>
              {opt.label}
              {/* Colour is never the only signal — screen readers and
                  colour-blind users get the state as text. */}
              <span className="sr-only">
                {checking ? ' (checking availability)' : available ? ' (available)' : ' (unavailable)'}
              </span>
            </button>
          )
        })}
      </div>

      <div className="llm__caption" title={status[value]?.reason || undefined}>
        {checking
          ? 'Checking providers…'
          : status[value]?.model || 'No model resolved'}
      </div>
    </div>
  )
}
