/* Drives one chat turn over SSE — design.md §Streaming and Motion.
 *
 * The critical detail is the render budget. A fast cloud stream delivers
 * dozens of token events per second; calling setState on each one makes React
 * render dozens of times per second and the typewriter visibly stutters. So
 * tokens land in a ref-held buffer and are flushed to state on a
 * requestAnimationFrame tick — at most one render per frame, whatever the
 * token rate, and the buffer coalesces naturally when the stream outruns the
 * display.
 *
 * The same treatment applies to artifact source, which arrives far faster than
 * prose. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { streamChat } from '../api/stream.js'
import { ApiError } from '../api/client.js'

const SLOW_MS = 3000 // "Retrieving from transcripts…"
const COLD_MS = 8000 // "Warming up the local model…" (local only)
const PREVIEW_DEBOUNCE_MS = 150

const EMPTY = {
  meta: null,
  text: '',
  artifact: null,
  citations: null,
  usage: null,
  error: null,
  finishReason: null,
}

export function useChatStream({ onComplete } = {}) {
  const [state, setState] = useState(EMPTY)
  const [streaming, setStreaming] = useState(false)
  const [waitStage, setWaitStage] = useState(null) // null | 'thinking' | 'retrieving' | 'warming'

  const abortRef = useRef(null)
  const rafRef = useRef(0)
  const textBuf = useRef('')
  const artifactBuf = useRef('')
  const startedAt = useRef(0)
  const gotFirstToken = useRef(false)
  const previewTimer = useRef(0)
  const onCompleteRef = useRef(onComplete)
  // Mirrors the artifact so `onComplete` can hand the finished object to the
  // caller. Reading it out of state there would see a stale closure value.
  const artifactRef = useRef(null)

  useEffect(() => {
    onCompleteRef.current = onComplete
  }, [onComplete])

  /** Flush both buffers into state, coalesced to one render per frame. */
  const scheduleFlush = useCallback(() => {
    if (rafRef.current) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      const t = textBuf.current
      const a = artifactBuf.current
      textBuf.current = ''
      artifactBuf.current = ''
      if (!t && !a) return

      setState((prev) => {
        const artifact =
          a && prev.artifact
            ? { ...prev.artifact, content: prev.artifact.content + a }
            : prev.artifact
        artifactRef.current = artifact
        return { ...prev, text: t ? prev.text + t : prev.text, artifact }
      })
    })
  }, [])

  const cleanup = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = 0
    if (previewTimer.current) clearTimeout(previewTimer.current)
    previewTimer.current = 0
  }, [])

  useEffect(() => cleanup, [cleanup])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const reset = useCallback(() => {
    cleanup()
    textBuf.current = ''
    artifactBuf.current = ''
    artifactRef.current = null
    setState(EMPTY)
    setStreaming(false)
    setWaitStage(null)
  }, [cleanup])

  const send = useCallback(
    async ({ sessionId, message, provider, skillOverride }) => {
      cleanup()
      textBuf.current = ''
      artifactBuf.current = ''
      gotFirstToken.current = false
      startedAt.current = Date.now()

      setState(EMPTY)
      setStreaming(true)
      setWaitStage('thinking')

      const controller = new AbortController()
      abortRef.current = controller

      // Escalating wait labels. "Specific beats indeterminate" — a spinner
      // that says nothing for 40 seconds on a cold local model reads as broken.
      const slowTimer = setTimeout(() => {
        if (!gotFirstToken.current) setWaitStage('retrieving')
      }, SLOW_MS)
      const coldTimer = setTimeout(() => {
        if (!gotFirstToken.current && provider === 'local') setWaitStage('warming')
      }, COLD_MS)

      const markFirstToken = () => {
        if (gotFirstToken.current) return
        gotFirstToken.current = true
        setWaitStage(null)
      }

      try {
        await streamChat(
          {
            session_id: sessionId,
            message,
            ...(provider ? { llm_provider: provider } : {}),
            ...(skillOverride ? { skill_override: skillOverride } : {}),
          },
          {
            meta: (d) => setState((p) => ({ ...p, meta: d })),

            token: (d) => {
              markFirstToken()
              textBuf.current += d.text || ''
              scheduleFlush()
            },

            artifact_start: (d) => {
              markFirstToken()
              const artifact = {
                id: d.artifact_id,
                type: d.type,
                title: d.title,
                content: '',
                complete: false,
                streaming: true,
                bytes: 0,
              }
              artifactRef.current = artifact
              setState((p) => ({ ...p, artifact }))
            },

            artifact_delta: (d) => {
              artifactBuf.current += d.text || ''
              scheduleFlush()
            },

            artifact_end: (d) => {
              // Flush any buffered source *before* marking complete, or the
              // last frame of content lands after the preview mounts.
              const tail = artifactBuf.current
              artifactBuf.current = ''
              setState((p) => {
                const artifact = p.artifact
                  ? {
                      ...p.artifact,
                      content: p.artifact.content + tail,
                      bytes: d.bytes,
                      complete: d.complete,
                      streaming: true, // preview still gated by the debounce
                    }
                  : p.artifact
                artifactRef.current = artifact
                return { ...p, artifact }
              })

              // Debounced so Preview mounts once, after the source settles —
              // mounting an iframe per token thrashes and a half-written
              // <div> previews as garbage.
              previewTimer.current = setTimeout(() => {
                setState((p) => {
                  const artifact = p.artifact ? { ...p.artifact, streaming: false } : p.artifact
                  artifactRef.current = artifact
                  return { ...p, artifact }
                })
              }, PREVIEW_DEBOUNCE_MS)
            },

            citations: (d) => setState((p) => ({ ...p, citations: d.citations || [] })),

            usage: (d) => setState((p) => ({ ...p, usage: d })),

            error: (d) =>
              setState((p) => ({
                ...p,
                error: { code: d.code, message: d.message, retryable: d.retryable },
              })),

            done: (d) => setState((p) => ({ ...p, finishReason: d.finish_reason })),
          },
          controller.signal
        )
      } catch (err) {
        if (err?.name === 'AbortError') {
          setState((p) => ({ ...p, finishReason: 'client_disconnect' }))
        } else if (err instanceof ApiError) {
          setState((p) => ({
            ...p,
            error: { code: err.code, message: err.message, retryable: err.retryable },
          }))
        } else {
          setState((p) => ({
            ...p,
            error: { code: 'INTERNAL_ERROR', message: 'Something went wrong.', retryable: false },
          }))
        }
      } finally {
        clearTimeout(slowTimer)
        clearTimeout(coldTimer)

        // Drain whatever the last frame left behind, so no token is lost
        // between the final flush and teardown.
        if (rafRef.current) cancelAnimationFrame(rafRef.current)
        rafRef.current = 0
        const t = textBuf.current
        const a = artifactBuf.current
        textBuf.current = ''
        artifactBuf.current = ''
        if (t || a) {
          setState((p) => {
            const artifact =
              a && p.artifact ? { ...p.artifact, content: p.artifact.content + a } : p.artifact
            artifactRef.current = artifact
            return { ...p, text: t ? p.text + t : p.text, artifact }
          })
        }

        setStreaming(false)
        setWaitStage(null)
        abortRef.current = null

        // Hand the finished artifact to the caller. Marked settled because the
        // stream is over — the preview debounce is a streaming affordance and
        // has no meaning once there is nothing left to arrive.
        const finalArtifact = artifactRef.current
          ? { ...artifactRef.current, streaming: false }
          : null
        onCompleteRef.current?.({ artifact: finalArtifact })
      }
    },
    [cleanup, scheduleFlush]
  )

  return { ...state, streaming, waitStage, send, stop, reset }
}
