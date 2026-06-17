'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useMarketDataLive } from '@/hooks/useMarketDataLive'
import IPhoneMockup from '@/components/mockups/IPhoneMockup'
import DesktopMockup from '@/components/mockups/DesktopMockup'
import FadeIn from '@/components/motion/FadeIn'
import { C } from '@/app/designTokens'

type Breakpoint = 'mobile' | 'tablet' | 'desktop'

export default function ExploreTokens() {
  const t = useTranslations('exploreTokens')
  const { data, loading } = useMarketDataLive()
  const [bp, setBp] = useState<Breakpoint>('desktop')

  useEffect(() => {
    const mqMobile = window.matchMedia('(max-width: 767px)')
    const mqTablet = window.matchMedia('(min-width: 768px) and (max-width: 1279px)')

    const update = () => {
      if (mqMobile.matches) setBp('mobile')
      else if (mqTablet.matches) setBp('tablet')
      else setBp('desktop')
    }
    update()

    mqMobile.addEventListener('change', update)
    mqTablet.addEventListener('change', update)
    return () => {
      mqMobile.removeEventListener('change', update)
      mqTablet.removeEventListener('change', update)
    }
  }, [])

  const hasData = Object.keys(data).length > 0

  return (
    <div style={{ position: 'relative' }}>
      {/* Header — centered */}
      <FadeIn y={32} duration={0.9}>
        <div style={{
          textAlign: 'center',
          maxWidth: 720,
          margin: '0 auto 64px',
        }}>
          <div style={{
            fontFamily: C.D,
            fontSize: 14,
            fontWeight: 500,
            color: C.purple,
            letterSpacing: '0.18em',
            textTransform: 'uppercase' as const,
            marginBottom: 16,
          }}>
            {t('eyebrow')}
          </div>
          <h2 style={{
            fontFamily: C.D,
            fontSize: 'clamp(32px, 5vw, 64px)',
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
            fontSize: 20,
            color: 'rgba(10,10,10,0.70)',
            lineHeight: 1.5,
            margin: 0,
            maxWidth: 680,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}>
            {t('subtitle')}
          </p>
        </div>
      </FadeIn>

      {/* Mockup stage */}
      {hasData ? (
        <FadeIn y={48} duration={1.1} delay={0.15}>
          {/* Desktop: dual mockup */}
          {bp === 'desktop' && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 0,
              minHeight: 720,
              padding: '32px 0',
            }}>
              <div style={{ position: 'relative', zIndex: 10 }}>
                <DesktopMockup data={data} loading={loading} />
              </div>
              <div style={{
                position: 'relative', zIndex: 20,
                marginLeft: -120, marginTop: 40,
              }}>
                <IPhoneMockup data={data} loading={loading} />
              </div>
            </div>
          )}

          {/* Tablet: desktop mockup only, scaled */}
          {bp === 'tablet' && (
            <div style={{
              display: 'flex', justifyContent: 'center',
              padding: '32px 0',
            }}>
              <div style={{
                transform: 'scale(0.85)',
                transformOrigin: 'center top',
              }}>
                <DesktopMockup data={data} loading={loading} />
              </div>
            </div>
          )}

          {/* Mobile: iPhone only, no tilt */}
          {bp === 'mobile' && (
            <div style={{
              display: 'flex', justifyContent: 'center',
              padding: '32px 0',
            }}>
              <div style={{
                transform: 'scale(0.85)',
                transformOrigin: 'center top',
              }}>
                <IPhoneMockup data={data} loading={loading} tilt={false} />
              </div>
            </div>
          )}
        </FadeIn>
      ) : (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          minHeight: 720,
          fontFamily: C.D, fontSize: 14, color: C.sub,
        }}>
          Loading markets…
        </div>
      )}
    </div>
  )
}
