import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import MeshHeroVideo from '@/components/pricing/MeshHeroVideo'

export const metadata: Metadata = {
  title: 'Pricing — RSends',
  description:
    'A flat fee, never a percentage. €0.15 per transaction, capped at €1.15. Pick a plan for the features you need.',
}

type PageProps = { params: Promise<{ locale: string }> }

const PLAN_KEYS = ['free', 'pro', 'custom'] as const
const HPAD = 'clamp(20px, 6vw, 96px)'

export default async function PricingPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'pricing' })

  return (
    <main style={{ background: C.bg }}>
      {/* ── Dark hero ─────────────────────────────────────────── */}
      <section
        style={{
          position: 'relative',
          width: '100%',
          minHeight: 'clamp(520px, 70vh, 720px)',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
          background: '#0B0B0C',
        }}
      >
        <MeshHeroVideo />
        {/* legibility overlay */}
        <div
          aria-hidden="true"
          style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,12,0.45)', zIndex: 1 }}
        />
        {/* content */}
        <div
          style={{
            position: 'relative',
            zIndex: 2,
            width: '100%',
            maxWidth: 1440,
            margin: '0 auto',
            padding: `clamp(96px, 14vh, 160px) ${HPAD} clamp(64px, 10vh, 120px)`,
          }}
        >
          <div
            style={{
              fontFamily: C.M,
              fontSize: 13,
              fontWeight: 500,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: '#E8A488',
              marginBottom: 18,
            }}
          >
            {t('eyebrow')}
          </div>

          <h1
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(40px, 6vw, 84px)',
              fontWeight: 600,
              lineHeight: 1.05,
              letterSpacing: '-1px',
              color: '#FFFFFF',
              margin: '0 0 20px',
              maxWidth: 900,
            }}
          >
            {t('title')}
          </h1>

          <p
            style={{
              fontFamily: C.D,
              fontSize: 18,
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.82)',
              margin: '0 0 28px',
              maxWidth: 560,
            }}
          >
            {t('subtitle')}
          </p>

          <span
            style={{
              display: 'inline-block',
              fontFamily: C.M,
              fontSize: 14,
              color: '#FFFFFF',
              background: 'rgba(255,255,255,0.1)',
              border: '1px solid rgba(255,255,255,0.16)',
              borderRadius: 999,
              padding: '8px 16px',
            }}
          >
            {t('feeLine')}
          </span>
        </div>
      </section>

      {/* ── Light cards section ───────────────────────────────── */}
      <section style={{ background: C.bg, padding: `clamp(56px, 9vh, 104px) ${HPAD}` }}>
        <div style={{ maxWidth: 1120, margin: '0 auto' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: 20,
              alignItems: 'stretch',
            }}
          >
            {PLAN_KEYS.map((key) => {
              const isPro = key === 'pro'
              const features = t.raw(`plans.${key}.features`) as string[]
              const cta = t(`plans.${key}.cta`)
              const period = t(`plans.${key}.period`)
              return (
                <div
                  key={key}
                  style={{
                    background: C.surface,
                    border: isPro ? `1.5px solid ${C.purple}` : `1px solid ${C.border}`,
                    borderRadius: 16,
                    padding: '36px 32px',
                    display: 'flex',
                    flexDirection: 'column',
                    boxShadow: isPro ? '0 12px 40px rgba(200,81,44,0.10)' : 'none',
                  }}
                >
                  {/* Pro accent label */}
                  {isPro && (
                    <span
                      style={{
                        alignSelf: 'flex-start',
                        fontFamily: C.M,
                        fontSize: 11,
                        fontWeight: 600,
                        letterSpacing: '0.16em',
                        textTransform: 'uppercase',
                        color: C.purple,
                        background: 'rgba(200,81,44,0.08)',
                        borderRadius: 999,
                        padding: '4px 10px',
                        marginBottom: 14,
                      }}
                    >
                      {t('plans.pro.name')}
                    </span>
                  )}

                  <h3
                    style={{
                      fontFamily: C.D,
                      fontSize: 18,
                      fontWeight: 600,
                      color: C.text,
                      margin: '0 0 6px',
                    }}
                  >
                    {t(`plans.${key}.name`)}
                  </h3>

                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 10 }}>
                    <span
                      style={{
                        fontFamily: C.D,
                        fontSize: 'clamp(34px, 4vw, 44px)',
                        fontWeight: 600,
                        letterSpacing: '-1px',
                        color: C.text,
                      }}
                    >
                      {t(`plans.${key}.price`)}
                    </span>
                    {period && (
                      <span style={{ fontFamily: C.D, fontSize: 15, color: C.sub }}>{period}</span>
                    )}
                  </div>

                  <p
                    style={{
                      fontFamily: C.D,
                      fontSize: 15,
                      lineHeight: 1.55,
                      color: C.sub,
                      margin: '0 0 22px',
                    }}
                  >
                    {t(`plans.${key}.tagline`)}
                  </p>

                  <ul style={{ listStyle: 'none', margin: '0 0 28px', padding: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {features.map((f, i) => (
                      <li
                        key={i}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: 10,
                          fontFamily: C.D,
                          fontSize: 14,
                          lineHeight: 1.5,
                          color: C.text,
                        }}
                      >
                        <span style={{ color: C.purple, fontWeight: 700, lineHeight: 1.5 }}>✓</span>
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>

                  {/* CTA — pinned to bottom */}
                  <div style={{ marginTop: 'auto' }}>
                    {key === 'custom' ? (
                      <a
                        href="mailto:support@rsends.com"
                        style={{
                          display: 'block',
                          textAlign: 'center',
                          fontFamily: C.D,
                          fontSize: 15,
                          fontWeight: 600,
                          padding: '13px 24px',
                          borderRadius: 8,
                          textDecoration: 'none',
                          background: 'transparent',
                          color: C.text,
                          border: `1.5px solid ${C.text}`,
                        }}
                      >
                        {cta}
                      </a>
                    ) : (
                      <Link
                        href="/login"
                        style={{
                          display: 'block',
                          textAlign: 'center',
                          fontFamily: C.D,
                          fontSize: 15,
                          fontWeight: 600,
                          padding: '13px 24px',
                          borderRadius: 8,
                          textDecoration: 'none',
                          background: C.text,
                          color: C.bg,
                        }}
                      >
                        {cta}
                      </Link>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Honest footnote */}
          <p
            style={{
              fontFamily: C.D,
              fontSize: 13,
              lineHeight: 1.6,
              color: C.sub,
              textAlign: 'center',
              maxWidth: 640,
              margin: '32px auto 0',
            }}
          >
            {t('footnote')}
          </p>
        </div>
      </section>
    </main>
  )
}
