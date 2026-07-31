/* The Artifact Viewer — design.md §The Artifact Viewer.
 *
 * The reason this app is not a chat window: HTML, CSS, and Markdown render in
 * place, with no external redirect and no download-to-view step.
 *
 * The security model is the whole design, and it is a *pairing*:
 *
 *   sandbox="allow-scripts"   without   allow-same-origin
 *
 * Scripts run, so an interactive mockup actually works. But the frame gets an
 * opaque origin, so it cannot reach the parent DOM, localStorage, cookies, or
 * the session. Adding allow-same-origin alongside allow-scripts would let the
 * frame remove its own sandbox attribute — the two together are equivalent to
 * no sandbox at all.
 *
 * allow-forms / allow-popups / allow-modals / allow-top-navigation are all
 * omitted, so an artifact cannot navigate the app away, open windows, or raise
 * a blocking alert().
 *
 * Sanitized innerHTML injection was rejected in Phase 1: any sanitizer strict
 * enough to be safe strips the <style> blocks and scripts that make a mockup
 * worth previewing. Isolation beats filtering. */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Markdown } from './Markdown.jsx'

const SANDBOX = 'allow-scripts'

/* Blocks every network destination while permitting the inline style and
 * script a self-contained mockup needs, plus data: URIs for inline images and
 * fonts. An artifact therefore cannot beacon, exfiltrate, or load a tracker —
 * and a mockup that *tries* to pull a Google Font renders unstyled rather than
 * silently phoning home, which is why the Skill C prompt forbids remote URLs. */
const CSP =
  "default-src 'none'; " +
  "style-src 'unsafe-inline'; " +
  "script-src 'unsafe-inline'; " +
  "img-src data: blob:; " +
  "font-src data:; " +
  "media-src data: blob:; " +
  "form-action 'none'; " +
  "base-uri 'none'"

