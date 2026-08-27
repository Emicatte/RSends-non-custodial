'use client'

import { useTranslations } from 'next-intl'

export function EmailAuthError({
  code,
  message,
  retryAfter,
  correlationId,
}: {
  code: string
  message?: string
  retryAfter?: string | null
  /** Shown so a user can quote it; joins to the backend request/audit log. */
  correlationId?: string
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
      <span data-testid="auth-error-message">{text}</span>
      {retryAfter ? (
        <span className="ml-1" style={{ color: '#888780' }}>
          ({t('retryIn', { seconds: retryAfter })})
        </span>
      ) : null}
      {correlationId ? (
        <span
          data-testid="auth-error-reference"
          className="mt-1 block text-xs"
          style={{ color: '#888780' }}
        >
          {t('errorReference')} {correlationId}
        </span>
      ) : null}
    </div>
  )
}
