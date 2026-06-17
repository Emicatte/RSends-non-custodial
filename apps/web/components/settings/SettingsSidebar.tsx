'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useTranslations } from 'next-intl'

interface SettingsSidebarProps {
  locale: string
}

type NavItem = {
  key: 'organization' | 'notifications' | 'wallets' | 'apiKeys' | 'billing' | 'invoices' | 'security'
  enabled: boolean
  href?: string
}

const ITEMS: NavItem[] = [
  { key: 'organization', enabled: true },
  { key: 'notifications', enabled: true },
  { key: 'wallets', enabled: true },
  { key: 'apiKeys', enabled: true, href: 'api-keys' },
  { key: 'billing', enabled: true },
  { key: 'invoices', enabled: true },
  { key: 'security', enabled: true },
]

export function SettingsSidebar({ locale }: SettingsSidebarProps) {
  const pathname = usePathname()
  const t = useTranslations('settings')

  return (
    <nav className="w-full md:w-56 flex-shrink-0" aria-label="Settings navigation">
      <ul className="space-y-1">
        {ITEMS.map((item) => {
          const href = `/${locale}/settings/${item.href ?? item.key}`
          const active = pathname === href
          if (!item.enabled) {
            return (
              <li key={item.key}>
                <span
                  className="block px-3 py-2 rounded-lg text-sm"
                  style={{ color: '#888780', cursor: 'not-allowed' }}
                  title={t('nav.soon')}
                >
                  {t(`nav.${item.key}`)}
                  <span className="ml-2 text-[10px] uppercase tracking-wider">
                    {t('nav.soon')}
                  </span>
                </span>
              </li>
            )
          }
          return (
            <li key={item.key}>
              <Link
                href={href}
                className="block px-3 py-2 rounded-lg text-sm transition-colors"
                style={{
                  color: active ? '#C8512C' : '#2C2C2A',
                  background: active ? 'rgba(200,81,44,0.08)' : 'transparent',
                  fontWeight: active ? 600 : 400,
                  textDecoration: 'none',
                }}
              >
                {t(`nav.${item.key}`)}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
