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

const TransactionsIcon = () => (
  <svg {...iconBase}>
    <line x1="3" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="21" y2="12" />
    <line x1="3" y1="18" x2="21" y2="18" />
  </svg>
)

const BalancesIcon = () => (
  <svg {...iconBase}>
    <rect x="2" y="6" width="20" height="14" rx="2" />
    <path d="M2 10h20" />
  </svg>
)

const ClientsIcon = () => (
  <svg {...iconBase}>
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
)

const SettingsIcon = () => (
  <svg {...iconBase}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

type BottomNavHref = '/app' | '/app/transactions' | '/app/balances' | '/app/clients' | '/app/settings'

type BottomNavItem = {
  key: 'dashboard' | 'transactions' | 'balances' | 'clients' | 'settings'
  href: BottomNavHref
  Icon: () => JSX.Element
}

const ITEMS: ReadonlyArray<BottomNavItem> = [
  { key: 'dashboard',    href: '/app',              Icon: DashboardIcon },
  { key: 'transactions', href: '/app/transactions', Icon: TransactionsIcon },
  { key: 'balances',     href: '/app/balances',     Icon: BalancesIcon },
  { key: 'clients',      href: '/app/clients',      Icon: ClientsIcon },
  { key: 'settings',     href: '/app/settings',     Icon: SettingsIcon },
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
