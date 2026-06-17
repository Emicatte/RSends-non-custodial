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

const SendIcon = () => (
  <svg {...iconBase}>
    <path d="M22 2L11 13" />
    <path d="M22 2l-7 20-4-9-9-4 20-7z" />
  </svg>
)

const SwapIcon = () => (
  <svg {...iconBase}>
    <path d="M7 16l-4-4 4-4" />
    <path d="M17 8l4 4-4 4" />
    <path d="M3 12h18" />
  </svg>
)

const FlowIcon = () => (
  <svg {...iconBase}>
    <circle cx="6" cy="6" r="2" />
    <circle cx="18" cy="6" r="2" />
    <circle cx="18" cy="18" r="2" />
    <path d="M8 6h8" />
    <path d="M18 8v8" />
    <path d="M16 18l-8-8" />
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

const CommandCenterIcon = () => (
  <svg {...iconBase}>
    <line x1="4" y1="21" x2="4" y2="14" />
    <line x1="4" y1="10" x2="4" y2="3" />
    <line x1="12" y1="21" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12" y2="3" />
    <line x1="20" y1="21" x2="20" y2="16" />
    <line x1="20" y1="12" x2="20" y2="3" />
    <line x1="1" y1="14" x2="7" y2="14" />
    <line x1="9" y1="8" x2="15" y2="8" />
    <line x1="17" y1="16" x2="23" y2="16" />
  </svg>
)

const ReportsIcon = () => (
  <svg {...iconBase}>
    <line x1="6" y1="20" x2="6" y2="16" />
    <line x1="12" y1="20" x2="12" y2="10" />
    <line x1="18" y1="20" x2="18" y2="4" />
  </svg>
)

const SettingsIcon = () => (
  <svg {...iconBase}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
)

type SidebarItem = {
  key: string
  href: '/app' | '/app/send' | '/app/swap' | '/app/flow' | '/app/transactions' | '/app/balances' | '/app/clients' | '/app/command-center' | '/app/reports' | '/app/settings'
  Icon: () => JSX.Element
  hover: string
}

type SidebarSection = {
  section: 'overview' | 'actions' | 'management'
  items: ReadonlyArray<SidebarItem>
}

const SECTIONS: ReadonlyArray<SidebarSection> = [
  {
    section: 'overview',
    items: [
      { key: 'dashboard', href: '/app', Icon: DashboardIcon, hover: 'scale(1.12) rotate(5deg)' },
    ],
  },
  {
    section: 'actions',
    items: [
      { key: 'send', href: '/app/send', Icon: SendIcon, hover: 'translateX(3px) translateY(-3px) rotate(-8deg)' },
      { key: 'swap', href: '/app/swap', Icon: SwapIcon, hover: 'rotate(180deg)' },
      { key: 'flow', href: '/app/flow', Icon: FlowIcon, hover: 'rotate(-15deg) scale(1.1)' },
    ],
  },
  {
    section: 'management',
    items: [
      { key: 'transactions', href: '/app/transactions', Icon: TransactionsIcon, hover: 'translateY(-2px)' },
      { key: 'balances', href: '/app/balances', Icon: BalancesIcon, hover: 'scaleY(1.15) translateY(-1px)' },
      { key: 'clients', href: '/app/clients', Icon: ClientsIcon, hover: 'translateX(2px)' },
      { key: 'commandCenter', href: '/app/command-center', Icon: CommandCenterIcon, hover: 'translateX(3px)' },
      { key: 'reports', href: '/app/reports', Icon: ReportsIcon, hover: 'scaleY(1.2) translateY(-2px)' },
      { key: 'settings', href: '/app/settings', Icon: SettingsIcon, hover: 'rotate(60deg)' },
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
      className="hidden md:flex"
      style={{
        position: 'fixed',
        top: 63,
        left: 0,
        bottom: 0,
        width: 210,
        flexDirection: 'column',
        padding: '20px 12px',
        background: COLORS.paper,
        borderRight: `1px solid ${COLORS.border}`,
        zIndex: 999,
        overflowY: 'auto',
      }}
    >
      {SECTIONS.map(({ section, items }) => (
        <div key={section} style={{ marginBottom: 20 }}>
          <div
            style={{
              fontFamily: 'var(--font-display)',
              fontSize: 10,
              fontWeight: 700,
              color: COLORS.muted,
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              padding: '6px 12px',
              marginBottom: 4,
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
                className="rp-sidebar-link"
                data-active={active}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '8px 12px',
                  borderRadius: 8,
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
