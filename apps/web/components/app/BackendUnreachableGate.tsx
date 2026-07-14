'use client'

/**
 * Full-page retry gate rendered by the /app and /settings layouts when the
 * server-side onboarding guard resolves 'unreachable' (network error,
 * timeout, 5xx — e.g. the Render free-tier cold start) or 'stale-token'
 * (expired access token — the probe below refreshes it via apiCall and hands
 * back to the guard, so the user stays on their URL instead of bouncing
 * through /onboarding).
 *
 * The absence of an answer is not a denial. This component re-asks the guard's
 * exact question (getOnboardingState via apiCall, Bearer + one-shot cookie
 * refresh) and classifies the outcome by whether the backend answered at all:
 *
 *   - any HTTP response (2xx or 4xx) => backend REACHABLE => router.refresh()
 *     hands back to the server guard, which is the authority on 4xx (it
 *     redirects those to the /onboarding gate). Bounded rechecks so a
 *     persistently server-slow backend can't freeze us on the skeleton.
 *   - a definitive auth death (session_expired from a failed refresh, or a 401
 *     that survived the one-shot refresh) => router.replace('/login').
 *   - network error / timeout / 5xx => still unreachable => backoff retry, then
 *     an explicit error card with a retry action. Never a silent bounce.
 *
 * Classification is by HTTP STATUS (apiCall carries err.status), not by
 * matching the per-route body-code string.
 */

import { useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { useTranslations } from 'next-intl'
import { useRouter } from '@/i18n/navigation'
import { getOnboardingState } from '@/lib/onboarding-client'

/** Sequential waits between outage retries — 90s total, beyond the free-tier
 * cold start. Exported so tests drive the exact schedule. */
export const RETRY_DELAYS_MS = [
  2_000, 4_000, 8_000, 15_000, 15_000, 15_000, 15_000, 16_000,
]

/** After a reachable response, how long to wait before re-checking whether the
 * server guard has cleared the gate, and how many such rechecks before giving
 * up (bounds the reachable-but-server-slow case so it can't hang). */
export const RECHECK_MS = 5_000
export const MAX_RECHECKS = 6

const PULSE = {
  borderRadius: 8,
  background: '#e5e4e0',
  animation: 'rsendsPulse 1.5s ease-in-out infinite',
} as const

export function BackendUnreachableGate() {
  const t = useTranslations('onboarding.gate.unreachable')
  const router = useRouter()
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)
    ?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [phase, setPhase] = useState<'retrying' | 'exhausted'>('retrying')
  // Increments on Try again so the retry effect restarts from a clean budget.
  const [round, setRound] = useState(0)

  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const tok = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (tok) tokenRef.current = tok
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [])

  useEffect(() => {
    if (phase !== 'retrying') return
    if (status === 'unauthenticated') {
      router.replace('/login')
      return
    }
    // Wait for a token before probing — a tokenless probe would 401 and
    // muddy the reachable-vs-denied classification.
    if (status !== 'authenticated') return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let outageIdx = 0
    let rechecks = 0

    const scheduleOutage = () => {
      if (outageIdx >= RETRY_DELAYS_MS.length) {
        setPhase('exhausted')
        return
      }
      timer = setTimeout(() => void attempt(), RETRY_DELAYS_MS[outageIdx++])
    }

    const handBackToServerGuard = () => {
      // Backend answered → re-run the server guard, which routes with full
      // information (dashboard, an onboarding step, or the /onboarding gate on
      // a 4xx). If it still renders us, the server timed out while the client
      // could reach the backend: re-check a bounded number of times so we
      // never freeze on the skeleton.
      router.refresh()
      rechecks += 1
      if (rechecks > MAX_RECHECKS) {
        setPhase('exhausted')
        return
      }
      timer = setTimeout(() => void attempt(), RECHECK_MS)
    }

    const attempt = async () => {
      try {
        await getOnboardingState(tokenRef.current)
      } catch (e) {
        if (cancelled) return
        const message = e instanceof Error ? e.message : ''
        const httpStatus = (e as { status?: number } | null)?.status
        if (message === 'session_expired' || httpStatus === 401) {
          // Session is genuinely dead (refresh failed, or a fresh token is
          // still rejected) — retrying would loop.
          router.replace('/login')
          return
        }
        if (typeof httpStatus === 'number' && httpStatus < 500) {
          // Reachable but denied (e.g. 403) — let the server guard decide.
          handBackToServerGuard()
          return
        }
        // 5xx or network/timeout (no status) — still an outage.
        scheduleOutage()
        return
      }
      if (cancelled) return
      handBackToServerGuard()
    }

    void attempt()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [phase, round, status, router])

  if (phase === 'retrying') {
    return (
      <div
        className="min-h-screen px-6 py-16"
        style={{ background: '#f7f6f3' }}
        aria-busy="true"
        data-testid="backend-unreachable-skeleton"
      >
        <style>{`@keyframes rsendsPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>
        <div className="max-w-md mx-auto space-y-3" aria-hidden="true">
          <div style={{ ...PULSE, height: 20, width: '40%' }} />
          <div style={{ ...PULSE, height: 42 }} />
          <div style={{ ...PULSE, height: 42 }} />
        </div>
      </div>
    )
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-6"
      style={{ background: '#f7f6f3' }}
    >
      <div
        role="alert"
        className="max-w-md w-full rounded-2xl border p-6 text-center space-y-4"
        style={{ borderColor: '#DDDCD6', background: '#FFFFFF' }}
      >
        <h1 className="text-lg font-semibold" style={{ color: '#2C2C2A' }}>
          {t('heading')}
        </h1>
        <p className="text-sm" style={{ color: '#888780' }}>
          {t('body')}
        </p>
        <button
          type="button"
          onClick={() => {
            setPhase('retrying')
            setRound((r) => r + 1)
          }}
          className="rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: '#DDDCD6', color: '#2C2C2A' }}
        >
          {t('retry')}
        </button>
      </div>
    </div>
  )
}
