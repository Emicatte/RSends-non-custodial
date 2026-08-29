'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import { LandingAuthButtons } from '@/components/auth/LandingAuthButtons'

// Flat marketing nav.
const NAV_LINKS = [
  { key: 'howItWorks', href: '/how-it-works' },
  { key: 'pricing', href: '/pricing' },
  { key: 'vision', href: '/vision' },
  { key: 'team', href: '/team' },
] as const

/**
 * The liquid-glass marketing header (extracted from the home page) plus the
 * flat page nav. Rendered on every marketing route via HeaderMount.
 *
 * Responsive behavior lives in CSS (not a JS resize listener) so the server
 * markup is already correct at every width: inline links ≥1024px, a minimal
 * disclosure toggle below. The collapse point is 1024 (not 768) because the
 * centered link row plus the side clusters need ~860px in the widest locale
 * (fr) before they collide.
 */
export default function MarketingNav() {
  const t = useTranslations('nav')
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState<string | null>(null)

  const linkStyle = (key: string): React.CSSProperties => ({
    fontFamily: C.D,
    fontSize: 14,
    fontWeight: 500,
    letterSpacing: '-0.01em',
    color: hovered === key ? C.purple : C.text,
    textDecoration: 'none',
    transition: 'color 150ms ease',
  })

  return (
    <nav
      className="bf-blur-24s rs-mnav"
      style={{
        position: 'fixed', top: 3, left: 0, right: 0, zIndex: 1000,
        paddingTop: 'var(--sat, 0px)',
        background: 'rgba(250,250,250,0.85)',
        borderBottom: '1px solid rgba(10,10,10,0.08)',
      }}
    >
      <style>{`
        /* ≥1024: 3-region grid — equal 1fr flanks keep the link row truly
           centered in the viewport regardless of logo / control widths.
           Below 1024 the links collapse into the toggle, so the header falls
           back to the plain logo↔controls flex row (a 1fr flank would starve
           the control cluster on narrow screens). */
        .rs-mnav { height: 60px; padding-left: 24px; padding-right: 24px;
                   display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; }
        .rs-mnav-links { display: flex; align-items: center; gap: 28px; }
        .rs-mnav-toggle { display: none; }
        @media (max-width: 1023px) {
          .rs-mnav { display: flex; justify-content: space-between; }
          .rs-mnav-links { display: none; }
          .rs-mnav-toggle { display: inline-flex; }
        }
        @media (max-width: 767px) {
          .rs-mnav { height: 52px; padding-left: 12px; padding-right: 12px; }
        }
      `}</style>

      {/* Left: logo → locale home */}
      <div style={{ display: 'flex', alignItems: 'center', justifySelf: 'start' }}>
        <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          <img src="/favicon.svg" alt="RSends" width={28} height={28} style={{ borderRadius: 7 }} />
          <span style={{ fontFamily: C.D, fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: '-0.03em' }}>
            RSends
          </span>
        </Link>
      </div>

      {/* Center: inline flat nav, viewport-centered between the side clusters */}
      <div className="rs-mnav-links">
        {NAV_LINKS.map(link => (
          <Link
            key={link.key}
            href={link.href}
            style={linkStyle(link.key)}
            onMouseEnter={() => setHovered(link.key)}
            onMouseLeave={() => setHovered(null)}
          >
            {t(link.key)}
          </Link>
        ))}
      </div>

      {/* Right: language + auth, plus the mobile disclosure toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifySelf: 'end', gridColumn: 3 }}>
        <LanguageSwitcher />
        <LandingAuthButtons />
        <button
          type="button"
          className="rs-mnav-toggle"
          aria-label="Menu"
          aria-expanded={open}
          aria-controls="rs-mnav-panel"
          onClick={() => setOpen(prev => !prev)}
          style={{
            alignItems: 'center', justifyContent: 'center',
            width: 36, height: 36, padding: 0,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: C.text,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
            {open ? (
              <path d="M4 4l10 10M14 4L4 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            ) : (
              <path d="M2 6h14M2 12h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile disclosure panel */}
      {open && (
        <div
          id="rs-mnav-panel"
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0,
            background: 'rgba(250,250,250,0.97)',
            borderBottom: '1px solid rgba(10,10,10,0.08)',
            display: 'flex', flexDirection: 'column',
            padding: '8px 12px 14px',
            gap: 4,
          }}
        >
          {NAV_LINKS.map(link => (
            <Link
              key={link.key}
              href={link.href}
              onClick={() => setOpen(false)}
              style={{
                fontFamily: C.D, fontSize: 15, fontWeight: 500,
                color: C.text, textDecoration: 'none',
                padding: '10px 4px',
                borderBottom: '1px solid rgba(10,10,10,0.06)',
              }}
            >
              {t(link.key)}
            </Link>
          ))}
        </div>
      )}
    </nav>
  )
}
