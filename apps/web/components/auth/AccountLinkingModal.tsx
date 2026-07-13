'use client'

import { useLocale, useTranslations } from 'next-intl'
import Link from 'next/link'

/**
 * "This email is already registered" guidance modal, shown by the signup form
 * when check-email (or the signup 409) reports an existing account. With
 * social login removed the only scenario left is an existing email/password
 * account, so the modal always guides to the login page.
 */
export function AccountLinkingModal({
  email,
  onClose,
}: {
  email: string
  onClose: () => void
}) {
  const t = useTranslations('auth.linking')
  const locale = useLocale()

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-linking-title"
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(44,44,42,0.45)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6"
        style={{ border: '1px solid rgba(200,81,44,0.25)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          id="account-linking-title"
          className="text-lg font-semibold"
          style={{ color: '#2C2C2A' }}
        >
          {t('passwordTitle')}
        </h2>
        <p className="mt-2 text-sm" style={{ color: '#888780' }}>
          {t('passwordBody', { email })}
        </p>

        <div className="mt-5 flex flex-col gap-2">
          <Link
            href={`/${locale}/login`}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white text-center"
            style={{ background: '#C8512C', textDecoration: 'none' }}
          >
            {t('ctaLogin')}
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-white px-4 py-2 text-sm font-medium"
            style={{
              color: '#2C2C2A',
              border: '1px solid rgba(200,81,44,0.25)',
              cursor: 'pointer',
            }}
          >
            {t('ctaClose')}
          </button>
        </div>
      </div>
    </div>
  )
}
