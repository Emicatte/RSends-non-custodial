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
const MAXW = 1440 // hero only — full-bleed dark band
const CONTAINER = 1160 // shared width for every section below the hero

// ── Fee model — single source of truth. Figures hard-coded so every locale
//    renders identical numbers (DM Mono). The % columns are illustrative
//    reference points, not any named provider's tariff. NEVER a % of volume.
const COMPARISON_ROWS = [
  { payment: '€50', rsends: '€0.15', p1: '€0.50', p29: '€1.45' },
  { payment: '€1,200', rsends: '€1.15', p1: '€12.00', p29: '€34.80' },
  { payment: '€50,000', rsends: '€1.15', p1: '€500.00', p29: '€1,450.00' },
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

const section: React.CSSProperties = {
  maxWidth: MAXW,
  margin: '0 auto',
  width: '100%',
}

const container: React.CSSProperties = {
  maxWidth: CONTAINER,
  margin: '0 auto',
  width: '100%',
}

export default async function PricingPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'pricing' })
  const details = t.raw('details.items') as { label: string; value: string }[]
  const faqs = t.raw('faq.items') as { q: string; a: string }[]

  return (
    <main style={{ background: C.bg }}>
      {/* ── Hero — dark mesh, left-aligned content ─────────────── */}
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
        <div
          aria-hidden="true"
          style={{ position: 'absolute', inset: 0, background: 'rgba(10,10,12,0.45)', zIndex: 1 }}
        />
        <div style={{ ...section, position: 'relative', zIndex: 2, padding: `0 ${HPAD}` }}>
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
            {t('feeModel.eyebrow')}
          </div>
          <h1
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(34px, 4.6vw, 64px)',
              fontWeight: 400,
              lineHeight: 1.06,
              letterSpacing: '-0.5px',
              color: '#FFFFFF',
              margin: 0,
              maxWidth: 880,
            }}
          >
            {t('feeModel.title')}
          </h1>
          <p
            style={{
              fontFamily: C.D,
              fontSize: 18,
              lineHeight: 1.6,
              color: 'rgba(255,255,255,0.8)',
              margin: '22px 0 0',
              maxWidth: 620,
            }}
          >
            {t('feeModel.subtitle')}
          </p>
        </div>
      </section>

      {/* ── Comparison table — the centerpiece ─────────────────── */}
      <section style={{ ...container, padding: `clamp(64px, 11vh, 120px) ${HPAD} clamp(40px, 7vh, 72px)` }}>
        <ScrubReveal scrub={0.5}>
          <h2
            className="rs-reveal"
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(26px, 3.4vw, 42px)',
              fontWeight: 500,
              color: C.text,
              lineHeight: 1.14,
              letterSpacing: '-0.02em',
              margin: '0 0 28px',
              maxWidth: 760,
            }}
          >
            {t('comparison.title')}
          </h2>

          {/* boundary div carries the reveal; inner scroll wrapper is its child */}
          <div className="rs-reveal">
            <div style={{ overflowX: 'auto', border: `1px solid ${C.border}`, borderRadius: 16, background: C.surface }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 640 }}>
                <thead>
                  <tr>
                    <th style={thStyle('left', false)}>{t('comparison.colPayment')}</th>
                    <th style={thStyle('right', true)}>{t('comparison.colRsends')}</th>
                    <th style={thStyle('right', false)}>
                      {t('comparison.col1')}{' '}
                      <span style={illoStyle}>({t('comparison.illustrative')})</span>
                    </th>
                    <th style={thStyle('right', false)}>
                      {t('comparison.col29')}{' '}
                      <span style={illoStyle}>({t('comparison.illustrative')})</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {COMPARISON_ROWS.map((r, i) => {
                    const last = i === COMPARISON_ROWS.length - 1
                    return (
                      <tr key={r.payment}>
                        <td style={tdNum(last, 'left', false, C.text)}>{r.payment}</td>
                        <td style={tdNum(last, 'right', true, C.purple)}>{r.rsends}</td>
                        <td style={tdNum(last, 'right', false, C.sub)}>{r.p1}</td>
                        <td style={tdNum(last, 'right', false, C.sub)}>{r.p29}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <p
            className="rs-reveal"
            style={{
              fontFamily: C.D,
              fontSize: 14,
              lineHeight: 1.6,
              color: C.sub,
              margin: '18px 0 0',
              maxWidth: 760,
            }}
          >
            {t('comparison.caption')}
          </p>
        </ScrubReveal>
      </section>

      {/* ── Fee details strip ──────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(24px, 4vh, 48px) ${HPAD}` }}>
        <ScrubReveal scrub={0.5}>
          <h2 className="rs-reveal" style={sectionLabel}>
            {t('details.title')}
          </h2>
        </ScrubReveal>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 16,
          }}
        >
          {details.map((d, i) => (
            <div
              key={i}
              className="rs-card"
              style={{
                background: C.surface,
                border: `1px solid ${C.border}`,
                borderRadius: 12,
                padding: '20px 22px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text }}>
                {d.label}
              </span>
              <span style={{ fontFamily: C.D, fontSize: 14, lineHeight: 1.5, color: C.sub }}>
                {d.value}
              </span>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Split illustration ─────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 72px) ${HPAD}` }}>
        <ScrubReveal scrub={0.5}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
              gap: 'clamp(32px, 5vw, 64px)',
              alignItems: 'center',
            }}
          >
            {/* LEFT — copy */}
            <div className="rs-reveal">
              <h2 style={{ ...sectionLabel, margin: '0 0 14px' }}>{t('split.heading')}</h2>
              <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 440 }}>
                {t('split.body')}
              </p>
            </div>

            {/* RIGHT — Split card. The card is the outermost (clipped) boundary,
                so the reveal lives here; inner rows stay static (no translate
                inside overflow:hidden). */}
            <div
              className="rs-reveal"
              style={{
                background: C.surface,
                border: `1px solid ${C.border}`,
                borderRadius: 24,
                overflow: 'hidden',
              }}
            >
            {/* Header */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                padding: '20px 24px',
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
                  fontSize: 9.5,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: C.sub,
                  background: 'rgba(10,10,10,0.04)',
                  border: `1px solid ${C.border}`,
                  borderRadius: 999,
                  padding: '4px 9px',
                  textAlign: 'right',
                }}
              >
                {t('split.disclaimer')}
              </span>
            </div>

            {/* Split rows — sum to 100% */}
            <div style={{ padding: '18px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
              {SPLIT.rows.map((r) => (
                <div key={r.addr} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <span
                    style={{ fontFamily: C.M, fontSize: 14, color: C.text, width: 92, flexShrink: 0 }}
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
                    <div style={{ width: `${r.pct}%`, height: '100%', borderRadius: 999, background: C.purple }} />
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
                padding: '16px 24px',
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

            <div style={{ padding: '12px 24px 18px' }}>
              <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>• {t('split.note')}</span>
            </div>
            </div>
          </div>
        </ScrubReveal>
      </section>

      {/* ── Tiers — what you get on top (same fee everywhere) ──── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD}` }}>
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
            <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 720 }}>
              {t('tiers.note')}
            </p>
          </div>
        </ScrubReveal>

        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
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
                }}
              >
                {isPro && (
                  <span
                    style={{
                      alignSelf: 'flex-start',
                      fontFamily: C.D,
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

                <h3 style={{ fontFamily: C.D, fontSize: 18, fontWeight: 600, color: C.text, margin: '0 0 6px' }}>
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
                  {period && <span style={{ fontFamily: C.D, fontSize: 15, color: C.sub }}>{period}</span>}
                </div>

                <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.55, color: C.sub, margin: '0 0 22px' }}>
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
      </section>

      {/* ── FAQ — always-open, left-aligned 2-col grid ─────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD}` }}>
        <ScrubReveal scrub={0.5}>
          <h2 className="rs-reveal" style={{ ...sectionLabel, marginBottom: 'clamp(24px, 4vh, 40px)' }}>
            {t('faq.title')}
          </h2>
        </ScrubReveal>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
            gap: 'clamp(24px, 3vw, 44px)',
          }}
        >
          {faqs.map((f, i) => (
            <div key={i} className="rs-card">
              <h3 style={{ fontFamily: C.D, fontSize: 16, fontWeight: 600, color: C.text, margin: '0 0 8px' }}>
                {f.q}
              </h3>
              <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 520 }}>
                {f.a}
              </p>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Footer disclaimer ──────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(32px, 5vh, 56px) ${HPAD} clamp(56px, 9vh, 96px)` }}>
        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 28 }}>
          <p style={{ fontFamily: C.M, fontSize: 12, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 760 }}>
            {t('compliance')}
          </p>
          <p style={{ fontFamily: C.D, fontSize: 13, lineHeight: 1.6, color: C.sub, margin: '12px 0 0', maxWidth: 760 }}>
            {t('footnote')}
          </p>
        </div>
      </section>
    </main>
  )
}

// ── Shared style helpers (kept out of JSX for readability) ──────────────────
const sectionLabel: React.CSSProperties = {
  fontFamily: C.D,
  fontSize: 'clamp(20px, 2.4vw, 28px)',
  fontWeight: 500,
  color: C.text,
  letterSpacing: '-0.01em',
  margin: '0 0 20px',
}

const illoStyle: React.CSSProperties = {
  fontFamily: C.D,
  fontSize: 11,
  fontWeight: 400,
  letterSpacing: 0,
  color: C.sub,
  textTransform: 'none',
}

function thStyle(align: 'left' | 'right', emphasized: boolean): React.CSSProperties {
  return {
    textAlign: align,
    padding: '16px 20px',
    fontFamily: C.D,
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    color: emphasized ? C.purple : C.sub,
    background: emphasized ? 'rgba(200,81,44,0.04)' : 'transparent',
    borderBottom: `1px solid ${C.border}`,
    whiteSpace: 'nowrap',
  }
}

function tdNum(last: boolean, align: 'left' | 'right', emphasized: boolean, color: string): React.CSSProperties {
  return {
    textAlign: align,
    padding: '18px 20px',
    fontFamily: C.M,
    fontSize: 'clamp(16px, 1.6vw, 19px)',
    fontWeight: emphasized ? 600 : 400,
    color,
    background: emphasized ? 'rgba(200,81,44,0.04)' : 'transparent',
    borderBottom: last ? 'none' : `1px solid ${C.border}`,
    fontVariantNumeric: 'tabular-nums',
    whiteSpace: 'nowrap',
  }
}
