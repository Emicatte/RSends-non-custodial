'use client'

import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useEffect, useState } from 'react'
import { useEmailAuth } from '@/hooks/useEmailAuth'

/**
 * Persistent "verify your email" banner shown across the signed-in app while
 * the user's email is unverified. Sources of truth:
 *  - session.email_verified === false (set at credentials login). Google/GitHub
 *    users are verified by construction, so it's never false for them.
 *  - a `rsends:email-unverified` window event (emitted by apiCall when a gated
 *    route returns 403 email_not_verified) — covers a stale-but-verified
 *    session that nonetheless hit the deny-by-default gate.
 */
export function EmailVerifyBanner() {
  const t = useTranslations('auth.verifyBanner')
  const { data: session } = useSession()
  const { resendVerification } = useEmailAuth()
  const [forced, setForced] = useState(false)
  const [sent, setSent] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onUnverified = () => setForced(true)
    window.addEventListener('rsends:email-unverified', onUnverified)
    return () => window.removeEventListener('rsends:email-unverified', onUnverified)
  }, [])

  const sessionUnverified = session?.email_verified === false
  const email = session?.user?.email ?? ''
  if (!sessionUnverified && !forced) return null

  const onResend = async () => {
    if (!email || busy || sent) return
    setBusy(true)
    try {
      await resendVerification(email)
      setSent(true)
    } catch {
      // ignore — the user can retry
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-sm"
      style={{
        background: 'rgba(255,181,71,0.12)',
        borderBottom: '1px solid rgba(255,181,71,0.35)',
        color: '#2C2C2A',
      }}
    >
      <span>{t('message')}</span>
      <button
        type="button"
        onClick={onResend}
        disabled={!email || busy || sent}
        className="rounded-md px-3 py-1 text-xs font-medium text-white disabled:opacity-60"
        style={{ background: '#C8512C', border: 'none', cursor: 'pointer' }}
      >
        {sent ? t('sent') : t('resend')}
      </button>
    </div>
  )
}
