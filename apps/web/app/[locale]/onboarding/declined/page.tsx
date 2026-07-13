'use client'

/**
 * /onboarding/declined — terminal screen for a declined merchant. Shows the
 * operator's reason (from the onboarding state) and a support contact. No
 * retry loop, no polling: the decision is manual and so is any appeal.
 */

import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'

import { getOnboardingState } from '@/lib/onboarding-client'

export default function ApprovalDeclinedPage() {
  const t = useTranslations('onboarding.declined')
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const [reason, setReason] = useState<string | null>(null)

  useEffect(() => {
    if (status !== 'authenticated') return
    let cancelled = false
    getOnboardingState(accessToken)
      .then((state) => {
        if (!cancelled) setReason(state.decline_reason ?? null)
      })
      .catch(() => {
        /* the static copy stands on its own */
      })
    return () => {
      cancelled = true
    }
  }, [status, accessToken])

  return (
    <div className="text-center py-16 space-y-4">
      <span
        className="inline-flex h-12 w-12 items-center justify-center rounded-full text-xl"
        style={{ background: '#F6DEDC', color: '#B3261E' }}
        aria-hidden
      >
        ✕
      </span>
      <h1 className="text-xl font-semibold" style={{ color: '#0A0A0A' }}>
        {t('title')}
      </h1>
      <p className="text-sm max-w-md mx-auto" style={{ color: '#55544E' }}>
        {t('body')}
      </p>
      {reason ? (
        <div
          className="max-w-md mx-auto rounded-lg border px-4 py-3 text-left text-sm"
          style={{ borderColor: '#EBD3CE', background: '#FBF3F1', color: '#55544E' }}
        >
          <span className="font-medium" style={{ color: '#0A0A0A' }}>
            {t('reasonLabel')}:{' '}
          </span>
          {reason}
        </div>
      ) : null}
      <p className="text-xs" style={{ color: '#888780' }}>
        {t('contact')}
      </p>
    </div>
  )
}
