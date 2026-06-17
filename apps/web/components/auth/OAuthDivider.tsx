'use client'

import { useTranslations } from 'next-intl'

export function OAuthDivider() {
  const t = useTranslations('auth')
  return (
    <div className="my-4 flex items-center gap-3" role="separator" aria-label={t('orContinueWith')}>
      <div className="flex-1 h-px" style={{ background: 'rgba(200,81,44,0.2)' }} />
      <span className="text-xs uppercase tracking-wider" style={{ color: '#888780' }}>
        {t('orContinueWith')}
      </span>
      <div className="flex-1 h-px" style={{ background: 'rgba(200,81,44,0.2)' }} />
    </div>
  )
}
