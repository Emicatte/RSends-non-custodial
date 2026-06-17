'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { Suspense, useEffect, useRef, useState } from 'react'
import { useEmailAuth, type EmailAuthErrorShape } from '@/hooks/useEmailAuth'
import { EmailAuthError } from '@/components/auth/EmailAuthError'

type State = 'loading' | 'success' | 'error'

function VerifyInner() {
  const t = useTranslations('auth.verify')
  const locale = useLocale()
  const params = useSearchParams()
  const token = params.get('token') ?? ''
  const { verifyEmail, resendVerification } = useEmailAuth()
  const [state, setState] = useState<State>('loading')
  const [err, setErr] = useState<EmailAuthErrorShape | null>(null)
  const [resendEmail, setResendEmail] = useState('')
  const [resendDone, setResendDone] = useState(false)
  const fired = useRef(false)

  useEffect(() => {
    if (fired.current) return
    fired.current = true
    if (!token) {
      setState('error')
      setErr({ code: 'invalid_token' })
      return
    }
    verifyEmail(token)
      .then(() => setState('success'))
      .catch((e) => {
        setErr(e as EmailAuthErrorShape)
        setState('error')
      })
  }, [token, verifyEmail])

  if (state === 'loading') {
    return (
      <div className="text-center">
        <p style={{ color: '#888780' }}>{t('loading')}</p>
      </div>
    )
  }

  if (state === 'success') {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
          {t('successTitle')}
        </h1>
        <p className="mt-2 text-sm" style={{ color: '#888780' }}>
          {t('successBody')}
        </p>
        <Link
          href={`/${locale}/login`}
          className="mt-6 inline-block rounded-lg px-4 py-2 text-sm font-medium text-white"
          style={{ background: '#C8512C', textDecoration: 'none' }}
        >
          {t('ctaLogin')}
        </Link>
      </div>
    )
  }

  return (
    <div className="w-full max-w-md">
      <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
        {t('errorTitle')}
      </h1>
      {err ? (
        <EmailAuthError
          code={err.code}
          message={err.message}
          retryAfter={err.retry_after}
        />
      ) : null}

      {err?.code === 'token_expired' ? (
        <div className="mt-4 flex flex-col gap-2">
          <label className="text-sm" style={{ color: '#2C2C2A' }}>
            {t('resendEmailLabel')}
            <input
              type="email"
              value={resendEmail}
              onChange={(e) => setResendEmail(e.target.value)}
              className="mt-1 w-full"
              style={{
                border: '1px solid rgba(200,81,44,0.25)',
                borderRadius: 10,
                padding: '10px 12px',
                fontSize: 14,
                color: '#2C2C2A',
                background: '#fff',
                outline: 'none',
              }}
            />
          </label>
          <button
            type="button"
            disabled={!resendEmail || resendDone}
            onClick={async () => {
              try {
                await resendVerification(resendEmail.trim().toLowerCase())
                setResendDone(true)
              } catch {
                // noop; user can retry
              }
            }}
            className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            style={{ background: '#C8512C', border: 'none' }}
          >
            {resendDone ? t('resendSent') : t('resendCta')}
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default function VerifyEmailPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10" style={{ background: '#FAF8F3' }}>
      <Suspense fallback={null}>
        <VerifyInner />
      </Suspense>
    </main>
  )
}
