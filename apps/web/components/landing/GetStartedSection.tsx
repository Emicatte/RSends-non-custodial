'use client'

import { useState, useEffect, useRef, useLayoutEffect } from 'react'
import Image from 'next/image'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { ShieldCheck, Code2, type LucideIcon } from 'lucide-react'
import { C } from '@/app/designTokens'
import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

gsap.registerPlugin(ScrollTrigger)

// useLayoutEffect on the client, useEffect on the server (avoids the SSR warning).
const useIsoLayoutEffect = typeof window !== 'undefined' ? useLayoutEffect : useEffect

function useIsMobile(bp = 768) {
  const [m, setM] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`)
    setM(mq.matches)
    const h = (e: MediaQueryListEvent) => setM(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [bp])
  return m
}

/** NYC skyline photo — swap this single const to change the closing image. */
const GETSTARTED_IMG = '/grattacieli/pexels-einfoto-2174723.jpg'

const FEATURES: { key: 'noncustodial' | 'developers'; Icon: LucideIcon }[] = [
  { key: 'noncustodial', Icon: ShieldCheck },
  { key: 'developers', Icon: Code2 },
]

export default function GetStartedSection() {
  const isMobile = useIsMobile()
  const t = useTranslations('getStarted')
  const secRef = useRef<HTMLElement>(null)

  // Single scrubbed timeline anchored to the block's CENTER hitting viewport CENTER:
  // because this block is ~full-viewport tall, "centered on screen" === progress 1, so
  // the staggered text reveal finishes exactly when the block is centered (never near the
  // footer). The photo is static; reverses on scroll-up; nothing is hover-triggered.
  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia()
    mm.add('(prefers-reduced-motion: no-preference)', () => {
      const ctx = gsap.context(() => {
        const items = gsap.utils.toArray<HTMLElement>('.rs-gs-text')
        if (!items.length) return
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: secRef.current,
            start: 'top 75%', // begins shortly after the block starts entering
            end: 'center center', // fully done when the block's center hits viewport center
            scrub: 0.5,
          },
        })
        tl.from(items, { autoAlpha: 0, y: 28, ease: 'none', stagger: 0.12 })
      }, secRef)
      if (typeof document !== 'undefined' && document.fonts?.ready) {
        document.fonts.ready.then(() => ScrollTrigger.refresh())
      }
      return () => ctx.revert()
    })
    return () => mm.revert()
  }, [])

  return (
    <section
      ref={secRef}
      id="get-started"
      style={{
        padding: isMobile ? '72px 24px' : '120px 96px',
        maxWidth: 1440,
        margin: '0 auto',
        scrollMarginTop: 80,
      }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: isMobile ? '1fr' : '0.58fr 0.42fr',
          alignItems: 'stretch',
          borderRadius: 24,
          border: `1px solid ${C.border}`,
        }}
      >
        {/* Left: NYC cityscape — STATIC (no animation; lives in the only overflow:hidden child). */}
        <div
          style={{
            position: 'relative',
            minHeight: isMobile ? 260 : undefined,
            overflow: 'hidden',
            borderRadius: isMobile ? '24px 24px 0 0' : '24px 0 0 24px',
          }}
        >
          <Image
            src={GETSTARTED_IMG}
            alt=""
            fill
            sizes="(max-width: 768px) 100vw, 58vw"
            priority
            style={{ objectFit: 'cover' }}
          />
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,10,0.25)' }} />
        </div>

        {/* Right: dark panel — animated text (not clipped, so y is safe). */}
        <div
          style={{
            background: C.text,
            padding: isMobile ? '40px 28px' : 56,
            borderRadius: isMobile ? '0 0 24px 24px' : '0 24px 24px 0',
          }}
        >
          <h2
            className="rs-gs-text"
            style={{
              fontFamily: C.D,
              fontSize: isMobile ? 32 : 40,
              fontWeight: 600,
              color: '#fff',
              letterSpacing: '-1px',
              lineHeight: 1.1,
              margin: '0 0 16px',
            }}
          >
            {t('heading')}
          </h2>

          <p
            className="rs-gs-text"
            style={{
              fontFamily: C.D,
              fontSize: 16,
              color: 'rgba(255,255,255,0.8)',
              lineHeight: 1.6,
              maxWidth: 420,
              margin: '0 0 28px',
            }}
          >
            {t('subcopy')}
          </p>

          <div style={{ height: 1, background: 'rgba(255,255,255,0.12)', margin: '0 0 28px' }} />

          {FEATURES.map(({ key, Icon }) => (
            <div
              key={key}
              className="rs-gs-text"
              style={{ display: 'flex', gap: 14, alignItems: 'flex-start', marginBottom: 20 }}
            >
              <Icon size={20} color="#fff" strokeWidth={2} aria-hidden style={{ flexShrink: 0, marginTop: 2 }} />
              <div>
                <div style={{ fontFamily: C.D, fontSize: 15, fontWeight: 600, color: '#fff', marginBottom: 4 }}>
                  {t(`features.${key}.title`)}
                </div>
                <div style={{ fontFamily: C.D, fontSize: 14, color: 'rgba(255,255,255,0.7)', lineHeight: 1.5 }}>
                  {t(`features.${key}.desc`)}
                </div>
              </div>
            </div>
          ))}

          <Link
            className="rs-gs-text"
            href="/login"
            style={{
              display: 'block',
              textAlign: 'center',
              background: '#fff',
              color: C.text,
              fontFamily: C.D,
              fontSize: 16,
              fontWeight: 600,
              padding: '14px 24px',
              borderRadius: 8,
              textDecoration: 'none',
              marginTop: 8,
            }}
          >
            {t('cta')}
          </Link>

          <a
            href="mailto:emiliocatteddu@gmail.com"
            style={{
              display: 'block',
              textAlign: 'center',
              fontFamily: C.D,
              fontSize: 14,
              color: 'rgba(255,255,255,0.7)',
              textDecoration: 'none',
              marginTop: 16,
            }}
          >
            {t('secondary')}
          </a>
        </div>
      </div>
    </section>
  )
}
