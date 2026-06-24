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
  /** first card's `start` (% of viewport). Each later card starts `stagger`% deeper. */
  startBase?: number
  /** first card's `end` (% of viewport). Each later card ends `stagger`% deeper. */
  endBase?: number
  /** per-index offset (%) applied to both start and end — the cascade tightness. */
  stagger?: number
}

/**
 * Section-scoped, scroll-scrubbed cascade. Unlike `ScrubReveal` (uniform start/end
 * per element), this gives every `.rs-card` descendant an INDEX-BASED trigger offset
 * so they reveal strictly one after another in DOM order (1 -> 2 -> 3 -> 4), even when
 * several share a grid row. Each later card starts a bit deeper in the viewport, which
 * breaks the pairwise sync of a 2x2 grid. Progress still scrubs with the wheel/trackpad
 * (stop -> hold, scroll up -> reverse). Respects prefers-reduced-motion; the base CSS
 * `.rs-card { opacity: 1 }` keeps content visible when the animation never runs.
 */
export default function ScrubCascade({
  children,
  className,
  style,
  y = 40,
  startBase = 88,
  endBase = 93,
  stagger = 6,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)

  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const ctx = gsap.context(() => {
        // Scope to THIS section's own .rs-card so multiple cascades don't cross-target.
        const q = gsap.utils.selector(ref)
        const cards = q('.rs-card')
        if (!cards.length) return
        // Index-based stagger: each later card starts deeper => strict 1,2,3,4 order.
        cards.forEach((el, i) => {
          gsap.fromTo(
            el,
            { autoAlpha: 0, y },
            {
              autoAlpha: 1,
              y: 0,
              ease: 'none',
              scrollTrigger: {
                trigger: el,
                start: `top ${startBase - i * stagger}%`,
                end: `top ${endBase - i * stagger}%`,
                scrub: 0.5,
              },
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
  }, [y, startBase, endBase, stagger])

  return (
    <div ref={ref} className={className} style={style}>
      {children}
    </div>
  )
}
