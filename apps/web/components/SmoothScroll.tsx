'use client'

import { ReactNode, useEffect } from 'react'
import Lenis from 'lenis'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

export default function SmoothScroll({ children }: { children: ReactNode }) {
  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) return

    const lenis = new Lenis({
      duration: 1.4,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      lerp: 0.1,
      wheelMultiplier: 0.7,
      touchMultiplier: 1.5,
      smoothWheel: true,
      syncTouch: false,
    })

    // Canonical Lenis <-> ScrollTrigger integration: drive Lenis from a SINGLE
    // clock (GSAP's ticker) and update ScrollTrigger on every Lenis scroll, so
    // scrubbed timelines track the smoothed wheel. (The previous version drove
    // lenis.raf from BOTH a manual rAF loop and the ticker, with two time bases,
    // which corrupted the scroll delta and made scrubs feel auto-played.)
    lenis.on('scroll', ScrollTrigger.update)
    const onTick = (time: number) => lenis.raf(time * 1000)
    gsap.ticker.add(onTick)
    gsap.ticker.lagSmoothing(0)
    ScrollTrigger.refresh()

    return () => {
      lenis.off('scroll', ScrollTrigger.update)
      gsap.ticker.remove(onTick)
      lenis.destroy()
    }
  }, [])

  return <>{children}</>
}
