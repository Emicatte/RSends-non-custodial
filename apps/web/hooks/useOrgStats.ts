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
  /**
   * Machine-stable snake chain name (`base`, `base_sepolia`, `ethereum`,
   * `arbitrum`, `tron`, `tron_nile`), or `chain:{id}` for a chain the backend
   * cannot name. Badges and explorer links key on THIS, never on the label —
   * keying on display text is what let a badge map and an explorer map speak
   * two different vocabularies about the same row.
   *
   * Optional ONLY for deploy skew — the backend field is required and always
   * sent. Web and the backend deploy independently, so a build that reads this
   * can briefly meet an API that does not send it; the page resolves the gap to
   * the neutral badge rather than to a guessed chain.
   */
  chain_key?: string
  status: string
  recipient: string
  timestamp_iso: string
  /**
   * False ⇒ `amount_usd` carries no information: the token has no USD peg, so
   * rendering it as "$0.00" next to a real payment would be a lie. Show the
   * token symbol instead.
   */
  amount_usd_known: boolean
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
  // Settlements in the 24h window that `volume_24h` could NOT value and left
  // out. Without these two, `volume_24h === 0` is ambiguous: it means both
  // "nobody paid" and "paid in something we cannot value". `transactions_24h`
  // plus this count is what tells them apart, so the UI must never render the
  // volume tile without consulting it.
  volume_24h_unpriced_count: number
  /** Distinct symbols behind that count, e.g. `['ETH']`. May be empty when the
   *  token is unknown to the registry — the count still stands. */
  volume_24h_unpriced_symbols: string[]
  // The two tiles that replaced `total_balance` / `active_clients` on the /app
  // home. `total_balance` is hard-coded 0.0 by the backend and always was —
  // RSends is non-custodial, so a balance tile can only assert a custody the
  // product does not have — and `active_clients` is a fact about the business,
  // not the interface. Both fields are still SENT (narrowing a response is a
  // wire change nothing forces); nothing reads them any more.
  volume_30d: number
  volume_30d_delta_pct: number
  // Two counts, not a rate: 0/0 (no webhooks configured) and 0/N (every one
  // failed) are different facts, and a pre-divided percentage loses that.
  webhooks_delivered_24h: number
  webhooks_attempted_24h: number
  // Get-started checklist facts (drive the /app home card). The backend
  // returns 200 with zeroed KPIs + these booleans even for an org with no
  // owner identity yet (fresh merchant) — no 409 on this route anymore.
  settlement_wallet_set: boolean
  has_api_key: boolean
  has_paid_payment: boolean
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
