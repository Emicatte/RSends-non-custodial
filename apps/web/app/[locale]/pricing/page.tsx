import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import MeshHeroVideo from '@/components/pricing/MeshHeroVideo'
import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'

export const metadata: Metadata = {
  title: 'Pricing — RSends',
  description:
    'A flat fee, never a percentage. €0.15 per transaction, capped at €1.15. Pick a plan for the features you need.',
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'

// Single source of truth for the fee model. Hard-coded so every locale renders
// the exact same figures (DM Mono). NEVER a percentage of volume.
const FEE_ROWS = [
  { payment: '€50', fee: '€0.15' },
  { payment: '€1,200', fee: '€1.15' },
  { payment: '€50,000', fee: '€1.15' },
] as const

// Illustrative split — percentages sum to 100; the fee is a flat line item,
// NOT part of the split. Address labels are obviously fake placeholders.
const SPLIT = {
  total: '€49.00',
  rows: [
    { addr: '0x…shop', pct: 88 },
    { addr: '0x…seller', pct: 12 },
  ],
  fee: '€0.15',
} as const

const PLAN_KEYS = ['free', 'pro', 'custom'] as const

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
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
          background: '#0A0A0A',
        }}
      >
        <MeshHeroVideo />
        {/* legibility overlay */}
        <div
          aria-hidden="true"
          style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,12,0.45)', zIndex: 1 }}
        />
        {/* content — eyebrow + headline, vertically centered */}
        <div
          style={{
            position: 'relative',
            zIndex: 2,
            width: '100%',
            maxWidth: 1440,
            margin: '0 auto',
            padding: `0 ${HPAD}`,
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
              fontSize: 'clamp(32px, 4.2vw, 60px)',
              fontWeight: 400,
              lineHeight: 1.08,
              letterSpacing: '-0.5px',
              color: '#FFFFFF',
              margin: 0,
              maxWidth: 900,
            }}
          >
            {t('title')}
          </h1>

          <p
            style={{
              fontFamily: C.D,
              fontSize: 17,
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.8)',
              margin: '20px 0 0',
              maxWidth: 560,
            }}
          >
            {t('subtitle')}
          </p>
        </div>
      </section>

      {/* ── Fee model — explained by example ──────────────────── */}
      <section style={{ background: C.bg, padding: `clamp(64px, 11vh, 120px) ${HPAD}` }}>
        <div style={{ maxWidth: 1040, margin: '0 auto' }}>
          <ScrubReveal scrub={0.5}>
            <div className="rs-reveal" style={{ maxWidth: 760, marginBottom: 'clamp(32px, 5vh, 56px)' }}>
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
                {t('feeModel.eyebrow')}
              </div>
              <h2
                style={{
                  fontFamily: C.D,
                  fontSize: 'clamp(28px, 4vw, 48px)',
                  fontWeight: 500,
                  color: C.text,
                  lineHeight: 1.12,
                  letterSpacing: '-0.02em',
                  margin: 0,
                }}
              >
                {t('feeModel.title')}
              </h2>
            </div>
          </ScrubReveal>

          {/* Example grid — each column is its own animated boundary */}
          <ScrubCascade
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: 20,
            }}
          >
            {FEE_ROWS.map((row) => (
              <div
                key={row.payment}
                className="rs-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 16,
                  padding: '32px 28px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 18,
                }}
              >
                <div>
                  <div
                    style={{
                      fontFamily: C.D,
                      fontSize: 13,
                      color: C.sub,
                      marginBottom: 6,
                    }}
                  >
                    {t('feeModel.paymentLabel')}
                  </div>
                  <div
                    style={{
                      fontFamily: C.M,
                      fontSize: 'clamp(26px, 3vw, 32px)',
                      fontWeight: 500,
                      color: C.text,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {row.payment}
                  </div>
                </div>

                <div
                  aria-hidden="true"
                  style={{ height: 1, background: C.border, margin: '2px 0' }}
                />

                <div>
                  <div
                    style={{
                      fontFamily: C.D,
                      fontSize: 13,
                      color: C.sub,
                      marginBottom: 6,
                    }}
                  >
                    {t('feeModel.feeLabel')}
                  </div>
                  <div
                    style={{
                      fontFamily: C.M,
                      fontSize: 'clamp(26px, 3vw, 32px)',
                      fontWeight: 500,
                      color: C.purple,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {row.fee}
                  </div>
                </div>
              </div>
            ))}
          </ScrubCascade>

          {/* Rule caption */}
          <ScrubReveal scrub={0.5}>
            <p
              className="rs-reveal"
              style={{
                fontFamily: C.D,
                fontSize: 15,
                lineHeight: 1.6,
                color: C.sub,
                margin: '28px 0 0',
                maxWidth: 680,
              }}
            >
              {t('feeModel.caption')}
            </p>
          </ScrubReveal>
        </div>
      </section>

      {/* ── Split illustration — the fee inside a real transaction ─ */}
      <section style={{ background: C.bg, padding: `0 ${HPAD} clamp(56px, 9vh, 104px)` }}>
        <ScrubReveal scrub={0.5} style={{ maxWidth: 520, margin: '0 auto' }}>
          {/* Card is the outermost (clipped) boundary — y-reveal lives here;
              inner rows stay static so nothing translates inside overflow:hidden */}
          <div
            className="rs-reveal"
            style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 24,
              overflow: 'hidden',
              boxShadow: '0 24px 60px rgba(10,10,10,0.06)',
            }}
          >
            {/* Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                padding: '22px 26px',
                borderBottom: `1px solid ${C.border}`,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                <span
                  style={{
                    fontFamily: C.D,
                    fontSize: 12,
                    fontWeight: 600,
                    letterSpacing: '0.18em',
                    color: C.text,
                  }}
                >
                  {t('split.label')}
                </span>
                <span style={{ color: C.sub }}>·</span>
                <span
                  style={{
                    fontFamily: C.M,
                    fontSize: 18,
                    fontWeight: 500,
                    color: C.text,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {SPLIT.total}
                </span>
              </div>
              <span
                style={{
                  fontFamily: C.M,
                  fontSize: 10,
                  letterSpacing: '0.10em',
                  textTransform: 'uppercase',
                  color: C.purple,
                  background: 'rgba(200,81,44,0.08)',
                  border: `1px solid rgba(200,81,44,0.20)`,
                  borderRadius: 999,
                  padding: '4px 9px',
                }}
              >
                {t('split.disclaimer')}
              </span>
            </div>

            {/* Split rows — sum to 100% */}
            <div style={{ padding: '20px 26px', display: 'flex', flexDirection: 'column', gap: 16 }}>
              {SPLIT.rows.map((r) => (
                <div key={r.addr} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <span
                    style={{
                      fontFamily: C.M,
                      fontSize: 14,
                      color: C.text,
                      width: 92,
                      flexShrink: 0,
                    }}
                  >
                    {r.addr}
                  </span>
                  <div
                    aria-hidden="true"
                    style={{
                      flex: 1,
                      height: 8,
                      borderRadius: 999,
                      background: 'var(--rs-wash)',
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${r.pct}%`,
                        height: '100%',
                        borderRadius: 999,
                        background: C.purple,
                      }}
                    />
                  </div>
                  <span
                    style={{
                      fontFamily: C.M,
                      fontSize: 14,
                      color: C.text,
                      width: 44,
                      textAlign: 'right',
                      flexShrink: 0,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {r.pct}%
                  </span>
                </div>
              ))}
            </div>

            {/* Fee — a SEPARATE flat line item, not part of the split % */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                padding: '16px 26px',
                borderTop: `1px solid ${C.border}`,
                background: 'rgba(200,81,44,0.04)',
              }}
            >
              <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 500, color: C.text }}>
                {t('split.feeLabel')}
              </span>
              <span
                style={{
                  fontFamily: C.M,
                  fontSize: 16,
                  fontWeight: 500,
                  color: C.purple,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {SPLIT.fee}
              </span>
            </div>

            {/* Footnote */}
            <div style={{ padding: '12px 26px 18px' }}>
              <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>
                • {t('split.note')}
              </span>
            </div>
          </div>
        </ScrubReveal>
      </section>

      {/* ── Tiers — what you get on top (same fee everywhere) ──── */}
      <section style={{ background: C.bg, padding: `clamp(40px, 7vh, 80px) ${HPAD} clamp(56px, 9vh, 104px)` }}>
        <div style={{ maxWidth: 1120, margin: '0 auto' }}>
          <ScrubReveal scrub={0.5}>
            <div className="rs-reveal" style={{ maxWidth: 760, marginBottom: 'clamp(28px, 4vh, 44px)' }}>
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
                {t('tiers.eyebrow')}
              </div>
              <h2
                style={{
                  fontFamily: C.D,
                  fontSize: 'clamp(26px, 3.6vw, 44px)',
                  fontWeight: 500,
                  color: C.text,
                  lineHeight: 1.12,
                  letterSpacing: '-0.02em',
                  margin: '0 0 16px',
                }}
              >
                {t('tiers.title')}
              </h2>
              <p
                style={{
                  fontFamily: C.D,
                  fontSize: 15,
                  lineHeight: 1.6,
                  color: C.sub,
                  margin: 0,
                  maxWidth: 680,
                }}
              >
                {t('tiers.note')}
              </p>
            </div>
          </ScrubReveal>

          <ScrubCascade
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
                  className="rs-card"
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
                        fontFamily: C.M,
                        fontSize: 'clamp(34px, 4vw, 44px)',
                        fontWeight: 500,
                        letterSpacing: '-1px',
                        color: C.text,
                        fontVariantNumeric: 'tabular-nums',
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
          </ScrubCascade>

          {/* Compliance + honest footnote */}
          <ScrubReveal scrub={0.5}>
            <p
              className="rs-reveal"
              style={{
                fontFamily: C.M,
                fontSize: 12,
                lineHeight: 1.6,
                color: C.sub,
                textAlign: 'center',
                maxWidth: 680,
                margin: '40px auto 0',
              }}
            >
              {t('compliance')}
            </p>
            <p
              className="rs-reveal"
              style={{
                fontFamily: C.D,
                fontSize: 13,
                lineHeight: 1.6,
                color: C.sub,
                textAlign: 'center',
                maxWidth: 640,
                margin: '12px auto 0',
              }}
            >
              {t('footnote')}
            </p>
          </ScrubReveal>
        </div>
      </section>
    </main>
  )
}
