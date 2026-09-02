'use client'

import { useRef, useLayoutEffect, useEffect, type RefObject } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { CustomEase } from 'gsap/CustomEase'
import { REVEAL, REVEAL_QUERY } from '@/lib/motion'

gsap.registerPlugin(ScrollTrigger, CustomEase)

// The agreed ease-out, registered once at module scope so `ease: REVEAL.easeName`
// resolves for every tween below. An unregistered name is not an error in GSAP —
// the tween silently runs on the default ease — so this line is load-bearing and
// `revealTiming.test.tsx` asserts `gsap.parseEase` can find it.
CustomEase.create(REVEAL.easeName, REVEAL.easeCurve)

// useLayoutEffect on the client, useEffect on the server (avoids the SSR warning
// since "use client" components still render once on the server in the App Router).
const useIsoLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect

/**
 * The one reveal implementation. Every `selector` descendant of `ref` gets a
 * fade-up-and-sharpen tween on the shared tokens in `lib/motion.ts`.
 *
 * ── Why one trigger per element rather than one per section
 *
 * A trigger on the wrapper fires once, for everything inside it — including
 * blocks two viewports further down, which are then already resolved by the
 * time the reader reaches them. Each element carries its own trigger keyed to
 * its own position instead, so "resolves as it enters" is true for a section of
 * any height. The visible cascade down a page is a consequence of that, not of
 * a stagger.
 *
 * ── What the stagger is actually for
 *
 * Elements sharing a grid row enter at the SAME scroll position, so position
 * cannot order them; the index delay does. It is capped at `staggerCap` so a
 * six-card grid never has a last card that lags noticeably behind its first.
 *
 * ── Degradation
 *
 * Gated on `REVEAL_QUERY` via `gsap.matchMedia`, so under
 * `prefers-reduced-motion: reduce` no ScrollTrigger is created at all — not
 * created-and-killed, not created with a no-op tween. Nothing here is
 * responsible for making content appear: the base CSS (`.rs-reveal { opacity: 1 }`)
 * rests visible, and the hidden state exists only inside a running tween. A
 * failed, late or disabled bundle leaves readable content behind.
 */
export function useReveal<T extends HTMLElement>(selector: string): RefObject<T> {
  const ref = useRef<T>(null)

  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia()
    mm.add(REVEAL_QUERY, () => {
      const ctx = gsap.context(() => {
        // Scoped to THIS group's own elements, so sibling groups on one page
        // never cross-target each other.
        const items = gsap.utils.selector(ref)(selector)
        if (!items.length) return
        items.forEach((el, i) => {
          gsap.fromTo(
            el,
            // Only the tween ever sets `filter`, so reduced-motion and no-JS
            // renders stay sharp via the base CSS.
            { autoAlpha: 0, y: REVEAL.y, filter: `blur(${REVEAL.blur}px)` },
            {
              autoAlpha: 1,
              y: 0,
              filter: 'blur(0px)',
              duration: REVEAL.duration,
              ease: REVEAL.easeName,
              delay: Math.min(i * REVEAL.stagger, REVEAL.staggerCap),
              scrollTrigger: {
                trigger: el,
                start: REVEAL.start,
                toggleActions: REVEAL.toggleActions,
                once: REVEAL.once,
              },
            },
          )
        })
      }, ref)
      // Recompute the trigger positions once webfonts settle (layout shift),
      // then clean up.
      if (typeof document !== 'undefined' && document.fonts?.ready) {
        document.fonts.ready.then(() => ScrollTrigger.refresh())
      }
      return () => ctx.revert()
    })
    return () => mm.revert()
  }, [selector])

  return ref
}
