'use client'

import { useTranslations } from 'next-intl'

export function EmailAuthError({
  code,
  message,
  retryAfter,
}: {
  code: string
  message?: string
  retryAfter?: string | null
}) {
  const t = useTranslations('auth.errors')

  const translationKey = `${code}`
  let text = ''
  try {
    text = t(translationKey)
  } catch {
    text = ''
  }
  if (!text || text === translationKey) {
    text = message || t('unknown')
  }

  return (
    <div
      role="alert"
      className="mt-3 rounded-lg px-3 py-2 text-sm"
      style={{
        background: 'rgba(192,57,43,0.08)',
        border: '1px solid rgba(192,57,43,0.3)',
        color: '#C0392B',
      }}
    >
      {text}
      {retryAfter ? (
        <span className="ml-1" style={{ color: '#888780' }}>
          ({t('retryIn', { seconds: retryAfter })})
        </span>
      ) : null}
    </div>
  )
}
