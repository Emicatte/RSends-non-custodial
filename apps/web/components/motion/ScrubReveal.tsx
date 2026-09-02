'use client'

import { ReactNode } from 'react'
import { useReveal } from './useReveal'

type Props = {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
}

/**
 * Reveals every `.rs-reveal` descendant on the shared timing in `lib/motion.ts`.
 *
 * There are deliberately NO timing props. Trigger point, duration, easing, rise,
 * blur and stagger are one set of values for the whole marketing site — the
 * landing page used to sit on a slower default than every other page, and
 * sixteen call sites carried a `scrub={0.5}` to pull themselves back. Nothing to
 * override means nothing to drift. `revealTiming.test.tsx` enforces it.
 *
 * (The name predates the rewrite: this no longer scrubs, it plays once on a
 * fixed duration. Renaming it touches two dozen call sites across five pages and
 * was kept out of the behaviour fix.)
 */
export default function ScrubReveal({ children, className, style }: Props) {
  const ref = useReveal<HTMLDivElement>('.rs-reveal')

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  )
}
