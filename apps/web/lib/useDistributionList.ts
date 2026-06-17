'use client'

import { useState, useEffect, useCallback } from 'react'
import { mutationHeaders, parseRSendError } from './rsendFetch'
import { useWalletAuth } from './walletAuth'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'

// ═══════════════════════════════════════════════════════════
//  TYPES
// ═══════════════════════════════════════════════════════════

export interface DistributionEntry {
  address: string
  label: string
  percent: number
}

export interface DistributionList {
  id: number
  owner_address: string
  name: string
  entries: DistributionEntry[]
  created_at: string | null
  updated_at: string | null
}

// ═══════════════════════════════════════════════════════════
//  HOOK
// ═══════════════════════════════════════════════════════════

export function useDistributionList(address: string | undefined) {
  const [lists, setLists] = useState<DistributionList[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { signOnce, getAuthHeaders, clearCache } = useWalletAuth(address)

  const fetchLists = useCallback(async (silent = false) => {
    if (!address) return
    if (!silent) setLoading(true)
    try {
      const doFetch = async () => {
        const headers = await getAuthHeaders()
        return fetch(
          `${BACKEND}/api/v1/distributions`,
          { headers, signal: AbortSignal.timeout(15000) },
        )
      }
      let res = await doFetch()
      if (res.status === 401) {
        clearCache()
        res = await doFetch()
      }
      if (res.ok) {
        const data = await res.json()
        setLists(data.lists ?? [])
        setError(null)
      }
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : String(e))
    }
    if (!silent) setLoading(false)
  }, [address, getAuthHeaders, clearCache])

  useEffect(() => { fetchLists() }, [fetchLists])

  const createList = useCallback(async (name: string, entries: DistributionEntry[]) => {
    if (!address) throw new Error('Wallet not connected')
    const isoTimestamp = new Date().toISOString()
    const message = `RSends:${address}:${isoTimestamp}`
    const signature = await signOnce(message)

    const res = await fetch(`${BACKEND}/api/v1/distributions`, {
      method: 'POST',
      headers: mutationHeaders({
        'X-Wallet-Address': address,
        'X-Wallet-Signature': signature,
        'X-Timestamp': isoTimestamp,
      }),
      body: JSON.stringify({ owner_address: address, name, entries }),
    })
    if (!res.ok) throw new Error(await parseRSendError(res))
    await fetchLists()
    return res.json()
  }, [address, fetchLists, signOnce])

  const deleteList = useCallback(async (id: number) => {
    if (!address) throw new Error('Wallet not connected')
    const isoTimestamp = new Date().toISOString()
    const message = `RSends:${address}:${isoTimestamp}`
    const signature = await signOnce(message)

    const res = await fetch(`${BACKEND}/api/v1/distributions/${id}`, {
      method: 'DELETE',
      headers: mutationHeaders({
        'X-Wallet-Address': address,
        'X-Wallet-Signature': signature,
        'X-Timestamp': isoTimestamp,
      }),
      body: JSON.stringify({ owner_address: address }),
    })
    if (!res.ok) throw new Error(await parseRSendError(res))
    await fetchLists()
  }, [address, fetchLists, signOnce])

  return { lists, loading, error, refresh: () => fetchLists(), createList, deleteList }
}
