'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { C } from '@/app/designTokens'
import FadeIn from '@/components/motion/FadeIn'
import { StaggerContainer, StaggerItem } from '@/components/motion/Stagger'
import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

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

function CtaLink({ children, color, outlined, style, href, ...rest }: Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { color: string; outlined?: boolean; href: string }) {
  const [hov, setHov] = useState(false)
  return (
    <Link
      href={href}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        fontFamily: C.D, fontSize: 14, fontWeight: 600, cursor: 'pointer',
        padding: '12px 24px', borderRadius: 10, transition: 'all 0.2s',
        border: outlined ? `1.5px solid ${color}` : 'none',
        background: outlined ? (hov ? color : 'transparent') : color,
        color: outlined ? (hov ? '#fff' : color) : '#fff',
        opacity: hov ? 1 : (outlined ? 0.9 : 0.95),
        transform: hov ? 'translateY(-1px)' : 'none',
        display: 'inline-block',
        textDecoration: 'none',
        ...style,
      }}
      {...rest}
    >{children}</Link>
  )
}

export default function LandingSections() {
  const isMobile = useIsMobile()
  const t = useTranslations('twoPaths')

  const devBullets = [t('developers.b1'), t('developers.b2'), t('developers.b3'), t('developers.b4')]
  const bizBullets = [t('businesses.b1'), t('businesses.b2'), t('businesses.b3'), t('businesses.b4')]

  const cardStyle: React.CSSProperties = {
    background: C.surface,
    border: `1px solid ${C.border}`,
    borderRadius: 16,
    padding: isMobile ? '28px 24px' : '40px 36px',
    display: 'flex',
    flexDirection: 'column',
  }

  const iconBoxStyle: React.CSSProperties = {
    width: 40, height: 40,
    borderRadius: 10,
    background: `${C.purple}15`,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    marginBottom: 24,
  }

  const eyebrowStyle: React.CSSProperties = {
    fontFamily: C.M,
    fontSize: 11,
    letterSpacing: '0.18em',
    color: C.purple,
    fontWeight: 500,
    marginBottom: 12,
  }

  const cardHeadingStyle: React.CSSProperties = {
    fontFamily: C.D,
    fontSize: isMobile ? 24 : 28,
    fontWeight: 600,
    color: C.text,
    letterSpacing: '-0.02em',
    lineHeight: 1.15,
    margin: '0 0 16px',
  }

  const cardBodyStyle: React.CSSProperties = {
    fontFamily: C.D,
    fontSize: 14,
    color: C.sub,
    lineHeight: 1.6,
    margin: '0 0 24px',
  }

  return (
    <div style={{ position: 'relative', zIndex: 1 }}>
      <section style={{
        padding: isMobile ? '60px 24px' : '80px 96px',
        maxWidth: 1440,
        margin: '0 auto',
      }}>
        {/* ── Section header ── */}
        <FadeIn y={32} duration={0.9}>
          <div style={{ maxWidth: 880, marginBottom: isMobile ? 32 : 48 }}>
            <h2 style={{
              fontFamily: C.D,
              fontSize: 'clamp(28px, 4vw, 52px)',
              fontWeight: 600,
              color: C.text,
              lineHeight: 1.1,
              letterSpacing: '-0.02em',
              margin: '0 0 16px',
            }}>
              {t('title')}
            </h2>
            <p style={{
              fontFamily: C.D,
              fontSize: 15,
              color: C.sub,
              lineHeight: 1.6,
              margin: 0,
              maxWidth: 680,
            }}>
              {t('subtitle')}
            </p>
          </div>
        </FadeIn>

        {/* ── Dual-card grid ── */}
        <StaggerContainer
          staggerDelay={0.15}
          style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
            gap: 24,
          }}
        >
          {/* Card 1 — FOR DEVELOPERS */}
          <StaggerItem>
            <motion.div
              whileHover={{ y: -4, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } }}
              style={cardStyle}
            >
              <div style={iconBoxStyle}>
                <span style={{ fontFamily: C.M, fontSize: 16, fontWeight: 700, color: C.purple }}>{'<>'}</span>
              </div>
              <div style={eyebrowStyle}>{t('developers.eyebrow')}</div>
              <h3 style={cardHeadingStyle}>{t('developers.title')}</h3>
              <p style={cardBodyStyle}>{t('developers.body')}</p>
              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 28px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {devBullets.map(b => (
                  <li key={b} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.purple, marginTop: 7, flexShrink: 0 }} />
                    <span style={{ fontFamily: C.D, fontSize: 13, color: `${C.text}cc`, lineHeight: 1.5 }}>{b}</span>
                  </li>
                ))}
              </ul>
              <div style={{ marginTop: 'auto' }}>
                <CtaLink color={C.text} href="/docs">{t('developers.cta')}</CtaLink>
              </div>
            </motion.div>
          </StaggerItem>

          {/* Card 2 — FOR BUSINESSES */}
          <StaggerItem>
            <motion.div
              whileHover={{ y: -4, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } }}
              style={cardStyle}
            >
              <div style={iconBoxStyle}>
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" style={{ color: C.purple }}>
                  <rect x="1" y="1" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                  <rect x="11" y="1" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                  <rect x="1" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                  <rect x="11" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              </div>
              <div style={eyebrowStyle}>{t('businesses.eyebrow')}</div>
              <h3 style={cardHeadingStyle}>{t('businesses.title')}</h3>
              <p style={cardBodyStyle}>{t('businesses.body')}</p>
              <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 28px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {bizBullets.map(b => (
                  <li key={b} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                    <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.purple, marginTop: 7, flexShrink: 0 }} />
                    <span style={{ fontFamily: C.D, fontSize: 13, color: `${C.text}cc`, lineHeight: 1.5 }}>{b}</span>
                  </li>
                ))}
              </ul>
              <div style={{ marginTop: 'auto' }}>
                <CtaLink color={C.text} outlined href="/app">{t('businesses.cta')}</CtaLink>
              </div>
            </motion.div>
          </StaggerItem>
        </StaggerContainer>
      </section>
    </div>
  )
}
