'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'
import { C } from '@/app/designTokens'
import LanguageSwitcher from '@/components/LanguageSwitcher'
import { LandingAuthButtons } from '@/components/auth/LandingAuthButtons'

// Flat marketing nav. Team is deliberately excluded (footer only) until its
// page is redesigned.
const NAV_LINKS = [
  { key: 'howItWorks', href: '/how-it-works' },
  { key: 'pricing', href: '/pricing' },
  { key: 'vision', href: '/vision' },
] as const

/**
 * The liquid-glass marketing header (extracted from the home page) plus the
 * flat page nav. Rendered on every marketing route via HeaderMount.
 *
 * Responsive behavior lives in CSS (not a JS resize listener) so the server
 * markup is already correct at every width: inline links ≥768px, a minimal
 * disclosure toggle below.
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
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}
    >
      <style>{`
        .rs-mnav { height: 60px; padding-left: 24px; padding-right: 24px; }
        .rs-mnav-links { display: flex; align-items: center; gap: 28px; }
        .rs-mnav-toggle { display: none; }
        @media (max-width: 767px) {
          .rs-mnav { height: 52px; padding-left: 12px; padding-right: 12px; }
          .rs-mnav-links { display: none; }
          .rs-mnav-toggle { display: inline-flex; }
        }
      `}</style>

      {/* Left: logo → locale home */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'clamp(16px, 3vw, 40px)' }}>
        <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          <img src="/favicon.svg" alt="RSends" width={28} height={28} style={{ borderRadius: 7 }} />
          <span style={{ fontFamily: C.D, fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: '-0.03em' }}>
            RSends
          </span>
        </Link>

        {/* Desktop: inline flat nav between logo and the right-side controls */}
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
      </div>

      {/* Right: language + auth, plus the mobile disclosure toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
