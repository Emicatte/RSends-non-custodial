import type { Metadata } from 'next'
import { getTranslations } from 'next-intl/server'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import ScrubReveal from '@/components/motion/ScrubReveal'
import ScrubCascade from '@/components/motion/ScrubCascade'

export const metadata: Metadata = {
  title: 'Team — RSends',
  description:
    'RSends is two people. Who builds the platform, and why you shouldn’t have to trust us with your funds.',
}

type PageProps = { params: Promise<{ locale: string }> }

const HPAD = 'clamp(20px, 6vw, 96px)'
const CONTAINER = 1160

const ROUTER_ADDRESS = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'
const CONTRACT_URL = `https://sepolia.basescan.org/address/${ROUTER_ADDRESS}`

// Names, initials, role labels and philosophy numbers are DM Mono / identity
// figures rendered identically in every locale; only bios and card copy are
// translated.
const PROFILES = [
  { initial: 'E', name: 'Emilio', role: 'CO-FOUNDER · LEAD ENGINEER' },
  { initial: 'S', name: 'Stefano', role: 'CO-FOUNDER · LEGAL & COMMERCIAL' },
] as const

const PHILOSOPHY_NUMS = ['01', '02', '03', '04'] as const

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

const card: React.CSSProperties = {
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  background: C.surface,
  padding: 'clamp(24px, 3.5vw, 36px)',
}

/** Wrap every "BaseScan" mention in an external link to the verified contract. */
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

export default async function TeamPage({ params }: PageProps) {
  const { locale } = await params
  const t = await getTranslations({ locale, namespace: 'team' })

  const profiles = t.raw('profiles') as { bio: string }[]
  const philosophy = t.raw('philosophy') as { title: string; body: string }[]

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
          <p className="rs-reveal" style={body}>{linkifyBaseScan(t('body2'))}</p>
          <p className="rs-reveal" style={{ ...body, margin: 0 }}>{t('body3')}</p>
        </ScrubReveal>
      </section>

      {/* ── Profile cards ─────────────────────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(40px, 7vh, 80px) ${HPAD} clamp(28px, 5vh, 56px)` }}>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))',
            gap: 'clamp(16px, 2.5vw, 28px)',
          }}
        >
          {PROFILES.map((profile, i) => (
            <div key={profile.name} className="rs-card" style={card}>
              <div
                aria-hidden="true"
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: 10,
                  background: C.text,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontFamily: C.M,
                  fontSize: 26,
                  fontWeight: 500,
                  color: C.bg,
                  marginBottom: 20,
                }}
              >
                {profile.initial}
              </div>
              <h2
                style={{
                  fontFamily: C.D,
                  fontSize: 19,
                  fontWeight: 500,
                  color: C.text,
                  letterSpacing: '-0.01em',
                  margin: '0 0 6px',
                }}
              >
                {profile.name}
              </h2>
              <div
                style={{
                  fontFamily: C.M,
                  fontSize: 11,
                  fontWeight: 500,
                  letterSpacing: '0.14em',
                  color: C.sub,
                  marginBottom: 14,
                }}
              >
                {profile.role}
              </div>
              <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0 }}>
                {profiles[i]?.bio}
              </p>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Philosophy — label + 2×2 card grid ────────────────────────── */}
      <section style={{ ...container, padding: `clamp(28px, 5vh, 56px) ${HPAD} clamp(12px, 2vh, 24px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal" style={eyebrow}>
            {t('philosophyLabel')}
          </div>
        </ScrubReveal>
      </section>
      <section style={{ ...container, padding: `0 ${HPAD} clamp(28px, 5vh, 56px)` }}>
        <ScrubCascade
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 420px), 1fr))',
            gap: 'clamp(16px, 2.5vw, 28px)',
          }}
        >
          {philosophy.map((item, i) => (
            <div key={item.title} className="rs-card" style={card}>
              <div
                style={{
                  fontFamily: C.M,
                  fontSize: 13,
                  fontWeight: 500,
                  letterSpacing: '0.14em',
                  color: C.purple,
                  marginBottom: 12,
                }}
              >
                {PHILOSOPHY_NUMS[i]}
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
                {item.title}
              </h2>
              <p style={{ fontFamily: C.D, fontSize: 15, lineHeight: 1.6, color: C.sub, margin: 0 }}>
                {linkifyBaseScan(item.body)}
              </p>
            </div>
          ))}
        </ScrubCascade>
      </section>

      {/* ── Quiet cross-link to /vision ───────────────────────────────── */}
      <section style={{ ...container, padding: `clamp(32px, 5vh, 56px) ${HPAD} clamp(56px, 9vh, 96px)` }}>
        <ScrubReveal scrub={0.5}>
          <div className="rs-reveal" style={{ borderTop: `1px solid ${C.border}`, paddingTop: 'clamp(24px, 4vh, 40px)' }}>
            <Link
              href="/vision"
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
