'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

/**
 * Phase C/D — session-authed org payments: list (C) + create/cancel (D).
 *
 * Reads AND mutates the active org's payment intents from the browser/session
 * path (`/api/v1/user/org/payment-intents`) via the `/api/backend` proxy + the
 * `apiCall` Bearer/refresh helper. NO wallet-signature auth, NO API key in the
 * browser. The UI is hard-locked to `test`: this hook never sends an
 * `environment` param, so the backend serves its `test` default and there is no
 * test/live toggle anywhere in `/app`.
 */

export interface OrgSplitLeg {
  address: string
  share_bps: number
  position: number
  label?: string | null
}

export interface OrgPaymentRecord {
  intent_id: string
  amount: number
  currency: string
  chain: string
  status: string
  recipient: string | null
  /** N-way split legs (recipient is null for split intents). */
  split?: OrgSplitLeg[] | null
  tx_hash: string | null
  matched_tx_hash: string | null
  created_at: string
  expires_at: string | null
}

export interface OrgPaymentsPayload {
  total: number
  page: number
  per_page: number
  records: OrgPaymentRecord[]
}

export interface CreateInvoiceInput {
  amount: number
  currency: string
  chain: string
  expires_in_minutes: number
  recipient?: string
  /** Non-custodial split: 2..20 legs, integer bps summing to exactly 10000.
   * Mutually exclusive with `recipient` (server-enforced 422). */
  split?: { address: string; share_bps: number }[]
}

/** Slice of PaymentIntentResponse the /app create flow needs (the pay link). */
export interface CreatedInvoice {
  intent_id: string
  recipient: string | null
  amount: number
  currency: string
  chain: string
  status: string
}

const PER_PAGE = 20

export function useOrgPayments() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [records, setRecords] = useState<OrgPaymentRecord[]>([])
  const [total, setTotal] = useState<number>(0)
  const [page, setPage] = useState<number>(1)
  const [statusFilter, setStatusFilterState] = useState<string>('') // '' = all
  // Bumped on active-org switch to force a refetch even when page is already 1.
  const [nonce, setNonce] = useState<number>(0)
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

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
      setRecords([])
      setTotal(0)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const q =
        `page=${page}&per_page=${PER_PAGE}` +
        (statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : '')
      const data = await apiCall<OrgPaymentsPayload>(
        `/api/v1/user/org/payment-intents?${q}`,
        tokenRef.current,
      )
      setRecords(data.records)
      setTotal(data.total)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      setRecords([])
      setTotal(0)
      console.error('[useOrgPayments] reload', e)
    } finally {
      setLoading(false)
    }
    // `nonce` is intentionally a dep: an org switch bumps it to refetch.
  }, [status, accessToken, page, nonce, statusFilter])

  useEffect(() => {
    void reload()
  }, [reload])

  // Active-org switch → a different org's payments; reset to page 1 and refetch.
  useEffect(() => {
    const onOrgChange = () => {
      setPage(1)
      setNonce((n) => n + 1)
    }
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [])

  const setStatusFilter = useCallback((s: string) => {
    setStatusFilterState(s)
    setPage(1)
  }, [])

  // Create an invoice (payment request) via the session path. No `environment`
  // param → the backend's `test` default (hard-lock). Throws the apiCall error
  // code on failure (the modal maps it, e.g. HTTP 422 → the recipient gate).
  const createIntent = useCallback(
    async (input: CreateInvoiceInput): Promise<CreatedInvoice> => {
      const token = await waitForToken(tokenRef)
      const result = await apiCall<CreatedInvoice>(
        '/api/v1/user/org/payment-intents',
        token,
        {
          method: 'POST',
          body: JSON.stringify({
            amount: input.amount,
            currency: input.currency,
            chain: input.chain,
            expires_in_minutes: input.expires_in_minutes,
            ...(input.recipient ? { recipient: input.recipient } : {}),
            ...(input.split ? { split: input.split } : {}),
          }),
        },
      )
      try {
        await reload()
      } catch (e) {
        console.warn('[useOrgPayments] reload after create failed', e)
      }
      return result
    },
    [reload],
  )

  const cancelIntent = useCallback(
    async (intentId: string): Promise<void> => {
      const token = await waitForToken(tokenRef)
      await apiCall<unknown>(
        `/api/v1/user/org/payment-intents/${intentId}/cancel`,
        token,
        { method: 'POST' },
      )
      try {
        await reload()
      } catch (e) {
        console.warn('[useOrgPayments] reload after cancel failed', e)
      }
    },
    [reload],
  )

  return {
    records,
    total,
    page,
    perPage: PER_PAGE,
    hasPrev: page > 1,
    hasNext: page * PER_PAGE < total,
    loading,
    error,
    isAuthed: status === 'authenticated',
    statusFilter,
    setStatusFilter,
    setPage,
    reload,
    createIntent,
    cancelIntent,
  }
}
