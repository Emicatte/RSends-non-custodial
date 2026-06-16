'use client'

import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import { useIsMobile } from '@/hooks/useIsMobile'
import AuthHeader from '@/components/auth/AuthHeader'
import { getFeature, otherFeatures, type FeatureKey } from '@/lib/features'
import { VISUALS } from '@/components/features/FeatureVisuals'

const CARD_BORDER = '1px solid rgba(200,81,44,0.15)'

const SECTION_H2: React.CSSProperties = {
  fontFamily: C.D,
  fontSize: 'clamp(24px, 3.2vw, 36px)',
  fontWeight: 600,
  color: C.text,
  lineHeight: 1.15,
  letterSpacing: '-0.02em',
  margin: 0,
}
const EYEBROW: React.CSSProperties = {
  fontFamily: C.M,
  fontSize: 11,
  letterSpacing: '0.18em',
  color: C.purple,
  fontWeight: 500,
  marginBottom: 12,
}

/** Reusable public marketing page shared by all four feature routes. */
export function FeaturePage({ featureKey }: { featureKey: FeatureKey }) {
  const t = useTranslations('features')
  const isMobile = useIsMobile()
  const feature = getFeature(featureKey)
  const Visual = VISUALS[feature.visual]
  const howItWorks = t.raw(`${featureKey}.howItWorks`) as { title: string; body: string }[]
  const example = t.raw(`${featureKey}.example`) as { label: string; text: string }
  const faqs = t.raw(`${featureKey}.faqs`) as { q: string; a: string }[]
  const others = otherFeatures(featureKey)

  const padX = isMobile ? 24 : 96
  const sectionMax = { maxWidth: 1440, margin: '0 auto' as const }

  const ctaButton = (label: string) => (
    <Link
      href="/signup"
      className="rounded-lg bg-[#C8512C] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#B04724]"
      style={{ textDecoration: 'none', display: 'inline-block' }}
    >
      {label}
    </Link>
  )

  return (
    <main style={{ minHeight: '100dvh', fontFamily: C.D, color: C.text, background: C.bg }}>
      <AuthHeader />

      {/* ── Hero ───────────────────────────────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '120px 24px 56px' : '160px 96px 80px',
        }}
      >
        <div style={{ maxWidth: 760 }}>
          <div
            style={{
              fontFamily: C.M,
              fontSize: 11,
              letterSpacing: '0.18em',
              color: C.purple,
              fontWeight: 500,
              marginBottom: 14,
            }}
          >
            {t(`${featureKey}.eyebrow`)}
          </div>
          <h1
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(32px, 5.5vw, 56px)',
              fontWeight: 600,
              color: C.text,
              lineHeight: 1.08,
              letterSpacing: '-0.02em',
              margin: '0 0 18px',
            }}
          >
            {t(`${featureKey}.title`)}
          </h1>
          <p
            style={{
              fontFamily: C.D,
              fontSize: 18,
              color: C.sub,
              lineHeight: 1.6,
              margin: '0 0 32px',
              maxWidth: 620,
            }}
          >
            {t(`${featureKey}.heroSub`)}
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
            {ctaButton(t('signUp'))}
            <Link
              href="/"
              style={{
                fontFamily: C.D,
                fontSize: 14,
                color: C.sub,
                textDecoration: 'none',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <span aria-hidden>←</span> {t('backToHome')}
            </Link>
          </div>
        </div>
      </section>

      {/* ── Overview (intro + visual mock) ─────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '8px 24px 16px' : `16px ${padX}px 32px`,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
            gap: isMobile ? 28 : 56,
            alignItems: 'center',
          }}
        >
          <div>
            <div style={EYEBROW}>{t('overview')}</div>
            <p
              style={{
                fontFamily: C.D,
                fontSize: 17,
                color: C.text,
                lineHeight: 1.7,
                margin: 0,
                opacity: 0.85,
              }}
            >
              {t(`${featureKey}.intro`)}
            </p>
          </div>
          <div>
            <Visual />
          </div>
        </div>
      </section>

      {/* ── How it works ───────────────────────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '40px 24px' : `48px ${padX}px 56px`,
        }}
      >
        <h2 style={SECTION_H2}>{t('howItWorks')}</h2>
        <div
          className="grid grid-cols-1 md:grid-cols-3 gap-4"
          style={{ marginTop: isMobile ? 24 : 32 }}
        >
          {howItWorks.map((step, i) => (
            <div key={i} className="rounded-2xl bg-white p-6" style={{ border: CARD_BORDER }}>
              <div
                className="h-9 w-9 rounded-lg flex items-center justify-center"
                style={{
                  background: 'rgba(200,81,44,0.08)',
                  color: C.purple,
                  fontFamily: C.M,
                  fontSize: 14,
                  fontWeight: 500,
                  marginBottom: 16,
                }}
              >
                {feature.sequential ? i + 1 : <CheckMark />}
              </div>
              <h3
                className="text-base font-semibold"
                style={{ color: '#2C2C2A', margin: '0 0 6px' }}
              >
                {step.title}
              </h3>
              <p className="text-sm leading-relaxed" style={{ color: '#888780', margin: 0 }}>
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Example (terracotta callout) ───────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '8px 24px 16px' : `8px ${padX}px 24px`,
        }}
      >
        <div
          style={{
            borderRadius: 16,
            border: '1px solid rgba(200,81,44,0.30)',
            background: 'rgba(200,81,44,0.05)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '8px 16px',
              background: 'rgba(200,81,44,0.10)',
              borderBottom: '1px solid rgba(200,81,44,0.18)',
            }}
          >
            <span
              style={{
                fontFamily: C.M,
                fontSize: 11,
                color: C.purple,
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              {example.label}
            </span>
          </div>
          <p
            style={{
              fontFamily: C.D,
              fontSize: 16,
              color: C.text,
              lineHeight: 1.7,
              margin: 0,
              padding: isMobile ? 16 : '20px 24px',
              opacity: 0.9,
            }}
          >
            {example.text}
          </p>
        </div>
      </section>

      {/* ── FAQ ────────────────────────────────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '40px 24px' : `48px ${padX}px 64px`,
        }}
      >
        <h2 style={SECTION_H2}>{t('faqs')}</h2>
        <div
          style={{
            marginTop: isMobile ? 20 : 28,
            borderTop: '1px solid rgba(10,10,10,0.08)',
            maxWidth: 820,
          }}
        >
          {faqs.map((f, i) => (
            <div
              key={i}
              style={{ padding: '20px 0', borderBottom: '1px solid rgba(10,10,10,0.08)' }}
            >
              <h3
                style={{
                  fontFamily: C.D,
                  fontSize: 16,
                  fontWeight: 600,
                  color: C.text,
                  margin: '0 0 8px',
                }}
              >
                {f.q}
              </h3>
              <p
                style={{
                  fontFamily: C.D,
                  fontSize: 15,
                  color: C.sub,
                  lineHeight: 1.7,
                  margin: 0,
                }}
              >
                {f.a}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── More reasons to sign in ────────────────────────── */}
      <section
        style={{
          ...sectionMax,
          padding: isMobile ? '24px 24px 56px' : `24px ${padX}px 80px`,
        }}
      >
        <h2
          style={{
            fontFamily: C.D,
            fontSize: 'clamp(20px, 2.6vw, 28px)',
            fontWeight: 600,
            color: C.text,
            letterSpacing: '-0.02em',
            margin: '0 0 24px',
          }}
        >
          {t('moreReasons')}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {others.map((o) => (
            <Link
              key={o.key}
              href={`/${o.slug}`}
              className="block rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C8512C]/40"
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <div
                className="rounded-2xl bg-white p-6 transition-colors h-full"
                style={{ border: CARD_BORDER }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.borderColor = 'rgba(200,81,44,0.35)')
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.borderColor = 'rgba(200,81,44,0.15)')
                }
              >
                <div
                  className="h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ background: 'rgba(200,81,44,0.08)', color: C.purple, marginBottom: 16 }}
                >
                  <o.Icon />
                </div>
                <h3 className="text-base font-semibold" style={{ color: '#2C2C2A', margin: 0 }}>
                  {t(`${o.key}.title`)}
                </h3>
                <p className="text-sm leading-relaxed" style={{ color: '#888780', margin: '6px 0 0' }}>
                  {t(`${o.key}.heroSub`)}
                </p>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Final CTA band ─────────────────────────────────── */}
      <section style={{ ...sectionMax, padding: isMobile ? '0 24px 72px' : `0 ${padX}px 96px` }}>
        <div
          style={{
            background: C.text,
            borderRadius: 24,
            padding: isMobile ? '40px 28px' : '64px 72px',
            textAlign: 'center',
          }}
        >
          <h2
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(24px, 3.4vw, 38px)',
              fontWeight: 600,
              color: C.surface,
              lineHeight: 1.15,
              letterSpacing: '-0.02em',
              margin: '0 0 14px',
            }}
          >
            {t('ctaBand.title')}
          </h2>
          <p
            style={{
              fontFamily: C.D,
              fontSize: 16,
              color: 'rgba(255,255,255,0.7)',
              lineHeight: 1.6,
              margin: '0 auto 28px',
              maxWidth: 560,
            }}
          >
            {t('ctaBand.sub')}
          </p>
          {ctaButton(t('ctaBand.button'))}
        </div>
      </section>
    </main>
  )
}

function CheckMark() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M20 6L9 17l-5-5" />
    </svg>
  )
}
