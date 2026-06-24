'use client'

import { ReactNode, useRef, useLayoutEffect, useEffect } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

// useLayoutEffect on the client, useEffect on the server (avoids the SSR warning
// since "use client" components still render once on the server in the App Router).
const useIsoLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect

type Props = {
  children: ReactNode
  className?: string
  style?: React.CSSProperties
  /** rise distance (px) for the fade-up */
  y?: number
  /** ScrollTrigger start, per element (enters from the bottom) */
  start?: string
  /** ScrollTrigger end, per element (fully revealed in the lower-middle of the viewport) */
  end?: string
}

/**
 * Section-scoped, scroll-scrubbed reveal. Gives every `.rs-reveal` descendant
 * its OWN ScrollTrigger keyed to that element's position, so each one finishes
 * as soon as it's comfortably in view (top 88% -> top 68%) while progress still
 * tracks the wheel/trackpad (stop -> hold, scroll up -> reverse). The cascade
 * comes naturally from elements entering at different scroll points. Respects
 * prefers-reduced-motion; the base CSS `.rs-reveal { opacity: 1 }` keeps content
 * visible when the animation never runs.
 */
export default function ScrubReveal({
  children,
  className,
  style,
  y = 40,
  start = 'top 92%',
  end = 'top 40%',
}: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const ctx = gsap.context(() => {
        // Scope to THIS section's own .rs-reveal so multiple ScrubReveals don't cross-target.
        const q = gsap.utils.selector(ref)
        const items = q('.rs-reveal')
        if (!items.length) return
        // One trigger per element, keyed to its own position, so each finishes
        // in the lower-middle of the viewport instead of all riding the wrapper.
        items.forEach((el) => {
          gsap.fromTo(
            el,
            { autoAlpha: 0, y },
            {
              autoAlpha: 1,
              y: 0,
              ease: 'none',
              scrollTrigger: { trigger: el, start, end, scrub: 0.9 },
            },
          )
        })
      }, ref)
      // Recompute start/end once webfonts settle (layout shift), then clean up.
      if (typeof document !== 'undefined' && document.fonts?.ready) {
        document.fonts.ready.then(() => ScrollTrigger.refresh())
      }
      return () => ctx.revert()
    })
    return () => mm.revert()
  }, [y, start, end])

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  )
}
