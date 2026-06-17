'use client'

/**
 * useMerchantInvoices — fatture delle commissioni (Settings → Fatture).
 *
 * GET  /api/v1/merchant/invoices          → lista
 * POST /api/v1/merchant/invoices          → genera (draft) per un periodo
 * POST /api/v1/merchant/invoices/{id}/issue → draft→issued (se cliente completo)
 *
 * Stesso pattern auth dello Step 2 (useMerchantProfile): apiCall + tokenRef +
 * waitForToken. Il PDF è generato client-side (lib/usePdfInvoice). Il caso
 * no_primary_wallet è esposto come negli altri tab Fatturazione.
 */

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'
import type { InvoicePdfData } from '@/lib/usePdfInvoice'

export interface InvoiceRecord extends InvoicePdfData {
  id: string
  owner_address: string
}

interface InvoiceListPayload {
  invoices: InvoiceRecord[]
}

const BASE = '/api/v1/merchant/invoices'

export function useMerchantInvoices() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const { activeOrg, role: currentUserRole } = useCurrentOrg()

  const [invoices, setInvoices] = useState<InvoiceRecord[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [noPrimaryWallet, setNoPrimaryWallet] = useState<boolean>(false)

  useEffect(() => {
    tokenRef.current = (session as { access_token?: string } | null)?.access_token
  }, [session])

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const t = (e as CustomEvent<{ access_token?: string }>).detail?.access_token
      if (t) tokenRef.current = t
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [])

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setInvoices([])
      return
    }
    setLoading(true)
    setError(null)
    setNoPrimaryWallet(false)
    try {
      const token = await waitForToken(tokenRef)
      const data = await apiCall<InvoiceListPayload>(BASE, token)
      setInvoices(data.invoices || [])
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      if (code === 'no_primary_wallet') setNoPrimaryWallet(true)
      else setError(code)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const create = useCallback(
    async (periodStart: string, periodEnd: string): Promise<InvoiceRecord | null> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const rec = await apiCall<InvoiceRecord>(BASE, token, {
          method: 'POST',
          body: JSON.stringify({ period_start: periodStart, period_end: periodEnd }),
        })
        await reload()
        return rec
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        if (code === 'no_primary_wallet') setNoPrimaryWallet(true)
        setError(code)
        return null
      } finally {
        setSaving(false)
      }
    },
    [reload],
  )

  const issue = useCallback(
    async (id: string): Promise<boolean> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<InvoiceRecord>(`${BASE}/${id}/issue`, token, { method: 'POST' })
        await reload()
        return true
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        return false
      } finally {
        setSaving(false)
      }
    },
    [reload],
  )

  return {
    invoices,
    loading,
    saving,
    error,
    noPrimaryWallet,
    isAuthed: status === 'authenticated',
    activeOrg,
    currentUserRole,
    reload,
    create,
    issue,
    clearError: () => setError(null),
  }
}
