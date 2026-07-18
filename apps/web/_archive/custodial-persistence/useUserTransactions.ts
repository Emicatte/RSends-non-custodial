'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export type ServerTxType =
  | 'transfer'
  | 'swap'
  | 'approve'
  | 'wrap'
  | 'unwrap'
  | 'split'
  | 'bridge'

export type ServerTxStatus =
  | 'pending'
  | 'confirming'
  | 'confirmed'
  | 'failed'
  | 'cancelled'

export type ServerTxDirection = 'out' | 'in'

export interface ServerTransaction {
  id: string
  chain_id: number
  tx_hash: string
  wallet_address: string
  tx_type: ServerTxType
  tx_status: ServerTxStatus
  direction: ServerTxDirection
  token_symbol: string | null
  token_address: string | null
  amount_raw: string | null
  amount_decimal: string | null
  counterparty_address: string | null
  extra_metadata: Record<string, unknown>
  gas_used: number | null
  gas_price_gwei: string | null
  block_number: number | null
  submitted_at: string
  confirmed_at: string | null
  updated_at: string
}

export interface CreateTxPayload {
  chain_id: number
  tx_hash: string
  wallet_address: string
  tx_type: ServerTxType
  tx_status?: ServerTxStatus
  direction?: ServerTxDirection
  token_symbol?: string | null
  token_address?: string | null
  amount_raw?: string | null
  amount_decimal?: string | null
  counterparty_address?: string | null
  extra_metadata?: Record<string, unknown>
  submitted_at?: string
}

export interface UpdateTxPayload {
  tx_status?: ServerTxStatus
  gas_used?: number
  gas_price_gwei?: string
  block_number?: number
  confirmed_at?: string
  extra_metadata?: Record<string, unknown>
}

export interface TxFilters {
  chain_id?: number
  tx_type?: string
  tx_status?: string
}

interface PaginatedResponse {
  items: ServerTransaction[]
  next_cursor: string | null
  has_more: boolean
}

interface BulkImportResponse {
  imported: number
  skipped: number
  errors: { tx_hash: string; error: string }[]
}

export function useUserTransactions(filters: TxFilters = {}) {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const [transactions, setTransactions] = useState<ServerTransaction[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const cursorRef = useRef<string | null>(null)

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

  const buildQuery = useCallback(
    (cursor?: string | null) => {
      const params = new URLSearchParams()
      if (filters.chain_id !== undefined) params.set('chain_id', String(filters.chain_id))
      if (filters.tx_type) params.set('tx_type', filters.tx_type)
      if (filters.tx_status) params.set('tx_status', filters.tx_status)
      if (cursor) params.set('cursor', cursor)
      return params.toString()
    },
    [filters.chain_id, filters.tx_type, filters.tx_status],
  )

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setTransactions([])
      cursorRef.current = null
      setHasMore(false)
      return
    }
    setLoading(true)
    setError(null)
    cursorRef.current = null
    try {
      const q = buildQuery()
      const data = await apiCall<PaginatedResponse>(
        `/api/v1/user/transactions${q ? `?${q}` : ''}`,
        tokenRef.current,
      )
      setTransactions(data.items)
      setHasMore(data.has_more)
      cursorRef.current = data.next_cursor
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status, accessToken, buildQuery])

  useEffect(() => {
    void reload()
  }, [reload])

  const loadMore = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken || !cursorRef.current || loading) return
    setLoading(true)
    try {
      const q = buildQuery(cursorRef.current)
      const data = await apiCall<PaginatedResponse>(
        `/api/v1/user/transactions?${q}`,
        tokenRef.current,
      )
      setTransactions((prev) => [...prev, ...data.items])
      setHasMore(data.has_more)
      cursorRef.current = data.next_cursor
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status, accessToken, loading, buildQuery])

  const create = useCallback(async (payload: CreateTxPayload) => {
    if (status !== 'authenticated') return null
    try {
      const token = await waitForToken(tokenRef)
      const tx = await apiCall<ServerTransaction>(
        '/api/v1/user/transactions',
        token,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      setTransactions((prev) => {
        const idx = prev.findIndex((t) => t.id === tx.id)
        if (idx >= 0) {
          const next = [...prev]
          next[idx] = tx
          return next
        }
        return [tx, ...prev]
      })
      return tx
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [status])

  const update = useCallback(async (id: string, patch: UpdateTxPayload) => {
    if (status !== 'authenticated') return null
    try {
      const token = await waitForToken(tokenRef)
      const tx = await apiCall<ServerTransaction>(
        `/api/v1/user/transactions/${id}`,
        token,
        { method: 'PATCH', body: JSON.stringify(patch) },
      )
      setTransactions((prev) => prev.map((t) => (t.id === id ? tx : t)))
      return tx
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [status])

  const remove = useCallback(async (id: string) => {
    if (status !== 'authenticated') return
    const token = await waitForToken(tokenRef)
    await apiCall<void>(`/api/v1/user/transactions/${id}`, token, {
      method: 'DELETE',
    })
    setTransactions((prev) => prev.filter((t) => t.id !== id))
  }, [status])

  const clearAll = useCallback(async () => {
    if (status !== 'authenticated') return
    const token = await waitForToken(tokenRef)
    await apiCall<void>('/api/v1/user/transactions', token, {
      method: 'DELETE',
    })
    setTransactions([])
    cursorRef.current = null
    setHasMore(false)
  }, [status])

  const bulkImport = useCallback(async (txs: CreateTxPayload[]) => {
    if (status !== 'authenticated' || txs.length === 0) return null
    try {
      const token = await waitForToken(tokenRef)
      const res = await apiCall<BulkImportResponse>(
        '/api/v1/user/transactions/bulk-import',
        token,
        { method: 'POST', body: JSON.stringify({ transactions: txs }) },
      )
      await reload()
      return res
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      return null
    }
  }, [status, reload])

  return {
    transactions,
    loading,
    error,
    hasMore,
    isAuthed: status === 'authenticated',
    reload,
    loadMore,
    create,
    update,
    remove,
    clearAll,
    bulkImport,
  }
}
