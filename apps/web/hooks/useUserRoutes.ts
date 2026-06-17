'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export interface SavedRoute {
  id: string
  name: string
  route_config: Record<string, unknown>
  is_favorite: boolean
  created_at: string
  updated_at: string
  last_used_at: string | null
  use_count: number
}

export function useUserRoutes() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const [routes, setRoutes] = useState<SavedRoute[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Keep tokenRef in sync with NextAuth session + auto-refresh events.
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
      setRoutes([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<SavedRoute[]>('/api/v1/user/routes', tokenRef.current)
      setRoutes(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const save = useCallback(
    async (name: string, config: Record<string, unknown>, isFavorite = false) => {
      const token = await waitForToken(tokenRef)
      const created = await apiCall<SavedRoute>(
        '/api/v1/user/routes',
        token,
        {
          method: 'POST',
          body: JSON.stringify({
            name,
            route_config: config,
            is_favorite: isFavorite,
          }),
        },
      )
      setRoutes((r) => [created, ...r])
      return created
    },
    [],
  )

  const remove = useCallback(async (id: string) => {
    const token = await waitForToken(tokenRef)
    await apiCall<void>(`/api/v1/user/routes/${id}`, token, {
      method: 'DELETE',
    })
    setRoutes((r) => r.filter((x) => x.id !== id))
  }, [])

  return {
    routes,
    loading,
    error,
    save,
    remove,
    reload,
    isAuthed: status === 'authenticated',
  }
}
