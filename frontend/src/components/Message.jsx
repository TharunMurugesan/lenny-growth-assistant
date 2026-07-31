/* Message rendering — design.md §Message.
 *
 * User messages are right-aligned bubbles rendered as *plain text with
 * preserved line breaks*. Never Markdown: a user does not expect their
 * asterisks to become bold, and not parsing user input removes an injection
 * surface for free.
 *
 * Assistant messages get no bubble at all. Prose sits directly on the canvas
 * so a 1250-word essay reads as a document rather than as a very long chat
 * bubble. */

import { memo, useState } from 'react'
import { Markdown } from './Markdown.jsx'

const SKILL_LABELS = {
  qa: 'Skill A · Grounded Q&A',
  ship30: 'Skill B · Ship30for30',
  artifact: 'Skill C · Artifact',
  meta: 'About this assistant',
}

const SHIP30_MIN = 1125

function SkillBadge({ skill, wordCount }) {
  if (!skill) return null
  const accent = skill === 'ship30' || skill === 'artifact'
  const short = skill === 'ship30' && wordCount != null && wordCount < SHIP30_MIN

  return (
    <div className="msg__badgerow">
      <span className={`badge${accent ? ' badge--accent' : ''}`}>{SKILL_LABELS[skill] || skill}</span>
      {skill === 'ship30' && wordCount != null && (
        <span
          className={`msg__wordcount${short ? ' is-short' : ''}`}
          title={
            short
              ? `Target is 1,250 words (±10%). This came in at ${wordCount} after one ` +
                'continuation pass — the real count is shown rather than rounded up.'
              : 'Target is 1,250 words (±10%).'
          }
        >
          {wordCount.toLocaleString()} words
        </span>
      )}
    </div>
  )
}

function Sources({ citations }) {
  const [open, setOpen] = useState(false)
  if (!citations?.length) return null

  return (
    <div className="sources">
      <button
        type="button"
        className="sources__toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={`sources__chevron${open ? ' is-open' : ''}`} aria-hidden="true">
          ▸
        </span>
        Sources ({citations.length})
      </button>

      {open && (
        <ol className="sources__list">
          {citations.map((c) => (
            <li key={`${c.n}-${c.chunk_id || c.episode_title}`} className="sources__item">
              <span className="sources__n">{c.n}</span>
              <span className="sources__body">
                {c.source_url ? (
                  <a href={c.source_url} target="_blank" rel="noreferrer noopener">
                    {c.episode_title}
                  </a>
                ) : (
                  <span>{c.episode_title}</span>
                )}
                {c.guest && <span className="sources__guest"> · {c.guest}</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function ArtifactChip({ artifact, onOpen }) {
  if (!artifact) return null
  const kb = artifact.bytes ? `${(artifact.bytes / 1024).toFixed(1)} KB` : ''
  return (
    <button type="button" className="artifact-chip" onClick={onOpen}>
      <span className="artifact-chip__icon" aria-hidden="true">
        ◧
      </span>
      <span className="artifact-chip__body">
        <span className="artifact-chip__title">{artifact.title || 'Artifact'}</span>
        <span className="artifact-chip__meta">
          {artifact.type}
          {kb ? ` · ${kb}` : ''}
        </span>
      </span>
      <span className="artifact-chip__arrow" aria-hidden="true">
        →
      </span>
    </button>
  )
}

function UserMessage({ content }) {
  return (
    <div className="msg msg--user">
      <div className="msg__bubble">{content}</div>
    </div>
  )
}

function AssistantMessage({
  content,
  skill,
  provider,
  model,
  citations,
  wordCount,
  artifact,
  finishReason,
  streaming,
  onOpenArtifact,
  onRegenerate,
}) {
  const [copied, setCopied] = useState(false)
  // Skill B is *reading*, not UI — a serif at 17/29 signals "document".
  const serif = skill === 'ship30'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="msg msg--assistant">
      <SkillBadge skill={skill} wordCount={wordCount} />

      <div className="msg__body">
        <Markdown serif={serif}>{content}</Markdown>
        {streaming && <span className="caret" aria-hidden="true" />}
      </div>

      <ArtifactChip artifact={artifact} onOpen={onOpenArtifact} />
      <Sources citations={citations} />

      {finishReason === 'client_disconnect' && (
        <div className="msg__stopped">Stopped</div>
      )}
      {finishReason === 'max_tokens' && (
        <div className="msg__stopped">Incomplete — hit the response length limit.</div>
      )}

      {!streaming && (
        <div className="msg__actions">
          <button type="button" className="btn-ghost btn-ghost--sm" onClick={copy}>
            ⧉ {copied ? 'Copied' : 'Copy'}
          </button>
          {onRegenerate && (
            <button type="button" className="btn-ghost btn-ghost--sm" onClick={onRegenerate}>
              ↻ Regenerate
            </button>
          )}
          {provider && (
            <span className="msg__stamp" title="The provider and model that produced this answer.">
              ⚑ {provider === 'cloud' ? 'Cloud' : 'Local'}
              {model ? ` · ${model}` : ''}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function MessageImpl({ message, streaming, onOpenArtifact, onRegenerate }) {
  if (message.role === 'user') return <UserMessage content={message.content} />
  return (
    <AssistantMessage
      content={message.content}
      skill={message.skill}
      provider={message.provider}
      model={message.model}
      citations={message.citations}
      wordCount={message.word_count}
      artifact={message.artifact}
      finishReason={message.finish_reason}
      streaming={streaming}
      onOpenArtifact={onOpenArtifact}
      onRegenerate={onRegenerate}
    />
  )
}

export const Message = memo(MessageImpl)
