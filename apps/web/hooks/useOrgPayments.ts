'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall } from '@/lib/auth-client'

/**
 * Phase C — session-authed org payments list.
 *
 * Reads the active org's payment intents from the browser/session path
 * (`GET /api/v1/user/org/payment-intents`) via the `/api/backend` proxy + the
 * `apiCall` Bearer/refresh helper. NO wallet-signature auth, NO API key in the
 * browser. The UI is hard-locked to `test`: this hook never sends an
 * `environment` param, so the backend serves its `test` default and there is no
 * test/live toggle anywhere in `/app`.
 */

export interface OrgPaymentRecord {
  intent_id: string
  amount: number
  currency: string
  chain: string
  status: string
  recipient: string | null
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

const PER_PAGE = 20

export function useOrgPayments() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [records, setRecords] = useState<OrgPaymentRecord[]>([])
  const [total, setTotal] = useState<number>(0)
  const [page, setPage] = useState<number>(1)
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
      const data = await apiCall<OrgPaymentsPayload>(
        `/api/v1/user/org/payment-intents?page=${page}&per_page=${PER_PAGE}`,
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
  }, [status, accessToken, page, nonce])

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
    setPage,
    reload,
  }
}
