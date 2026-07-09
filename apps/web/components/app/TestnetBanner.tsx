'use client'

/**
 * Persistent testnet banner for the /app dashboard. Plain static strip — no
 * dismiss, no animation. Copy is fixed (no license/custody/mainnet-live
 * implications).
 */

import { useTranslations } from 'next-intl'

export function TestnetBanner() {
  const t = useTranslations('onboarding')

  return (
    <div
      role="status"
      className="px-4 py-2 text-center text-xs md:text-sm border-b"
      style={{
        background: '#FDF3EF',
        borderColor: '#E8A488',
        color: '#8A3A1F',
      }}
    >
      {t('banner')}
    </div>
  )
}
