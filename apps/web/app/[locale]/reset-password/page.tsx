'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { Suspense, useState } from 'react'
import { useEmailAuth } from '@/hooks/useEmailAuth'
import {
  PasswordStrengthMeter,
  scorePassword,
} from '@/components/auth/PasswordStrengthMeter'
import { EmailAuthError } from '@/components/auth/EmailAuthError'

function Inner() {
  const t = useTranslations('auth.resetPassword')
  const locale = useLocale()
  const router = useRouter()
  const params = useSearchParams()
  const token = params.get('token') ?? ''
  const { resetPassword, loading, error, clearError } = useEmailAuth()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  const mismatch = confirm.length > 0 && password !== confirm
  const canSubmit =
    token.length > 0 &&
    scorePassword(password) >= 2 &&
    password === confirm &&
    !loading

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    try {
      await resetPassword(token, password)
      router.push(`/${locale}/login?reset=1`)
    } catch {
      // error surfaced by hook
    }
  }

  if (!token) {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
          {t('errorTitle')}
        </h1>
        <p className="mt-2 text-sm" style={{ color: '#888780' }}>
          {t('missingToken')}
        </p>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md">
      <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
        {t('title')}
      </h1>
      <p className="mt-1 text-sm" style={{ color: '#888780' }}>
        {t('subtitle')}
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('newPasswordLabel')}
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
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
          <PasswordStrengthMeter password={password} />
        </label>

        <label className="flex flex-col gap-1 text-sm" style={{ color: '#2C2C2A' }}>
          {t('confirmLabel')}
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
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
          {mismatch ? (
            <span className="mt-1 text-xs" style={{ color: '#C0392B' }}>
              {t('mismatch')}
            </span>
          ) : null}
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
          disabled={!canSubmit}
          className="mt-2 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          style={{ background: '#C8512C', border: 'none' }}
        >
          {loading ? t('submitLoading') : t('submit')}
        </button>
      </form>
    </div>
  )
}

export default function ResetPasswordPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10" style={{ background: '#FAF8F3' }}>
      <Suspense fallback={null}>
        <Inner />
      </Suspense>
    </main>
  )
}
