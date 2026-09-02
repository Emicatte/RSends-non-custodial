import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { C } from '@/app/designTokens'
import MeshHeroVideo from '@/components/pricing/MeshHeroVideo'
import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'

export const metadata: Metadata = {
  title: 'Pricing — RSends',
  description:
    'RSends is a flat monthly software subscription — no per-transaction fee from mainnet launch. The price is sized to your volume and agreed at onboarding.',
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'
const MAXW = 1440 // hero only — full-bleed dark band
const CONTAINER = 1160 // shared width for every section below the hero

// Illustrative split — percentages sum to 100. The amounts are a sample
// payment, not RSends pricing (subscription pricing is agreed per merchant
// at onboarding and never shown as a public figure). Address labels are
// obviously fake placeholders.
const SPLIT = {
  total: '€49.00',
  rows: [
    { addr: '0x…shop', pct: 88 },
    { addr: '0x…seller', pct: 12 },
  ],
} as const

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
  const includes = t.raw('includes.items') as { label: string; value: string }[]
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
            {t('hero.eyebrow')}
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
            {t('hero.title')}
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
            {t('hero.subtitle')}
          </p>
        </div>
      </section>

      {/* ── Flat vs percentage — qualitative, no figures ───────── */}
      <section style={{ ...container, padding: `clamp(64px, 11vh, 120px) ${HPAD} clamp(40px, 7vh, 72px)` }}>
        <ScrubReveal>
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
            {t('model.title')}
          </h2>
        </ScrubReveal>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 20,
          }}
        >
          {(['percent', 'flat'] as const).map((key) => {
            const emphasized = key === 'flat'
            return (
              <div
                key={key}
                className="rs-card"
                style={{
                  background: C.surface,
                  border: emphasized ? `1.5px solid ${C.purple}` : `1px solid ${C.border}`,
                  borderRadius: 16,
                  padding: '28px 30px',
                }}
              >
                <h3
                  style={{
                    fontFamily: C.D,
                    fontSize: 16,
                    fontWeight: 600,
                    color: emphasized ? C.purple : C.text,
                    margin: '0 0 10px',
                  }}
                >
                  {t(`model.${key}.label`)}
                </h3>
                <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0 }}>
                  {t(`model.${key}.body`)}
                </p>
              </div>
            )
          })}
        </ScrubCascade>
      </section>

      {/* ── What the subscription includes ─────────────────────── */}
      <section style={{ ...container, padding: `clamp(24px, 4vh, 48px) ${HPAD}` }}>
        <ScrubReveal>
          <h2 className="rs-reveal" style={sectionLabel}>
            {t('includes.title')}
          </h2>
        </ScrubReveal>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
            gap: 16,
          }}
        >
          {includes.map((d, i) => (
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

      {/* ── Talk to us — the one offer, priced at onboarding ───── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 72px) ${HPAD}` }}>
        <ScrubReveal>
          <div
            className="rs-reveal"
            style={{
              background: C.surface,
              border: `1.5px solid ${C.purple}`,
              borderRadius: 16,
              padding: 'clamp(28px, 4vw, 44px)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              gap: 14,
            }}
          >
            <h2
              style={{
                fontFamily: C.D,
                fontSize: 'clamp(22px, 2.8vw, 32px)',
                fontWeight: 500,
                color: C.text,
                letterSpacing: '-0.01em',
                margin: 0,
              }}
            >
              {t('talk.title')}
            </h2>
            <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 640 }}>
              {t('talk.body')}
            </p>
            <a
              href="mailto:emiliocatteddu@gmail.com"
              style={{
                display: 'inline-block',
                textAlign: 'center',
                fontFamily: C.D,
                fontSize: 15,
                fontWeight: 600,
                padding: '13px 28px',
                borderRadius: 8,
                textDecoration: 'none',
                background: C.text,
                color: C.bg,
                marginTop: 6,
              }}
            >
              {t('talk.cta')}
            </a>
          </div>
        </ScrubReveal>
      </section>

      {/* ── Split illustration ─────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 72px) ${HPAD}` }}>
        <ScrubReveal>
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

            {/* RIGHT — Split card + quiet disclosure caption below it. The card
                is the outermost (clipped) boundary, so the reveal lives there;
                inner rows stay static (no translate inside overflow:hidden). The
                caption is a plain always-visible line (required honesty note). */}
            <div>
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

            <div style={{ padding: '12px 24px 18px', borderTop: `1px solid ${C.border}` }}>
              <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>• {t('split.note')}</span>
            </div>
            </div>
            <p style={splitCaption}>{t('split.disclaimer')}</p>
            </div>
          </div>
        </ScrubReveal>
      </section>

      {/* ── FAQ — always-open, left-aligned 2-col grid ─────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD}` }}>
        <ScrubReveal>
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

const splitCaption: React.CSSProperties = {
  fontFamily: C.M,
  fontSize: 11,
  lineHeight: 1.5,
  color: C.sub,
  letterSpacing: 0,
  margin: '10px 0 0',
}
