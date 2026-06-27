import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import MeshHeroVideo from '@/components/pricing/MeshHeroVideo'
import ScrubReveal from '@/components/motion/ScrubReveal'

export const metadata: Metadata = {
  title: 'How It Works — RSends',
  description:
    'How a payment moves through RSends: a hosted checkout or payment link settles on-chain, straight to the merchant’s wallet, routed by an immutable contract that never takes custody.',
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'
const MAXW = 1440 // hero only — full-bleed dark band
const CONTAINER = 1160 // shared width for every section below the hero

// ── Illustrative card data — hard-coded so every locale renders identical
//    DM Mono figures. Addresses/order ids are obviously fake placeholders;
//    the split percentages sum to 100 and the fee is a flat line item, never
//    a percentage. The only REAL figure is the Base Sepolia tx in PROOF.
const CHECKOUT = {
  order: 'Order #8421',
  total: '€49.00',
  method: 'USDC · Base',
  settlesTo: '0x9F…3a2',
} as const

const SPLIT = {
  total: '€49.00',
  rows: [
    { addr: '0x…shop', pct: 88 },
    { addr: '0x…seller', pct: 12 },
  ],
  fee: '€0.15',
} as const

const SETTLE = {
  block: '19,482,113',
  tx: '0x3kd9…',
} as const

// ── REAL on-chain settlement — Base Sepolia (testnet). Framed honestly.
const PROOF_TX = '0x082cc24a5ce0407b3ae44c5dbb568ded14a94714519d9e6fccbde839b2c7a57d'
const PROOF_TX_SHORT = '0x082cc2…b2c7a57d'
const PROOF_URL = `https://sepolia.basescan.org/tx/${PROOF_TX}`

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

export default async function HowItWorksPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'howItWorks' })

  const steps = [
    { key: 'step1', heading: t('step1.heading'), body: t('step1.body'), card: <CheckoutCard /> },
    { key: 'step2', heading: t('step2.heading'), body: t('step2.body'), card: <SplitCard /> },
    { key: 'step3', heading: t('step3.heading'), body: t('step3.body'), card: <SettleCard /> },
  ]

  return (
    <main style={{ background: C.bg }}>
      {/* ── Hero — dark mesh, left-aligned content (mirrors /pricing) ── */}
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

      {/* ── The flow — three steps, copy + rebuilt card ─────────────── */}
      <section style={{ ...container, padding: `clamp(64px, 11vh, 120px) ${HPAD} clamp(24px, 4vh, 48px)` }}>
        <ScrubReveal scrub={0.5}>
          <div
            className="rs-reveal"
            style={{
              fontFamily: C.M,
              fontSize: 11,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: C.purple,
              fontWeight: 500,
            }}
          >
            {t('flowEyebrow')}
          </div>
        </ScrubReveal>
      </section>

      {steps.map((s, i) => (
        <section
          key={s.key}
          style={{ ...container, padding: `clamp(28px, 5vh, 56px) ${HPAD}` }}
        >
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
                <div
                  style={{
                    fontFamily: C.M,
                    fontSize: 12,
                    fontWeight: 500,
                    letterSpacing: '0.14em',
                    color: C.sub,
                    marginBottom: 14,
                  }}
                >
                  {`STEP ${i + 1}`}
                </div>
                <h2 style={{ ...sectionLabel, fontSize: 'clamp(24px, 3vw, 34px)', margin: '0 0 14px' }}>
                  {s.heading}
                </h2>
                <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: 0, maxWidth: 460 }}>
                  {s.body}
                </p>
              </div>

              {/* RIGHT — illustrative card (outer clipped boundary carries the reveal) */}
              {s.card}
            </div>
          </ScrubReveal>
        </section>
      ))}

      {/* ── Real settlement proof — the differentiator ──────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD}` }}>
        <ScrubReveal scrub={0.5}>
          <div
            className="rs-reveal"
            style={{
              border: `1px solid ${C.border}`,
              borderRadius: 16,
              background: C.surface,
              padding: 'clamp(24px, 4vw, 40px)',
            }}
          >
            <div
              style={{
                fontFamily: C.M,
                fontSize: 11,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: C.purple,
                fontWeight: 500,
                marginBottom: 14,
              }}
            >
              {t('proof.eyebrow')}
            </div>
            <h2 style={{ ...sectionLabel, margin: '0 0 12px' }}>{t('proof.title')}</h2>
            <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: '0 0 22px', maxWidth: 680 }}>
              {t('proof.body')}
            </p>

            {/* Network + tx hash — DM Mono */}
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginBottom: 20 }}>
              <span
                style={{
                  fontFamily: C.M,
                  fontSize: 11,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  color: C.sub,
                  background: 'rgba(10,10,10,0.04)',
                  border: `1px solid ${C.border}`,
                  borderRadius: 999,
                  padding: '5px 11px',
                }}
              >
                {t('proof.network')}
              </span>
              <a
                href={PROOF_URL}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontFamily: C.M,
                  fontSize: 14,
                  color: C.text,
                  textDecoration: 'none',
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                {PROOF_TX_SHORT}
              </a>
            </div>

            <a
              href={PROOF_URL}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-block',
                fontFamily: C.D,
                fontSize: 15,
                fontWeight: 600,
                color: C.purple,
                textDecoration: 'none',
              }}
            >
              {t('proof.cta')}
            </a>
          </div>
        </ScrubReveal>
      </section>

      {/* ── Closing CTA — to pricing + open the app ─────────────────── */}
      <section style={{ ...container, padding: `clamp(32px, 5vh, 56px) ${HPAD} clamp(56px, 9vh, 96px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal" style={{ borderTop: `1px solid ${C.border}`, paddingTop: 'clamp(28px, 4vh, 44px)' }}>
            <h2
              style={{
                fontFamily: C.D,
                fontSize: 'clamp(24px, 3vw, 36px)',
                fontWeight: 500,
                color: C.text,
                letterSpacing: '-0.02em',
                lineHeight: 1.14,
                margin: '0 0 12px',
                maxWidth: 640,
              }}
            >
              {t('cta.title')}
            </h2>
            <p style={{ fontFamily: C.D, fontSize: 16, lineHeight: 1.6, color: C.sub, margin: '0 0 26px', maxWidth: 560 }}>
              {t('cta.body')}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14 }}>
              <Link
                href="/pricing"
                style={{
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
                {t('cta.pricing')}
              </Link>
              <Link
                href="/login"
                style={{
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
                {t('cta.secondary')}
              </Link>
            </div>
          </div>
        </ScrubReveal>
      </section>
    </main>
  )
}

// ── Illustrative cards — rebuilt natively (no canvas import). Flat surfaces,
//    thin border, no glow. DM Mono on amounts/addresses/hashes only. Each card
//    is the outermost clipped boundary so the .rs-reveal lives on it and inner
//    rows stay static (never translate inside overflow:hidden). ────────────────

function cardShell(): React.CSSProperties {
  return {
    background: C.surface,
    border: `1px solid ${C.border}`,
    borderRadius: 24,
    overflow: 'hidden',
  }
}

const rowPad = '16px 24px'

function CheckoutCard() {
  return (
    <div className="rs-reveal" style={cardShell()}>
      {/* Header — order + total */}
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
        <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text }}>{CHECKOUT.order}</span>
        <span style={{ fontFamily: C.M, fontSize: 18, fontWeight: 500, color: C.text, fontVariantNumeric: 'tabular-nums' }}>
          {CHECKOUT.total}
        </span>
      </div>
      {/* Method */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: rowPad }}>
        <span style={{ fontFamily: C.D, fontSize: 14, color: C.sub }}>Pay with</span>
        <span style={{ fontFamily: C.M, fontSize: 14, color: C.text }}>{CHECKOUT.method}</span>
      </div>
      {/* Settles to */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: rowPad,
          borderTop: `1px solid ${C.border}`,
        }}
      >
        <span style={{ fontFamily: C.D, fontSize: 14, color: C.sub }}>Settles to</span>
        <span style={{ fontFamily: C.M, fontSize: 14, color: C.text }}>{CHECKOUT.settlesTo}</span>
      </div>
      {/* Pay button — visual only, non-functional */}
      <div style={{ padding: '18px 24px', borderTop: `1px solid ${C.border}` }}>
        <div
          role="button"
          aria-disabled="true"
          style={{
            display: 'block',
            textAlign: 'center',
            fontFamily: C.D,
            fontSize: 15,
            fontWeight: 600,
            padding: '13px 24px',
            borderRadius: 8,
            background: C.text,
            color: C.bg,
            cursor: 'default',
            userSelect: 'none',
          }}
        >
          Pay {CHECKOUT.total}
        </div>
      </div>
    </div>
  )
}

function SplitCard() {
  return (
    <div>
    <div className="rs-reveal" style={cardShell()}>
      {/* Header — label + total */}
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
          <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, letterSpacing: '0.18em', color: C.text }}>
            SPLIT
          </span>
          <span style={{ color: C.sub }}>·</span>
          <span style={{ fontFamily: C.M, fontSize: 18, fontWeight: 500, color: C.text, fontVariantNumeric: 'tabular-nums' }}>
            {SPLIT.total}
          </span>
        </div>
      </div>

      {/* Split rows — sum to 100% */}
      <div style={{ padding: '18px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {SPLIT.rows.map((r) => (
          <div key={r.addr} style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontFamily: C.M, fontSize: 14, color: C.text, width: 92, flexShrink: 0 }}>{r.addr}</span>
            <div
              aria-hidden="true"
              style={{ flex: 1, height: 8, borderRadius: 999, background: 'var(--rs-wash)', overflow: 'hidden' }}
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
          padding: rowPad,
          borderTop: `1px solid ${C.border}`,
          background: 'rgba(200,81,44,0.04)',
        }}
      >
        <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 500, color: C.text }}>RSends fee</span>
        <span style={{ fontFamily: C.M, fontSize: 16, fontWeight: 500, color: C.purple, fontVariantNumeric: 'tabular-nums' }}>
          {SPLIT.fee}
        </span>
      </div>

      <div style={{ padding: '12px 24px 18px' }}>
        <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>• routed in 1 tx</span>
      </div>
    </div>
    <p style={splitCaption}>Illustrative example — not real customer data.</p>
    </div>
  )
}

function SettleCard() {
  return (
    <div className="rs-reveal" style={cardShell()}>
      {/* Header — confirmed */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '20px 24px',
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 999, background: C.green, flexShrink: 0 }} />
        <span style={{ fontFamily: C.D, fontSize: 15, fontWeight: 600, color: C.text }}>Confirmed</span>
      </div>
      {/* Block */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: rowPad }}>
        <span style={{ fontFamily: C.D, fontSize: 14, color: C.sub }}>Block</span>
        <span style={{ fontFamily: C.M, fontSize: 14, color: C.text, fontVariantNumeric: 'tabular-nums' }}>
          {SETTLE.block}
        </span>
      </div>
      {/* Tx */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: rowPad,
          borderTop: `1px solid ${C.border}`,
        }}
      >
        <span style={{ fontFamily: C.D, fontSize: 14, color: C.sub }}>Tx</span>
        <span style={{ fontFamily: C.M, fontSize: 14, color: C.text }}>{SETTLE.tx}</span>
      </div>
      {/* Custody none — emphasized */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: rowPad,
          borderTop: `1px solid ${C.border}`,
          background: 'rgba(200,81,44,0.04)',
        }}
      >
        <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text }}>Custody</span>
        <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.purple }}>none</span>
      </div>
    </div>
  )
}

// ── Shared style helpers ────────────────────────────────────────────────────
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
