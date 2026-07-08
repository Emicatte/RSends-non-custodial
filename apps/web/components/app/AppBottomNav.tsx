'use client'

import { Link, usePathname } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'

const ICON_SIZE = 22

const iconBase = {
  width: ICON_SIZE,
  height: ICON_SIZE,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

const DashboardIcon = () => (
  <svg {...iconBase}>
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
  </svg>
)

const PaymentsIcon = () => (
  <svg {...iconBase}>
    <rect x="2" y="5" width="20" height="14" rx="2" />
    <line x1="2" y1="10" x2="22" y2="10" />
  </svg>
)

const SettingsIcon = () => (
  <svg {...iconBase}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

const WebhooksIcon = () => (
  <svg {...iconBase}>
    <path d="M18 16.98h-5.99c-1.66 0-3.01-1.34-3.01-3s1.35-3 3.01-3H18" />
    <path d="m14 13 4 4-4 4" />
    <circle cx="6" cy="7" r="3" />
    <path d="M6 10v4" />
  </svg>
)

const ApiKeysIcon = () => (
  <svg {...iconBase}>
    <circle cx="7.5" cy="15.5" r="4.5" />
    <path d="m10.5 12.5 8-8" />
    <path d="m16.5 6.5 3 3" />
    <path d="m13.5 9.5 3 3" />
  </svg>
)

type BottomNavHref = '/app' | '/app/payments' | '/app/webhooks' | '/app/api-keys' | '/settings'

type BottomNavItem = {
  key: 'dashboard' | 'payments' | 'webhooks' | 'apiKeys' | 'settings'
  href: BottomNavHref
  Icon: () => JSX.Element
}

// Custodial/mock entries (transactions/balances/clients) removed in Phase A;
// `payments` (Phase C) is the org payments view; `webhooks`/`apiKeys` (Phase E)
// are the operational management pages; `settings` → live /settings area.
const ITEMS: ReadonlyArray<BottomNavItem> = [
  { key: 'dashboard', href: '/app',          Icon: DashboardIcon },
  { key: 'payments',  href: '/app/payments', Icon: PaymentsIcon },
  { key: 'webhooks',  href: '/app/webhooks', Icon: WebhooksIcon },
  { key: 'apiKeys',   href: '/app/api-keys', Icon: ApiKeysIcon },
  { key: 'settings',  href: '/settings',     Icon: SettingsIcon },
]

export default function AppBottomNav() {
  const pathname = usePathname()
  const t = useTranslations('app.sidebar')

  const isActive = (href: BottomNavHref) =>
    href === '/app' ? pathname === '/app' : pathname.startsWith(href)

  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-[1000] bg-white border-t border-black/[0.06] grid grid-cols-5"
      style={{
        paddingBottom: 'env(safe-area-inset-bottom)',
      }}
    >
      {ITEMS.map(({ key, href, Icon }) => {
        const active = isActive(href)
        return (
          <Link
            key={key}
            href={href}
            className="flex flex-col items-center justify-center gap-1 no-underline"
            style={{
              minHeight: 60,
              color: active ? '#1a1a1a' : '#6b6b6b',
            }}
          >
            <Icon />
            <span
              style={{
                fontSize: 10,
                fontWeight: active ? 600 : 500,
                letterSpacing: 0.2,
              }}
            >
              {t(key)}
            </span>
          </Link>
        )
      })}
    </nav>
  )
}
