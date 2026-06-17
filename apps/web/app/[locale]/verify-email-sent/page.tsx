'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useLocale, useTranslations } from 'next-intl'
import { Suspense, useState } from 'react'
import { useEmailAuth } from '@/hooks/useEmailAuth'

function Inner() {
  const t = useTranslations('auth.verify')
  const locale = useLocale()
  const params = useSearchParams()
  const email = params.get('email') ?? ''
  const { resendVerification, loading } = useEmailAuth()
  const [sent, setSent] = useState(false)

  const onResend = async () => {
    if (!email) return
    try {
      await resendVerification(email)
      setSent(true)
    } catch {
      // noop
    }
  }

  return (
    <div className="w-full max-w-md text-center">
      <h1 className="text-2xl font-semibold" style={{ color: '#2C2C2A' }}>
        {t('sentTitle')}
      </h1>
      <p className="mt-2 text-sm" style={{ color: '#888780' }}>
        {email ? t('sentBody', { email }) : t('sentBodyNoEmail')}
      </p>
      <div className="mt-6 flex flex-col items-center gap-2">
        <button
          type="button"
          disabled={!email || loading || sent}
          onClick={onResend}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          style={{ background: '#C8512C', border: 'none', cursor: 'pointer' }}
        >
          {sent ? t('resendSent') : t('resendCta')}
        </button>
        <Link
          href={`/${locale}/login`}
          className="text-xs"
          style={{ color: '#C8512C', textDecoration: 'none' }}
        >
          {t('ctaLogin')}
        </Link>
      </div>
    </div>
  )
}

export default function VerifyEmailSentPage() {
  return (
    <main className="min-h-screen flex items-center justify-center px-4 py-10" style={{ background: '#FAF8F3' }}>
      <Suspense fallback={null}>
        <Inner />
      </Suspense>
    </main>
  )
}
