'use client'

import { Link, usePathname } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'
import './app-sidebar.css'

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  accent: '#C45A3C',
  accentLight: 'rgba(196, 90, 60, 0.08)',
  paper: '#f7f6f3',
  border: 'rgba(26, 26, 26, 0.08)',
}

const ICON_SIZE = 18

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

type SidebarItem = {
  key: string
  href: '/app' | '/app/payments' | '/app/webhooks' | '/app/api-keys' | '/settings'
  Icon: () => JSX.Element
  hover: string
}

type SidebarSection = {
  section: 'overview' | 'management'
  items: ReadonlyArray<SidebarItem>
}

// Non-custodial dashboard nav. Custodial surfaces (send/swap/flow/command-center)
// and the mock management pages (transactions/balances/clients/reports) were
// removed in Phase A; the operational Invoices/Webhooks entries land in later
// phases. `payments` (Phase C) is the session-authed org payments view;
// `settings` points at the live session-guarded /settings area.
const SECTIONS: ReadonlyArray<SidebarSection> = [
  {
    section: 'overview',
    items: [
      { key: 'dashboard', href: '/app', Icon: DashboardIcon, hover: 'scale(1.12) rotate(5deg)' },
      { key: 'payments', href: '/app/payments', Icon: PaymentsIcon, hover: 'scale(1.12)' },
      { key: 'webhooks', href: '/app/webhooks', Icon: WebhooksIcon, hover: 'scale(1.12)' },
    ],
  },
  {
    section: 'management',
    items: [
      { key: 'apiKeys', href: '/app/api-keys', Icon: ApiKeysIcon, hover: 'scale(1.12)' },
      { key: 'settings', href: '/settings', Icon: SettingsIcon, hover: 'rotate(60deg)' },
    ],
  },
]

function isActive(pathname: string, href: string): boolean {
  if (href === '/app') return pathname === '/app'
  return pathname === href || pathname.startsWith(href + '/')
}

export default function AppSidebar() {
  const pathname = usePathname()
  const t = useTranslations('app.sidebar')

  return (
    <aside
      aria-label="App navigation"
      // top-16 must match the nav's md height (h-16) in AppNav.tsx — the two
      // change together or content slides under the fixed chrome.
      className="hidden md:flex fixed top-16 bottom-0 left-0 z-[999] w-52 flex-col overflow-y-auto px-3 py-5"
      style={{
        background: COLORS.paper,
        borderRight: `1px solid ${COLORS.border}`,
      }}
    >
      {SECTIONS.map(({ section, items }) => (
        <div key={section} className="mb-5">
          <div
            className="px-3 py-1.5 mb-1"
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 10,
              fontWeight: 700,
              color: COLORS.muted,
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
            }}
          >
            {t(section)}
          </div>
          {items.map(({ key, href, Icon, hover }) => {
            const active = isActive(pathname, href)
            return (
              <Link
                key={key}
                href={href}
                className="rp-sidebar-link flex items-center gap-3 px-3 py-2 rounded-lg"
                data-active={active}
                style={{
                  textDecoration: 'none',
                  color: active ? COLORS.accent : COLORS.ink,
                  fontFamily: 'var(--font-display)',
                  fontSize: 13,
                  fontWeight: active ? 700 : 500,
                  background: active ? COLORS.accentLight : 'transparent',
                  borderLeft: `2px solid ${active ? COLORS.accent : 'transparent'}`,
                  transition: 'background 0.15s, color 0.15s',
                  ['--rp-icon-hover' as string]: hover,
                }}
              >
                <span className="rp-sidebar-icon" aria-hidden>
                  <Icon />
                </span>
                <span>{t(key)}</span>
              </Link>
            )
          })}
        </div>
      ))}
    </aside>
  )
}
