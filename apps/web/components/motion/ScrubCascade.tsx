'use client'

import { ReactNode } from 'react'
import { useReveal } from './useReveal'

type Props = {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
}

/**
 * The same reveal as `ScrubReveal`, keyed to `.rs-card` instead — the two exist
 * so a page can reveal its prose and its card grid independently, not because
 * they animate differently. They no longer do: both run
 * `useReveal`, and the strict 1-2-3-4 order a grid needs comes from the shared
 * index delay.
 *
 * What this used to do, and why it never looked right: it gave each card its own
 * per-index TRIGGER offset, `start: top (88 - i*6)%` against
 * `end: top (93 - i*6)%`. Scrolling down, an element's top passes 93% before it
 * passes 88%, so the end sat BEFORE the start; ScrollTrigger clamped the range
 * to nothing and the cards snapped instead of animating. Every card grid on the
 * landing, team, pricing and vision pages was affected.
 */
export default function ScrubCascade({ children, className, style }: Props) {
  const ref = useReveal<HTMLDivElement>('.rs-card')

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  )
}