function withCsp(html) {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`
  // Inject as early as possible: a CSP meta tag only governs what comes after
  // it, so placing it after a <script> would leave that script ungoverned.
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head[^>]*>/i, (m) => `${m}\n${meta}`)
  }
  if (/<html[^>]*>/i.test(html)) {
    return html.replace(/<html[^>]*>/i, (m) => `${m}\n<head>${meta}</head>`)
  }
  return `<!doctype html><html><head>${meta}</head><body>${html}</body></html>`
}

function bytesLabel(n) {
  if (!n && n !== 0) return ''
  if (n < 1024) return `${n} B`
  return `${(n / 1024).toFixed(1)} KB`
}

function HtmlPreview({ content, title, reloadKey }) {
  const srcDoc = useMemo(() => withCsp(content), [content])
  return (
    <iframe
      // Keyed on content + an explicit reload counter so React re-mounts the
      // frame rather than patching a live document. Patching mid-stream
      // produces flicker and half-parsed CSS.
      key={`${reloadKey}:${content.length}`}
      className="artifact__frame"
      title={title ? `Artifact preview: ${title}` : 'Artifact preview'}
      sandbox={SANDBOX}
      srcDoc={srcDoc}
    />
  )
}

function CodeView({ content, streaming }) {
  const ref = useRef(null)
  const lines = useMemo(() => content.split('\n'), [content])

  // Follow the caret while source streams in, but stop the moment it settles
  // so the user can scroll back through what arrived.
  useEffect(() => {
    if (streaming && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [content, streaming])

  return (
    <div className="artifact__code" ref={ref}>
      <pre>
        <code>
          {lines.map((line, i) => (
            <span className="artifact__line" key={i}>
              <span className="artifact__lineno">{i + 1}</span>
              <span className="artifact__linetext">{line || ' '}</span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  )
}

export function ArtifactViewer({ artifact, onClose, width, onResize }) {
  // Code first while streaming: the user watches it assemble in the
  // representation where partial content is meaningful, then Preview mounts.
  const [tab, setTab] = useState('code')
  const [fullscreen, setFullscreen] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [copied, setCopied] = useState(false)
  const dragging = useRef(false)

  // An artifact replayed from history carries neither `streaming` nor
  // `complete` — those are live-stream concepts. Absent means settled and
  // whole, so both checks compare against the explicit false rather than
  // testing truthiness, which would leave a reopened artifact stuck on Code.
  const settled = !!artifact && artifact.streaming !== true
  const incomplete = artifact?.complete === false

  // Auto-select Preview once the source settles — but never yank the tab away
  // from an incomplete artifact, because then the source *is* the truth and
  // that is what the user needs to see.
  useEffect(() => {
    if (!artifact) return
    if (settled && !incomplete) setTab('preview')
    else if (artifact.streaming === true) setTab('code')
  }, [settled, incomplete, artifact?.streaming, artifact?.id])

  useEffect(() => {
    if (!fullscreen) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') setFullscreen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  useEffect(() => {
    const move = (e) => {
      if (!dragging.current) return
      const pct = ((window.innerWidth - e.clientX) / window.innerWidth) * 100
      onResize?.(Math.min(70, Math.max(30, pct)))
    }
    const up = () => {
      dragging.current = false
      document.body.classList.remove('is-resizing')
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [onResize])

  if (!artifact) return null

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(artifact.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* ignore */
    }
  }

  const download = () => {
    const ext = artifact.type === 'markdown' ? 'md' : 'html'
    const name = (artifact.title || 'artifact').replace(/[^\w.-]+/g, '-').toLowerCase()
    const blob = new Blob([artifact.content], {
      type: artifact.type === 'markdown' ? 'text/markdown' : 'text/html',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${name}.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <aside
      className={`artifact${fullscreen ? ' artifact--fullscreen' : ''}`}
      style={fullscreen ? undefined : { width: `${width}%` }}
      role="complementary"
      aria-label="Artifact viewer"
    >
      {!fullscreen && (
        <div
          className="artifact__handle"
          onMouseDown={() => {
            dragging.current = true
            document.body.classList.add('is-resizing')
          }}
          role="separator"
          aria-label="Resize artifact panel"
          aria-orientation="vertical"
        />
      )}

      <header className="artifact__header">
        <span className="artifact__icon" aria-hidden="true">
          ◧
        </span>
        <h2 className="artifact__title" title={artifact.title || 'Artifact'}>
          {artifact.title || 'Artifact'}
        </h2>

        <span className="artifact__meta">
          {artifact.type}
          {artifact.bytes ? ` · ${bytesLabel(artifact.bytes)}` : ''}
        </span>

        {incomplete && !artifact.streaming && (
          <span className="chip chip--warning" title="The model stopped before closing the tag.">
            Incomplete
          </span>
        )}

        <button
          type="button"
          className="btn-icon"
          onClick={() => setFullscreen((v) => !v)}
          aria-label={fullscreen ? 'Exit fullscreen' : 'Expand to fullscreen'}
        >
          ⤢
        </button>
        <button type="button" className="btn-icon" onClick={onClose} aria-label="Close artifact">
          ✕
        </button>
      </header>

      <div className="artifact__tabs" role="tablist" aria-label="Artifact view">
        {['preview', 'code'].map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            id={`artifact-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`artifact-panel-${name}`}
            className={`artifact__tab${tab === name ? ' is-active' : ''}`}
            onClick={() => setTab(name)}
          >
            {name === 'preview' ? 'Preview' : 'Code'}
          </button>
        ))}
      </div>

      <div
        className="artifact__surface"
        role="tabpanel"
        id={`artifact-panel-${tab}`}
        aria-labelledby={`artifact-tab-${tab}`}
      >
        {tab === 'code' ? (
          <CodeView content={artifact.content} streaming={artifact.streaming === true} />
        ) : artifact.streaming === true ? (
          <div className="artifact__pending">Rendering preview…</div>
        ) : artifact.type === 'markdown' ? (
          <div className="artifact__markdown">
            <Markdown serif>{artifact.content}</Markdown>
          </div>
        ) : (
          <HtmlPreview
            content={artifact.content}
            title={artifact.title}
            reloadKey={reloadKey}
          />
        )}
      </div>

      <footer className="artifact__footer">
        <button type="button" className="btn-ghost" onClick={copy}>
          ⧉ {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className="btn-ghost" onClick={download}>
          ⬇ Download
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setReloadKey((k) => k + 1)}
          title="Re-mount the preview — the escape hatch for a stuck script or animation."
        >
          ↻ Reload
        </button>
      </footer>
    </aside>
  )
}
