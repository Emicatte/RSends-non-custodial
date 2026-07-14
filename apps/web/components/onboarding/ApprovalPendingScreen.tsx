'use client'

/**
 * Post-KYB waiting screen: the merchant's profile is in the review queue
 * (approval_status = pending_approval). Polls the onboarding state with
 * backoff (lib/approvalPolling) and transitions ON ITS OWN when the operator
 * decides — approved → /app, declined → the decline page. No manual refresh.
 *
 * Failure handling (a merchant can sit here for hours):
 *   • transient poll errors (network / 5xx / refresh temporarily down) keep
 *     the backoff going; after TRANSIENT_NOTICE_THRESHOLD consecutive
 *     failures a non-blocking "still retrying" line appears, cleared by the
 *     first success — never a silent stall;
 *   • a terminal `session_expired` (or NextAuth flipping to unauthenticated)
 *     STOPS the polling and swaps the copy for a "session expired" message
 *     with a login link that returns here. No infinite spinner.
 */

import { useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { Link, useRouter } from '@/i18n/navigation'

import { approvalTransition, nextPollDelay } from '@/lib/approvalPolling'
import { getOnboardingState } from '@/lib/onboarding-client'

// ~2.5 min of consecutive failures (15+30+60+60s) before surfacing trouble.
export const TRANSIENT_NOTICE_THRESHOLD = 4

const LOGIN_HREF = '/login?redirect=/onboarding/pending'

export function ApprovalPendingScreen() {
  const t = useTranslations('onboarding.pending')
  const router = useRouter()
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const [expired, setExpired] = useState(false)
  const [trouble, setTrouble] = useState(false)

  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  // A dead NextAuth session (signed out by a failed refresh, or expired) must
  // surface, not silently stop the poll effect below.
  useEffect(() => {
    if (status === 'unauthenticated') setExpired(true)
  }, [status])

  useEffect(() => {
    if (status !== 'authenticated') return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let failures = 0

    const tick = async () => {
      try {
        const state = await getOnboardingState(tokenRef.current)
        if (cancelled) return
        failures = 0
        setTrouble(false)
        const target = approvalTransition(state.approval_status)
        if (target) {
          router.replace(target)
          return
        }
      } catch (e) {
        if (cancelled) return
        if ((e as Error).message === 'session_expired') {
          // Terminal: apiCall already signed us out client-side. Stop polling
          // and tell the merchant — a token that no longer exists will never
          // start working again by itself.
          setExpired(true)
          return
        }
        // Transient (network/5xx/refresh window): keep polling on the same
        // backoff, but never silently forever.
        failures += 1
        if (failures >= TRANSIENT_NOTICE_THRESHOLD) setTrouble(true)
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

  if (expired) {
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
        <p className="text-sm max-w-md mx-auto" role="alert" style={{ color: '#B3261E' }}>
          {t('sessionExpired')}
        </p>
        <Link
          href={LOGIN_HREF}
          className="inline-block rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
        >
          {t('loginAgain')}
        </Link>
      </div>
    )
  }

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
      {trouble && (
        <p className="text-xs" role="status" style={{ color: '#B3261E' }}>
          {t('connectionTrouble')}
        </p>
      )}
    </div>
  )
}
