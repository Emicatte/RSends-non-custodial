'use client'

/**
 * "Get started" checklist card for the /app home. Links to EXISTING surfaces
 * only: settlement wallet config (settings/organization, Phase B), the API
 * keys tab (Phase E), and creating a test payment (/app/payments).
 */

import { useTranslations } from 'next-intl'
import { Link } from '@/i18n/navigation'

const ITEMS = [
  { key: 'wallet', href: '/settings/organization' },
  { key: 'apiKey', href: '/app/api-keys' },
  { key: 'testPayment', href: '/app/payments' },
] as const

export function GetStartedChecklist() {
  const t = useTranslations('onboarding.checklist')

  return (
    <div
      className="rounded-2xl border p-5"
      style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
    >
      <h2 className="text-sm font-semibold mb-3" style={{ color: '#0A0A0A' }}>
        {t('title')}
      </h2>
      <ul className="space-y-2">
        {ITEMS.map((item, i) => (
          <li key={item.key}>
            <Link
              href={item.href}
              className="flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm hover:border-[#C8512C]"
              style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
            >
              <span
                className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px]"
                style={{ borderColor: '#C8512C', color: '#C8512C' }}
              >
                {i + 1}
              </span>
              {t(item.key)}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
