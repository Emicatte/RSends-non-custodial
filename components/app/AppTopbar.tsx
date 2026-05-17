'use client'

import { usePathname } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  white: '#ffffff',
  border: '#e5e4e0',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
}

// Map app pathname → app.sidebar.* translation key
const PATH_TO_KEY: ReadonlyArray<{ prefix: string; key: string }> = [
  { prefix: '/app/transactions',   key: 'transactions' },
  { prefix: '/app/balances',       key: 'balances' },
  { prefix: '/app/clients',        key: 'clients' },
  { prefix: '/app/command-center', key: 'commandCenter' },
  { prefix: '/app/reports',        key: 'reports' },
  { prefix: '/app/settings',       key: 'settings' },
  { prefix: '/app/send',           key: 'send' },
  { prefix: '/app/swap',           key: 'swap' },
  { prefix: '/app/flow',           key: 'flow' },
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

  const titleKey = resolveTitleKey(pathname)
  const title = t(`app.sidebar.${titleKey}`)

  return (
    <div
      className="px-4 md:px-8 py-[18px]"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        background: COLORS.white,
        borderBottom: `1px solid ${COLORS.border}`,
      }}
    >
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

      <div
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 10px',
            borderRadius: 999,
            background: COLORS.greenLight,
            color: COLORS.green,
            fontFamily: 'var(--font-display)',
            fontSize: 11,
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: COLORS.green,
              display: 'inline-block',
            }}
          />
          {t('app.dashboard.mainnetBadge')}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 13,
            fontWeight: 600,
            color: COLORS.muted,
          }}
        >
          RPagos SRL
        </span>
      </div>
    </div>
  )
}
