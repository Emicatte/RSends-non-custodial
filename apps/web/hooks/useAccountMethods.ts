'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export interface AuthMethods {
  has_password: boolean
  has_google: boolean
  has_github: boolean
  google_email: string | null
  github_username: string | null
}

export function useAccountMethods() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [methods, setMethods] = useState<AuthMethods | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
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

  const clearError = useCallback(() => setError(null), [])

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setMethods(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<AuthMethods>(
        '/api/v1/user/account/auth-methods',
        tokenRef.current,
      )
      setMethods(data)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useAccountMethods] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const _mutate = useCallback(
    async (path: string, body?: unknown) => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<{ status: string }>(
          `/api/v1/user/account/${path}`,
          token,
          {
            method: 'POST',
            body: body !== undefined ? JSON.stringify(body) : undefined,
          },
        )
        await reload()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [reload],
  )

  const addPassword = useCallback(
    (password: string) => _mutate('add-password', { password }),
    [_mutate],
  )
  const removePassword = useCallback(
    () => _mutate('remove-password'),
    [_mutate],
  )
  const linkGoogle = useCallback(
    (id_token: string) => _mutate('link-google', { id_token }),
    [_mutate],
  )
  const unlinkGoogle = useCallback(() => _mutate('unlink-google'), [_mutate])
  const linkGithub = useCallback(
    (access_token: string) => _mutate('link-github', { access_token }),
    [_mutate],
  )
  const unlinkGithub = useCallback(() => _mutate('unlink-github'), [_mutate])

  return {
    methods,
    loading,
    saving,
    error,
    clearError,
    reload,
    addPassword,
    removePassword,
    linkGoogle,
    unlinkGoogle,
    linkGithub,
    unlinkGithub,
  }
}
