'use client'

import { ReactNode, useEffect } from 'react'
import Lenis from 'lenis'

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

    let rafId: number
    const raf = (time: number) => {
      lenis.raf(time)
      rafId = requestAnimationFrame(raf)
    }
    rafId = requestAnimationFrame(raf)

    // GSAP ScrollTrigger sync
    import('gsap').then(({ gsap }) => {
      import('gsap/ScrollTrigger').then(({ ScrollTrigger }) => {
        gsap.registerPlugin(ScrollTrigger)
        lenis.on('scroll', ScrollTrigger.update)
        gsap.ticker.add((time) => lenis.raf(time * 1000))
        gsap.ticker.lagSmoothing(0)
      })
    })

    return () => {
      cancelAnimationFrame(rafId)
      lenis.destroy()
    }
  }, [])

  return <>{children}</>
}
