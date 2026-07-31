/* Markdown → React elements. Never `dangerouslySetInnerHTML`.
 *
 * design.md §Markdown rendering. Parsing to elements rather than injecting
 * HTML means model output cannot introduce markup into the app document at
 * all — the escape hatch simply does not exist, so there is nothing to
 * sanitize and nothing to get wrong later. */

import { memo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function CodeBlock({ children, className }) {
  const [copied, setCopied] = useState(false)
  const text = String(children).replace(/\n$/, '')
  const language = /language-(\w+)/.exec(className || '')?.[1]

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard denied — the source is still selectable */
    }
  }

  return (
    <div className="md-codeblock">
      <div className="md-codeblock__bar">
        <span className="md-codeblock__lang">{language || 'text'}</span>
        <button type="button" className="btn-ghost btn-ghost--sm" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>
        <code className={className}>{text}</code>
      </pre>
    </div>
  )
}

const components = {
  code({ inline, className, children, ...props }) {
    if (inline) {
      return (
        <code className="md-inline-code" {...props}>
          {children}
        </code>
      )
    }
    return <CodeBlock className={className}>{children}</CodeBlock>
  },
  // GFM tables get their own scroll container rather than forcing the whole
  // column wider and breaking the measure.
  table({ children }) {
    return (
      <div className="md-table-scroll">
        <table>{children}</table>
      </div>
    )
  },
  a({ href, children }) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    )
  },
}

function MarkdownImpl({ children, serif = false }) {
  return (
    <div className={`md${serif ? ' md--serif' : ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children || ''}
      </ReactMarkdown>
    </div>
  )
}

/* Memoised on content: an assistant message re-renders on every rAF flush
 * while streaming, and re-parsing unchanged Markdown each frame is the other
 * half of the stutter budget. */
export const Markdown = memo(MarkdownImpl)
