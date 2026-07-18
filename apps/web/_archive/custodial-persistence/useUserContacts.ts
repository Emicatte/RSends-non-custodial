'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export interface ServerContact {
  id: string
  address: string
  label: string
  last_used_at: string | null
  tx_count: number
  extra_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CreateContactPayload {
  address: string
  label: string
  last_used_at?: string
  tx_count?: number
  extra_metadata?: Record<string, unknown>
}

export interface UpdateContactPayload {
  label?: string
  last_used_at?: string
  tx_count?: number
  extra_metadata?: Record<string, unknown>
}

/** Shape used by AddressIntelligence.tsx (backward-compat with localStorage). */
export interface AddressContactLike {
  address: string
  label: string
  lastUsed: string
  txCount: number
}

interface BulkImportResponse {
  imported: number
  skipped: number
  errors: { address: string; error: string }[]
}

export function serverToLocal(c: ServerContact): AddressContactLike {
  return {
    address: c.address,
    label: c.label,
    lastUsed: c.last_used_at ?? '',
    txCount: c.tx_count,
  }
}

export function localToServer(c: AddressContactLike): CreateContactPayload {
  return {
    address: c.address,
    label: c.label ?? '',
    last_used_at: c.lastUsed && c.lastUsed.length > 0 ? c.lastUsed : undefined,
    tx_count: c.txCount ?? 0,
  }
}

export function useUserContacts() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const [contacts, setContacts] = useState<ServerContact[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      setContacts([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<ServerContact[]>(
        '/api/v1/user/contacts',
        tokenRef.current,
      )
      setContacts(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const upsert = useCallback(
    async (payload: CreateContactPayload) => {
      if (status !== 'authenticated') return null
      try {
        const token = await waitForToken(tokenRef)
        const c = await apiCall<ServerContact>(
          '/api/v1/user/contacts',
          token,
          { method: 'POST', body: JSON.stringify(payload) },
        )
        setContacts((prev) => {
          const idx = prev.findIndex((x) => x.id === c.id)
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = c
            return next
          }
          return [c, ...prev]
        })
        return c
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [status],
  )

  const update = useCallback(
    async (id: string, patch: UpdateContactPayload) => {
      if (status !== 'authenticated') return null
      try {
        const token = await waitForToken(tokenRef)
        const c = await apiCall<ServerContact>(
          `/api/v1/user/contacts/${id}`,
          token,
          { method: 'PATCH', body: JSON.stringify(patch) },
        )
        setContacts((prev) => prev.map((x) => (x.id === id ? c : x)))
        return c
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [status],
  )

  const remove = useCallback(
    async (id: string) => {
      if (status !== 'authenticated') return
      const token = await waitForToken(tokenRef)
      try {
        await apiCall<void>(`/api/v1/user/contacts/${id}`, token, {
          method: 'DELETE',
        })
      } catch {
        /* 204 bodies are empty; apiCall's JSON parse may throw — ignore */
      }
      setContacts((prev) => prev.filter((x) => x.id !== id))
    },
    [status],
  )

  const clearAll = useCallback(async () => {
    if (status !== 'authenticated') return
    const token = await waitForToken(tokenRef)
    try {
      await apiCall<void>('/api/v1/user/contacts', token, {
        method: 'DELETE',
      })
    } catch {
      /* 204 body empty */
    }
    setContacts([])
  }, [status])

  const bulkImport = useCallback(
    async (items: CreateContactPayload[]) => {
      if (status !== 'authenticated' || items.length === 0) return null
      try {
        const token = await waitForToken(tokenRef)
        const res = await apiCall<BulkImportResponse>(
          '/api/v1/user/contacts/bulk-import',
          token,
          { method: 'POST', body: JSON.stringify({ contacts: items }) },
        )
        await reload()
        return res
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        return null
      }
    },
    [status, reload],
  )

  return {
    contacts,
    loading,
    error,
    isAuthed: status === 'authenticated',
    reload,
    upsert,
    update,
    remove,
    clearAll,
    bulkImport,
  }
}
