'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall } from '@/lib/auth-client'

/**
 * Phase E — session-authed org stats (KPI snapshot with USD conversion).
 *
 * Reads `GET /api/v1/user/org/stats` via the `/api/backend` proxy + `apiCall`
 * Bearer/refresh helper. This REPLACES the `/app` home widget's previous
 * wallet-signature read of `/api/v1/dashboard/stats`, whose primary-wallet
 * scope broke once an org's `settlement_wallet` ≠ its primary wallet. Hard-
 * locked to `test` (no `environment` param → backend `test` default). Polls,
 * and refetches on an active-org switch.
 */

export interface RecentTransactionDTO {
  id: number
  tx_hash: string | null
  type: string
  amount_usd: number
  currency: string
  chain: string
  status: string
  recipient: string
  timestamp_iso: string
}

export interface OrgStats {
  volume_24h: number
  volume_24h_delta_pct: number
  transactions_24h: number
  transactions_24h_delta: number
  total_balance: number
  total_balance_chains: number
  active_clients: number
  active_clients_this_week: number
  recent_transactions: RecentTransactionDTO[]
}

const POLL_MS = 30_000

export function useOrgStats() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [stats, setStats] = useState<OrgStats | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<boolean>(false)
  // Bumped on active-org switch to force a refetch.
  const [nonce, setNonce] = useState<number>(0)

  useEffect(() => {
    tokenRef.current = (session as { access_token?: string } | null)
      ?.access_token
  }, [session])

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const t = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (t) tokenRef.current = t
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [])

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setStats(null)
      setError(false)
      setLoading(false)
      return
    }
    try {
      const data = await apiCall<OrgStats>(
        '/api/v1/user/org/stats',
        tokenRef.current,
      )
      setStats(data)
      setError(false)
    } catch (e) {
      setError(true)
      setStats(null)
      console.error('[useOrgStats] reload', e)
    } finally {
      setLoading(false)
    }
    // `nonce` is intentionally a dep: an org switch bumps it to refetch.
  }, [status, accessToken, nonce])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    if (status !== 'authenticated') return
    const id = window.setInterval(() => {
      void reload()
    }, POLL_MS)
    return () => window.clearInterval(id)
  }, [reload, status])

  useEffect(() => {
    const onOrgChange = () => setNonce((n) => n + 1)
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [])

  return { stats, loading, error, isAuthed: status === 'authenticated', reload }
}
