'use client'

import Link from 'next/link'
import { useLocale, useTranslations } from 'next-intl'
import { useState } from 'react'
import { useEmailAuth } from '@/hooks/useEmailAuth'
import { EmailAuthError } from '@/components/auth/EmailAuthError'

export default function ForgotPasswordPage() {
  const t = useTranslations('auth.forgotPassword')
  const locale = useLocale()
  const { requestPasswordReset, loading, error, clearError } = useEmailAuth()
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    try {
      await requestPasswordReset(email.trim().toLowerCase())
      setSent(true)
    } catch {
      // error captured in hook state
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10" style={{ background: '#FAF8F3' }}>
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
          {t('title')}
        </h1>
        <p className="mt-1 text-sm" style={{ color: '#888780' }}>
          {t('subtitle')}
        </p>

        {sent ? (
          <div
            className="mt-6 rounded-lg px-4 py-3 text-sm"
            style={{
              background: 'rgba(76,154,107,0.1)',
              border: '1px solid rgba(76,154,107,0.3)',
              color: '#2C2C2A',
            }}
          >
            {t('successBody')}
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
              {t('emailLabel')}
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{
                  border: '1px solid rgba(200,81,44,0.25)',
                  borderRadius: 10,
                  padding: '10px 12px',
                  fontSize: 14,
                  color: '#2C2C2A',
                  background: '#fff',
                  width: '100%',
                  outline: 'none',
                }}
              />
            </label>
            {error ? (
              <EmailAuthError
                code={error.code}
                message={error.message}
                retryAfter={error.retry_after}
              />
            ) : null}
            <button
              type="submit"
              disabled={loading || email.length < 4}
              className="mt-2 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
              style={{ background: '#C8512C', border: 'none' }}
            >
              {loading ? t('submitLoading') : t('submit')}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-sm" style={{ color: '#888780' }}>
          <Link
            href={`/${locale}/login`}
            style={{ color: '#C8512C', textDecoration: 'none' }}
          >
            {t('backToLogin')}
          </Link>
        </p>
      </div>
    </main>
  )
}
