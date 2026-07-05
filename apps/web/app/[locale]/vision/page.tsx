import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'

export const metadata: Metadata = {
  title: 'Vision — RSends',
  description:
    "A payment should move money, not hold it. Why RSends settles every payment directly from the customer's wallet to the merchant's wallet.",
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'
const CONTAINER = 1160

// Timeline years are DM Mono figures rendered identically in every locale;
// only the labels are translated.
const TIMELINE_YEARS = [
  { year: '2025', accent: false },
  { year: '2026', accent: false },
  { year: 'NEXT', accent: true },
] as const

const container: React.CSSProperties = {
  maxWidth: CONTAINER,
  margin: '0 auto',
  width: '100%',
}

const eyebrow: React.CSSProperties = {
  fontFamily: C.M,
  fontSize: 11,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: C.purple,
  fontWeight: 500,
}

const body: React.CSSProperties = {
  fontFamily: C.D,
  fontSize: 17,
  lineHeight: 1.65,
  color: C.sub,
  margin: '0 0 18px',
  maxWidth: 640,
}

export default async function VisionPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'vision' })

  const cards = t.raw('cards') as { title: string; body: string }[]
  const timeline = t.raw('timeline') as { label: string }[]

  return (
    <main style={{ background: C.bg }}>
      {/* ── Eyebrow + headline + body ─────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(96px, 16vh, 160px) ${HPAD} clamp(24px, 4vh, 48px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal" style={{ ...eyebrow, marginBottom: 18 }}>
            {t('eyebrow')}
          </div>
          <h1
            className="rs-reveal"
            style={{
              fontFamily: C.D,
              fontSize: 'clamp(32px, 4.2vw, 58px)',
              fontWeight: 400,
              lineHeight: 1.08,
              letterSpacing: '-0.5px',
              color: C.text,
              margin: '0 0 28px',
              maxWidth: 820,
            }}
          >
            {t('title')}
          </h1>
          <p className="rs-reveal" style={body}>{t('body1')}</p>
          <p className="rs-reveal" style={body}>{t('body2')}</p>
          <p className="rs-reveal" style={{ ...body, margin: 0 }}>{t('body3')}</p>
        </ScrubReveal>
      </section>

      {/* ── Terracotta rule + pull line ───────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD} clamp(28px, 5vh, 56px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal">
            <div style={{ width: 26, height: 2, background: C.purple, marginBottom: 18 }} />
            <p
              style={{
                fontFamily: C.D,
                fontSize: 'clamp(22px, 2.6vw, 30px)',
                fontWeight: 500,
                letterSpacing: '-0.02em',
                lineHeight: 1.3,
                color: C.text,
                margin: 0,
                maxWidth: 640,
              }}
            >
              {t('pullLine')}
            </p>
          </div>
        </ScrubReveal>
      </section>

      {/* ── Three-card grid ───────────────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(28px, 5vh, 56px) ${HPAD}` }}>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))',
            gap: 'clamp(16px, 2.5vw, 28px)',
          }}
        >
          {cards.map(card => (
            <div
              key={card.title}
              className="rs-card"
              style={{
                border: `1px solid ${C.border}`,
                borderRadius: 16,
                background: C.surface,
                padding: 'clamp(24px, 3.5vw, 36px)',
              }}
            >
              <h2
                style={{
                  fontFamily: C.D,
                  fontSize: 18,
                  fontWeight: 500,
                  color: C.text,
                  letterSpacing: '-0.01em',
                  margin: '0 0 10px',
                }}
              >
                {card.title}
              </h2>
              <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0 }}>
                {card.body}
              </p>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Timeline — 3 nodes, NEXT in terracotta ────────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD} clamp(28px, 5vh, 56px)` }}>
        {/* Three across everywhere, single column under ~520px — inline styles
            can't express the breakpoint, so the rule lives with the page. */}
        <style>{`
          .rs-vision-timeline { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(20px, 3vw, 36px); }
          @media (max-width: 520px) { .rs-vision-timeline { grid-template-columns: 1fr; } }
        `}</style>
        <ScrubCascade className="rs-vision-timeline">
          {TIMELINE_YEARS.map((node, i) => (
            <div
              key={node.year}
              className="rs-card"
              style={{ position: 'relative', borderTop: `1px solid ${C.border}`, paddingTop: 20 }}
            >
              <div
                aria-hidden="true"
                style={{
                  position: 'absolute',
                  top: -4,
                  left: 0,
                  width: 7,
                  height: 7,
                  borderRadius: 999,
                  background: node.accent ? C.purple : C.text,
                }}
              />
              <div
                style={{
                  fontFamily: C.M,
                  fontSize: 13,
                  fontWeight: 500,
                  letterSpacing: '0.14em',
                  color: node.accent ? C.purple : C.text,
                  marginBottom: 8,
                }}
              >
                {node.year}
              </div>
              <div style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.5, color: C.sub }}>
                {timeline[i]?.label}
              </div>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Quiet cross-link to /team ─────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(32px, 5vh, 56px) ${HPAD} clamp(56px, 9vh, 96px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal" style={{ borderTop: `1px solid ${C.border}`, paddingTop: 'clamp(24px, 4vh, 40px)' }}>
            <Link
              href="/team"
              style={{
                fontFamily: C.D,
                fontSize: 15,
                fontWeight: 500,
                color: C.text,
                textDecoration: 'none',
                borderBottom: `1px solid ${C.border}`,
                paddingBottom: 2,
              }}
            >
              {t('crossLink')} →
            </Link>
          </div>
        </ScrubReveal>
      </section>
    </main>
  )
}
