import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'
import MediaHero from '@/components/marketing/MediaHero'

export const metadata: Metadata = {
  title: 'Vision — RSends',
  description:
    "A payment should move money, not hold it. Why RSends settles every payment directly from the customer's wallet to the merchant's wallet.",
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'
const CONTAINER = 1160

// Phase labels/titles/bodies come from vision.timeline; only the accent
// (terracotta NEXT node) is structural.
const TIMELINE_PHASES = [{ accent: false }, { accent: false }, { accent: true }] as const

// Mirrors team/page.tsx (pages can't import from pages). Every locale keeps
// the literal "BaseScan" in the phase-01 body so the split anchors it.
const ROUTER_ADDRESS = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'
const CONTRACT_URL = `https://sepolia.basescan.org/address/${ROUTER_ADDRESS}`

function linkifyBaseScan(text: string) {
  const parts = text.split('BaseScan')
  return parts.flatMap((part, i) =>
    i === 0
      ? [part]
      : [
          <a
            key={i}
            href={CONTRACT_URL}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: C.text, textDecoration: 'none', borderBottom: `1px solid ${C.border}` }}
          >
            BaseScan
          </a>,
          part,
        ],
  )
}

const container: React.CSSProperties = {
  maxWidth: CONTAINER,
  margin: '0 auto',
  width: '100%',
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
  const tHiw = await getTranslations({ locale, namespace: 'howItWorks' })

  const cards = t.raw('cards') as { title: string; body: string }[]
  const timeline = t.raw('timeline') as { label: string; title: string; body: string }[]

  return (
    <main style={{ background: C.bg }}>
      {/* ── Hero — shared dark video hero (see components/marketing/MediaHero,
             mirrors the pricing / how-it-works mesh hero incl. no-flash) ──── */}
      <MediaHero
        eyebrow={t('eyebrow')}
        title={t('title')}
        subline={t('hero.subline')}
        videoSrc="/vision/hero-bg.mp4"
        poster="/vision/hero-poster.jpg"
      />

      {/* ── Editorial — the three paragraphs, on paper ─────────────────── */}
      <section style={{ ...container, padding: `clamp(72px, 12vh, 128px) ${HPAD} clamp(24px, 4vh, 48px)` }}>
        <ScrubReveal scrub={0.5}>
          <p className="rs-reveal" style={body}>{t('body1')}</p>
          <p className="rs-reveal" style={body}>{t('body2')}</p>
          <p className="rs-reveal" style={{ ...body, margin: 0 }}>{t('body3')}</p>
        </ScrubReveal>
      </section>

      {/* ── Terracotta rule + pull line, display scale ─────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD} clamp(28px, 5vh, 56px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal">
            <div style={{ width: 26, height: 2, background: C.purple, marginBottom: 18 }} />
            <p
              style={{
                fontFamily: C.D,
                fontSize: 'clamp(28px, 3.2vw, 44px)',
                fontWeight: 500,
                letterSpacing: '-0.02em',
                lineHeight: 1.25,
                color: C.text,
                margin: 0,
                maxWidth: 760,
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

      {/* ── Phase timeline — 3 cards on a rail, NEXT in terracotta ────── */}
      <section style={{ ...container, padding: `clamp(48px, 8vh, 96px) ${HPAD} clamp(28px, 5vh, 56px)` }}>
        {/* Continuous rail across the container; vertical rail under 480px.
            Inline styles can't express the breakpoint, so the rule lives with
            the page. The rail is not a .rs-card, so ScrubCascade leaves it
            static while dot + card cascade together per phase. */}
        <style>{`
          .rs-vision-timeline { position: relative; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: clamp(20px, 3vw, 36px); }
          .rs-vision-timeline-rail { position: absolute; top: 5px; left: 0; right: 0; height: 1px; background: ${C.border}; }
          .rs-vision-tl-item { position: relative; padding-top: 26px; }
          .rs-vision-tl-dot { position: absolute; top: 0; left: 0; width: 11px; height: 11px; border-radius: 999px; }
          @media (max-width: 480px) {
            .rs-vision-timeline { grid-template-columns: 1fr; gap: 30px; padding-left: 24px; }
            .rs-vision-timeline-rail { top: 2px; bottom: 2px; left: 5px; right: auto; width: 1px; height: auto; }
            .rs-vision-tl-item { padding-top: 0; }
            .rs-vision-tl-dot { left: -24px; top: 3px; }
          }
        `}</style>
        <ScrubCascade className="rs-vision-timeline">
          <div className="rs-vision-timeline-rail" aria-hidden="true" />
          {TIMELINE_PHASES.map((node, i) => (
            <div key={timeline[i]?.label ?? i} className="rs-card rs-vision-tl-item">
              <div
                aria-hidden="true"
                className="rs-vision-tl-dot"
                style={{ background: node.accent ? C.purple : C.text }}
              />
              <div
                style={{
                  border: `1px solid ${C.border}`,
                  borderRadius: 16,
                  background: C.surface,
                  padding: 'clamp(24px, 3.5vw, 36px)',
                  height: '100%',
                }}
              >
                <div
                  style={{
                    fontFamily: C.M,
                    fontSize: 13,
                    fontWeight: 500,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    color: node.accent ? C.purple : C.text,
                    marginBottom: 12,
                  }}
                >
                  {timeline[i]?.label}
                </div>
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
                  {timeline[i]?.title}
                </h2>
                <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0 }}>
                  {i === 0 ? linkifyBaseScan(timeline[i]?.body ?? '') : timeline[i]?.body}
                </p>
              </div>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Closing band — pricing CTA + quiet team link ───────────────── */}
      <section style={{ ...container, padding: `clamp(32px, 5vh, 56px) ${HPAD} clamp(56px, 9vh, 96px)` }}>
        <ScrubReveal scrub={0.5}>
          <div
            className="rs-reveal"
            style={{
              borderTop: `1px solid ${C.border}`,
              paddingTop: 'clamp(28px, 4vh, 44px)',
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: 'clamp(16px, 3vw, 28px)',
            }}
          >
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
              {tHiw('cta.pricing')}
            </Link>
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
