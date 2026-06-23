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

const PLAN_KEYS = ['free', 'pro', 'custom'] as const

export default function PricingSection() {
  const isMobile = useIsMobile()
  const t = useTranslations('pricing')

  const cardStyle = (featured: boolean): React.CSSProperties => ({
    background: C.surface,
    border: featured ? `1.5px solid ${C.purple}` : `1px solid ${C.border}`,
    borderRadius: 16,
    padding: isMobile ? '28px 24px' : '36px 32px',
    display: 'flex',
    flexDirection: 'column',
  })

  return (
    <div id="pricing" style={{ position: 'relative', zIndex: 1, scrollMarginTop: 80 }}>
      <section style={{
        padding: isMobile ? '60px 24px' : '100px 96px',
        maxWidth: 1440,
        margin: '0 auto',
      }}>
        {/* ── Section header ── */}
        <FadeIn y={32} duration={0.9}>
          <div style={{ maxWidth: 880, marginBottom: isMobile ? 32 : 56 }}>
            <div style={{
              fontFamily: C.M,
              fontSize: 11,
              letterSpacing: '0.18em',
              color: C.purple,
              fontWeight: 500,
              marginBottom: 12,
            }}>
              {t('eyebrow')}
            </div>
            <h2 style={{
              fontFamily: C.D,
              fontSize: 'clamp(28px, 4vw, 52px)',
              fontWeight: 500,
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
              margin: '0 0 16px',
              maxWidth: 680,
            }}>
              {t('subtitle')}
            </p>
            <div style={{
              display: 'inline-block',
              fontFamily: C.M,
              fontSize: 13,
              color: C.text,
              background: `${C.purple}12`,
              border: `1px solid ${C.purple}30`,
              borderRadius: 999,
              padding: '8px 16px',
            }}>
              {t('feeLine')}
            </div>
          </div>
        </FadeIn>

        {/* ── Plan cards ── */}
        <StaggerContainer
          staggerDelay={0.15}
          style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr',
            gap: 24,
          }}
        >
          {PLAN_KEYS.map((key) => {
            const featured = key === 'pro'
            const features = t.raw(`plans.${key}.features`) as string[]
            return (
              <StaggerItem key={key}>
                <motion.div
                  whileHover={{ y: -4, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } }}
                  style={cardStyle(featured)}
                >
                  <div style={{
                    fontFamily: C.M,
                    fontSize: 11,
                    letterSpacing: '0.18em',
                    color: featured ? C.purple : C.sub,
                    fontWeight: 500,
                    marginBottom: 12,
                  }}>
                    {t(`plans.${key}.name`)}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 6 }}>
                    <span style={{
                      fontFamily: C.D,
                      fontSize: isMobile ? 32 : 38,
                      fontWeight: 600,
                      color: C.text,
                      letterSpacing: '-0.02em',
                    }}>
                      {t(`plans.${key}.price`)}
                    </span>
                    <span style={{ fontFamily: C.D, fontSize: 14, color: C.sub }}>
                      {t(`plans.${key}.period`)}
                    </span>
                  </div>
                  <p style={{
                    fontFamily: C.D,
                    fontSize: 14,
                    color: C.sub,
                    lineHeight: 1.6,
                    margin: '0 0 24px',
                  }}>
                    {t(`plans.${key}.tagline`)}
                  </p>
                  <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 28px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {features.map((f) => (
                      <li key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                        <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.purple, marginTop: 7, flexShrink: 0 }} />
                        <span style={{ fontFamily: C.D, fontSize: 13, color: `${C.text}cc`, lineHeight: 1.5 }}>{f}</span>
                      </li>
                    ))}
                  </ul>
                  <div style={{ marginTop: 'auto' }}>
                    <Link
                      href={key === 'custom' ? '/docs' : '/login'}
                      style={{
                        fontFamily: C.D, fontSize: 14, fontWeight: 600,
                        padding: '12px 24px', borderRadius: 10,
                        border: featured ? 'none' : `1.5px solid ${C.text}`,
                        background: featured ? C.text : 'transparent',
                        color: featured ? '#fff' : C.text,
                        display: 'inline-block', textDecoration: 'none',
                      }}
                    >
                      {t(`plans.${key}.cta`)}
                    </Link>
                  </div>
                </motion.div>
              </StaggerItem>
            )
          })}
        </StaggerContainer>

        {/* ── Compliance line ── */}
        <FadeIn y={20} duration={0.8}>
          <p style={{
            fontFamily: C.M,
            fontSize: 12,
            color: C.sub,
            lineHeight: 1.6,
            margin: isMobile ? '28px 0 0' : '40px 0 0',
            textAlign: 'center',
          }}>
            {t('compliance')}
          </p>
        </FadeIn>
      </section>
    </div>
  )
}
