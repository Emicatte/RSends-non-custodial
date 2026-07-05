'use client'

import { useEffect, useRef, useState } from 'react'

const START_DELAY_MS = 300 // after document.fonts.ready
const CARET_LINGER_MS = 2000 // keep blinking after the last character
const CARET_FADE_MS = 400

/**
 * Progressive-enhancement typewriter for the /vision hero headline.
 *
 * The full headline is always in the markup: server render, no-JS, and
 * prefers-reduced-motion all show it verbatim (the animation only starts from
 * a client effect). Layout can never shift: an invisible sizing ghost holds
 * the final box (including multi-line wraps) while the typed overlay fills in
 * on top. Screen readers get the full text immediately via the sr-only span;
 * everything animated is aria-hidden.
 */
export default function TypewriterHeadline({
  text,
  style,
}: {
  text: string
  style?: React.CSSProperties
}) {
  // 'static' until hydration; the overlay shows the full headline. Flips to
  // 'typing' only when JS runs and the user hasn't asked for reduced motion.
  const [phase, setPhase] = useState<'static' | 'typing' | 'done' | 'caret-fading' | 'finished'>('static')
  const [typed, setTyped] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let cancelled = false
    const schedule = (fn: () => void, ms: number) => {
      timerRef.current = setTimeout(() => {
        if (!cancelled) fn()
      }, ms)
    }

    const typeFrom = (index: number) => {
      if (index > text.length) {
        setPhase('done')
        schedule(() => {
          setPhase('caret-fading')
          schedule(() => setPhase('finished'), CARET_FADE_MS)
        }, CARET_LINGER_MS)
        return
      }
      setTyped(text.slice(0, index))
      // 45-65ms per character with slight jitter
      schedule(() => typeFrom(index + 1), 45 + Math.random() * 20)
    }

    // Wait for webfonts so the ghost's reserved box is already in its final
    // metrics when typing starts. jsdom and older engines lack document.fonts.
    const fontsReady: Promise<unknown> = document.fonts?.ready ?? Promise.resolve()
    fontsReady.then(() => {
      if (cancelled) return
      setPhase('typing')
      setTyped('')
      schedule(() => typeFrom(1), START_DELAY_MS)
    })

    return () => {
      cancelled = true
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [text])

  const showCaret = phase === 'typing' || phase === 'done' || phase === 'caret-fading'

  return (
    <h1 style={{ ...style, position: 'relative' }}>
      <style>{`
        @keyframes rs-tw-blink { 50% { opacity: 0; } }
        .rs-tw-caret {
          display: inline-block;
          width: 2px;
          height: 0.85em;
          margin-left: 3px;
          vertical-align: -0.08em;
          background: #C8512C;
          animation: rs-tw-blink 1s steps(1, end) infinite;
        }
        .rs-tw-caret--fading {
          opacity: 0;
          transition: opacity ${CARET_FADE_MS}ms ease;
          animation: none;
        }
      `}</style>
      {/* Visually hidden, but immediately available to screen readers */}
      <span
        style={{
          position: 'absolute',
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: 'hidden',
          clip: 'rect(0, 0, 0, 0)',
          whiteSpace: 'nowrap',
          border: 0,
        }}
      >
        {text}
      </span>
      <span aria-hidden="true" style={{ position: 'relative', display: 'block' }}>
        {/* Sizing ghost: reserves the final box (incl. line wraps) at every width */}
        <span style={{ visibility: 'hidden', display: 'block' }}>{text}</span>
        <span style={{ position: 'absolute', inset: 0, display: 'block' }}>
          {phase === 'static' ? text : typed}
          {showCaret && (
            <span className={`rs-tw-caret${phase === 'caret-fading' ? ' rs-tw-caret--fading' : ''}`} />
          )}
        </span>
      </span>
    </h1>
  )
}
