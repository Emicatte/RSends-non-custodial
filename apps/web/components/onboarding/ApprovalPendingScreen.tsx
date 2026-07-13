'use client'

/**
 * Post-KYB waiting screen: the merchant's profile is in the review queue
 * (approval_status = pending_approval). Polls the onboarding state with
 * backoff (lib/approvalPolling) and transitions ON ITS OWN when the operator
 * decides — approved → /app, declined → the decline page. No manual refresh.
 */

import { useEffect, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useRouter } from '@/i18n/navigation'

import { approvalTransition, nextPollDelay } from '@/lib/approvalPolling'
import { getOnboardingState } from '@/lib/onboarding-client'

export function ApprovalPendingScreen() {
  const t = useTranslations('onboarding.pending')
  const router = useRouter()
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  useEffect(() => {
    if (status !== 'authenticated') return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0

    const tick = async () => {
      try {
        const state = await getOnboardingState(tokenRef.current)
        if (cancelled) return
        const target = approvalTransition(state.approval_status)
        if (target) {
          router.replace(target)
          return
        }
      } catch {
        // transient (network/5xx/refresh window): keep polling on the same
        // backoff — the screen is read-only, nothing to surface but patience.
      }
      if (!cancelled) {
        timer = setTimeout(tick, nextPollDelay(attempt))
        attempt += 1
      }
    }

    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [status, router])

  return (
    <div className="text-center py-16 space-y-4">
      <span
        className="inline-flex h-12 w-12 items-center justify-center rounded-full text-xl"
        style={{ background: '#FBE8DF', color: '#C8512C' }}
        aria-hidden
      >
        ⏳
      </span>
      <h1 className="text-xl font-semibold" style={{ color: '#0A0A0A' }}>
        {t('title')}
      </h1>
      <p className="text-sm max-w-md mx-auto" style={{ color: '#55544E' }}>
        {t('body')}
      </p>
      <p className="text-xs" style={{ color: '#888780' }}>
        {t('autoRefresh')}
      </p>
    </div>
  )
}
