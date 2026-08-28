'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Link, usePathname } from '@/i18n/navigation'
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

/** Compacts past this many pixels of scroll. */
const COMPACT_AT = 24

/**
 * The marketing header, rendered on every marketing route via HeaderMount.
 *
 * One surface, always solid terracotta-deep. There is deliberately no
 * transparent-over-hero variant: `--rs-terracotta-deep` carries white text at
 * 6.14:1, and that guarantee evaporates the moment the bar goes translucent
 * over arbitrary hero content.
 *
 * `--rs-terracotta-deep` and not `--rs-terracotta`: white on the lighter
 * terracotta is 4.4975:1, i.e. just under AA. See docs/brand-tokens.md.
 *
 * Responsive behavior lives in CSS (not a JS resize listener) so the server
 * markup is already correct at every width: inline links ≥1024px, a minimal
 * disclosure toggle below. The collapse point is 1024 (not 768) because the
 * centered link row plus the side clusters need ~860px in the widest locale
 * (fr) before they collide.
 *
 * The compact-on-scroll state is the one thing that does need JS. It only ever
 * shrinks a `position: fixed` bar, and every marketing page reserves its top
 * padding as a fixed value rather than measuring the nav — so this cannot move
 * page content, and contributes nothing to CLS.
 */
export default function MarketingNav() {
  const t = useTranslations('nav')
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [compact, setCompact] = useState(false)

  useEffect(() => {
    // rAF-coalesced: scroll fires far more often than we can usefully repaint,
    // and this listener must never be the reason a scroll janks.
    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = requestAnimationFrame(() => {
        frame = 0
        setCompact(window.scrollY > COMPACT_AT)
      })
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [])

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`)

  return (
    <nav
      className={`rs-mnav${compact ? ' rs-mnav--compact' : ''}`}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 1000,
        paddingTop: 'var(--sat, 0px)',
        background: C.terracottaDeep,
      }}
    >
      {/* The nav's CSS lives in app/globals.css under "MARKETING NAV", not in an
          inline <style>. React HTML-escapes text children, and <style> is a
          raw-text element the browser never un-escapes — so an apostrophe in a
          selector like [aria-current='page'] ships to the client as &#x27;,
          breaking both the rule and hydration. The previous inline block only
          survived because it happened to contain no quotes. */}

      {/* Left: logo → locale home */}
      <div style={{ display: 'flex', alignItems: 'center', justifySelf: 'start' }}>
        <Link
          href="/"
          className="rs-mnav-logo"
          style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}
        >
          <img src="/favicon.svg" alt="RSends" width={28} height={28} style={{ borderRadius: 4 }} />
          <span style={{ fontFamily: C.D, fontSize: 16, fontWeight: 700, color: C.onDark, letterSpacing: '-0.03em' }}>
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
            className="rs-mnav-link"
            aria-current={isActive(link.href) ? 'page' : undefined}
            style={{
              fontFamily: C.D,
              fontSize: 14,
              fontWeight: 500,
              letterSpacing: '-0.01em',
              color: C.onDark,
              textDecoration: 'none',
            }}
          >
            {t(link.key)}
          </Link>
        ))}
      </div>

      {/* Right: language + auth, plus the mobile disclosure toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifySelf: 'end', gridColumn: 3 }}>
        <LanguageSwitcher onDark />
        <LandingAuthButtons onDark />
        <button
          type="button"
          className="rs-mnav-toggle"
          aria-label="Menu"
          aria-expanded={open}
          aria-controls="rs-mnav-panel"
          onClick={() => setOpen(prev => !prev)}
          style={{
            alignItems: 'center', justifyContent: 'center',
            // 44×44 is the floor for a touch target, and this is the only
            // control on the bar below 1024px.
            width: 44, height: 44, padding: 0,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: C.onDark,
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

      {/* Mobile disclosure panel — same surface as the bar it drops out of */}
      {open && (
        <div
          id="rs-mnav-panel"
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0,
            background: C.terracottaDeep,
            borderBottom: '1px solid rgba(0,0,0,0.12)',
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
              aria-current={isActive(link.href) ? 'page' : undefined}
              style={{
                fontFamily: C.D, fontSize: 15, fontWeight: 500,
                color: C.onDark, textDecoration: 'none',
                // 44px min so the panel rows are touch targets too.
                minHeight: 44, display: 'flex', alignItems: 'center',
                padding: '0 4px',
                borderBottom: `1px solid ${C.onDarkLine}`,
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
