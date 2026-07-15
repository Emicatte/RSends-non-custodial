'use client'

import { usePathname } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
}

// Map app pathname → app.sidebar.* translation key. The topbar h1 is the ONE
// page title (the pages themselves render no h1 — a subtitle at most), so
// every /app route needs an entry here or it falls back to "dashboard".
const PATH_TO_KEY: ReadonlyArray<{ prefix: string; key: string }> = [
  { prefix: '/app/payments', key: 'payments' },
  { prefix: '/app/webhooks', key: 'webhooks' },
  { prefix: '/app/api-keys', key: 'apiKeys' },
]

function resolveTitleKey(pathname: string): string {
  if (pathname === '/app') return 'dashboard'
  for (const entry of PATH_TO_KEY) {
    if (pathname === entry.prefix || pathname.startsWith(entry.prefix + '/')) {
      return entry.key
    }
  }
  return 'dashboard'
}

export default function AppTopbar() {
  const pathname = usePathname()
  const t = useTranslations()
  const { activeOrg } = useCurrentOrg()

  const titleKey = resolveTitleKey(pathname)
  const title = t(`app.sidebar.${titleKey}`)

  return (
    <div
      className="py-4"
      style={{
        background: COLORS.white,
        borderBottom: `1px solid ${COLORS.border}`,
      }}
    >
      {/* Inner box mirrors the page container (pageStyles.appPage): same
          max-w-6xl with the gutter padding INSIDE it, so the title stays
          aligned with page content even when the max-width binds. */}
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-5 md:px-8">
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22,
            fontWeight: 700,
            color: COLORS.ink,
            letterSpacing: '-0.02em',
            margin: 0,
          }}
        >
          {title}
        </h1>

        <div className="ml-auto flex items-center gap-3">
          {activeOrg?.name && (
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 13,
                fontWeight: 600,
                color: COLORS.muted,
              }}
            >
              {activeOrg.name}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
