'use client'

/**
 * lib/web3/usePaymentIntent — fetch-only driver for the hosted checkout's
 * intent data (the previous WebSocket channel is intentionally gone; polling
 * with backoff does the job and is testable with mock timers).
 *
 * Phases:
 * - loading (with a `slow` notice flag) while the initial fetch retries with
 *   backoff; a definitive 404 short-circuits to not_found.
 * - unreachable once the initial fetch has been failing for
 *   INITIAL_RETRY_GIVE_UP_AFTER. A blank or frozen screen is still never
 *   acceptable — this phase is the opposite of frozen: it states that the
 *   payment service cannot be reached and hands the payer a retry. The
 *   automatic timer stops there, and `online`/tab-refocus resumes it, so a
 *   recovered network needs no reload.
 * - ready(intent): while `status === 'pending'` a steady watch poll catches
 *   paid-elsewhere / expiry flips (the backend's _effective_status reports
 *   pending-past-expiry as expired).
 * - startSyncPolling(): called when the payer's tx mines; switches to the
 *   quick sync backoff until the backend reflects the payment, then stops.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  PAID_STATES,
  normalizeIntent,
  type PaymentIntent,
  type RawPaymentIntent,
} from '@/lib/web3/paymentIntent'
import {
  INITIAL_RETRY_GIVE_UP_AFTER,
  SLOW_NOTICE_AFTER,
  pollDelay,
  throttleDelay,
  type PollKind,
} from '@/lib/web3/intentPoll'

export type IntentPhase =
  | { kind: 'loading'; slow: boolean }
  | { kind: 'not_found' }
  | { kind: 'unreachable'; detail: string | null }
  | { kind: 'ready'; intent: PaymentIntent }

export interface UsePaymentIntentResult {
  phase: IntentPhase
  backendPaid: boolean
  refresh: () => void
  startSyncPolling: () => void
}

export function usePaymentIntent(intentId: string): UsePaymentIntentResult {
  const [phase, setPhase] = useState<IntentPhase>({ kind: 'loading', slow: false })
  const [backendPaid, setBackendPaid] = useState(false)

  const modeRef = useRef<PollKind | 'stopped'>('initial')
  const attemptRef = useRef(0)
  const startedAtRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const slowTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const scheduleIn = useCallback((delay: number, run: () => void) => {
    if (modeRef.current === 'stopped') return
    clearTimer()
    timerRef.current = setTimeout(run, delay)
  }, [])

  const schedule = useCallback(
    (run: () => void) => {
      if (modeRef.current === 'stopped') return
      scheduleIn(
        pollDelay(
          modeRef.current,
          attemptRef.current,
          Date.now() - startedAtRef.current,
        ),
        run,
      )
    },
    [scheduleIn],
  )

  /**
   * The initial fetch, and only it, gives up after its window: the payer has
   * seen nothing at all, so an honest "cannot reach the service" plus a retry
   * beats a shimmer that never resolves. Returns true once it has done so.
   */
  const giveUpIfInitialExhausted = useCallback((detail: string | null) => {
    if (
      modeRef.current !== 'initial' ||
      Date.now() - startedAtRef.current < INITIAL_RETRY_GIVE_UP_AFTER
    ) {
      return false
    }
    modeRef.current = 'stopped'
    clearTimer()
    if (slowTimerRef.current) {
      clearTimeout(slowTimerRef.current)
      slowTimerRef.current = null
    }
    setPhase({ kind: 'unreachable', detail })
    return true
  }, [])

  const tick = useCallback(async () => {
    if (!mountedRef.current || modeRef.current === 'stopped') return
    try {
      const res = await fetch(`/api/pay/${encodeURIComponent(intentId)}`, {
        cache: 'no-store',
      })
      if (!mountedRef.current) return

      if (res.status === 404) {
        modeRef.current = 'stopped'
        if (slowTimerRef.current) clearTimeout(slowTimerRef.current)
        setPhase({ kind: 'not_found' })
        return
      }
      // Rate limited (429), or the limiter itself is down and failing closed
      // (503 RATE_LIMIT_UNAVAILABLE). Both mean "ask again later", and both are
      // made worse by the steady cadence the other errors deliberately keep:
      // each retry re-enters the very bucket it is waiting on.
      if (res.status === 429 || res.status === 503) {
        if (giveUpIfInitialExhausted(`HTTP ${res.status}`)) return
        scheduleIn(throttleDelay(retryAfterSeconds(res)), () => void tick())
        return
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const raw = (await res.json()) as RawPaymentIntent
      if (!mountedRef.current) return
      const intent = normalizeIntent(raw, intentId)

      if (slowTimerRef.current) {
        clearTimeout(slowTimerRef.current)
        slowTimerRef.current = null
      }
      setPhase({ kind: 'ready', intent })

      if (PAID_STATES.has(intent.status)) {
        setBackendPaid(true)
        modeRef.current = 'stopped'
        return
      }

      if (modeRef.current === 'initial') {
        // Loaded: switch to the pending watch (or stop on a terminal status).
        modeRef.current = intent.status === 'pending' ? 'watch' : 'stopped'
        attemptRef.current = 0
        startedAtRef.current = Date.now()
      } else if (modeRef.current === 'watch' && intent.status !== 'pending') {
        modeRef.current = 'stopped'
      } else {
        attemptRef.current += 1
      }
      schedule(() => void tick())
    } catch (err) {
      if (!mountedRef.current || modeRef.current === 'stopped') return
      // The INITIAL fetch gives up after the window: the payer has seen
      // nothing at all so far, so an honest "cannot reach the service" with a
      // retry beats a shimmer that never resolves. watch/sync keep their
      // cadence instead — there the intent is already on screen and a
      // transient error must not kill the poll.
      if (giveUpIfInitialExhausted(errorDetail(err))) return
      // Schedule with the CURRENT attempt (first retry uses the first delay),
      // then advance the counter for the next round.
      schedule(() => void tick())
      attemptRef.current += 1
    }
  }, [intentId, schedule])

  const refresh = useCallback(() => {
    if (modeRef.current === 'stopped') modeRef.current = 'watch'
    clearTimer()
    void tick()
  }, [tick])

  const startSyncPolling = useCallback(() => {
    modeRef.current = 'sync'
    attemptRef.current = 0
    startedAtRef.current = Date.now()
    schedule(() => void tick())
  }, [schedule, tick])

  // Coming back from an outage must not require a reload. Once we have given
  // up, the browser telling us connectivity returned (or the payer returning
  // to the tab) is the cheapest possible signal to try again.
  const unreachableRef = useRef(false)
  unreachableRef.current = phase.kind === 'unreachable'

  useEffect(() => {
    const resume = () => {
      if (!mountedRef.current || !unreachableRef.current) return
      if (typeof document !== 'undefined' && document.hidden) return
      refresh()
    }
    window.addEventListener('online', resume)
    document.addEventListener('visibilitychange', resume)
    return () => {
      window.removeEventListener('online', resume)
      document.removeEventListener('visibilitychange', resume)
    }
  }, [refresh])

  useEffect(() => {
    mountedRef.current = true
    modeRef.current = 'initial'
    attemptRef.current = 0
    startedAtRef.current = Date.now()
    setPhase({ kind: 'loading', slow: false })
    setBackendPaid(false)

    slowTimerRef.current = setTimeout(() => {
      if (!mountedRef.current) return
      setPhase((p) => (p.kind === 'loading' ? { kind: 'loading', slow: true } : p))
    }, SLOW_NOTICE_AFTER)

    void tick()

    return () => {
      mountedRef.current = false
      modeRef.current = 'stopped'
      clearTimer()
      if (slowTimerRef.current) clearTimeout(slowTimerRef.current)
    }
  }, [intentId, tick])

  return { phase, backendPaid, refresh, startSyncPolling }
}

/**
 * The server's Retry-After in seconds, or null when it is absent or not a
 * number. The proxy replays the header precisely so this can be read.
 */
function retryAfterSeconds(res: Response): number | null {
  const raw = res.headers?.get?.('retry-after')
  if (!raw) return null
  const seconds = Number(raw)
  return Number.isFinite(seconds) ? seconds : null
}

/** First line of the raw error, bounded. Support-facing only, never a headline. */
function errorDetail(err: unknown): string | null {
  if (err == null) return null
  const raw = err instanceof Error ? err.message : String(err)
  return raw.split('\n')[0].slice(0, 160) || null
}
