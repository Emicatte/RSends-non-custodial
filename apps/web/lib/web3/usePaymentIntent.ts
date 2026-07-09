'use client'

/**
 * lib/web3/usePaymentIntent — fetch-only driver for the hosted checkout's
 * intent data (the previous WebSocket channel is intentionally gone; polling
 * with backoff does the job and is testable with mock timers).
 *
 * Phases:
 * - loading (with a `slow` notice flag) while the initial fetch retries with
 *   backoff — a blank or frozen screen is never acceptable, so failures
 *   retry forever; only a definitive 404 short-circuits to not_found.
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
import { SLOW_NOTICE_AFTER, pollDelay, type PollKind } from '@/lib/web3/intentPoll'

export type IntentPhase =
  | { kind: 'loading'; slow: boolean }
  | { kind: 'not_found' }
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

  const schedule = useCallback((run: () => void) => {
    if (modeRef.current === 'stopped') return
    clearTimer()
    const delay = pollDelay(
      modeRef.current,
      attemptRef.current,
      Date.now() - startedAtRef.current,
    )
    timerRef.current = setTimeout(run, delay)
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
    } catch {
      if (!mountedRef.current || modeRef.current === 'stopped') return
      // Initial failures retry forever with backoff; watch/sync just keep
      // their cadence (a transient error must not kill the poll). Schedule
      // with the CURRENT attempt (first retry uses the first delay), then
      // advance the counter for the next round.
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
