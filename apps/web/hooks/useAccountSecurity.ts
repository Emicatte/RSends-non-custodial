'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

/**
 * Hook for `/settings/security` — owns the three backend surfaces the page
 * renders (status, sessions, known-devices) plus the request/cancel delete
 * flow. Pattern (`tokenRef` + `rsends:token-refreshed`) mirrors
 * `useUserWallets` so a silent refresh never breaks in-flight requests.
 */

export interface ActiveSession {
  session_id: string
  created_at: string
  last_activity_at: string | null
  ip_address: string | null
  user_agent_snippet: string | null
  is_current: boolean
}

export interface KnownDevice {
  id: string
  user_agent_snippet: string | null
  ip_last_seen: string | null
  first_seen_at: string
  last_seen_at: string
  login_count: number
}

export interface AccountStatus {
  email: string
  display_name: string | null
  created_at: string
  deletion_requested_at: string | null
  deletion_scheduled_for: string | null
  deletion_reason: string | null
  days_until_deletion: number | null
}

export interface DeletionRequestInput {
  reason?: string
  confirmation: string
}

export function useAccountSecurity() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [accountStatus, setAccountStatus] = useState<AccountStatus | null>(null)
  const [sessions, setSessions] = useState<ActiveSession[]>([])
  const [devices, setDevices] = useState<KnownDevice[]>([])
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

  const reloadStatus = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) return
    try {
      const data = await apiCall<AccountStatus>(
        '/api/v1/user/account/status',
        tokenRef.current,
      )
      setAccountStatus(data)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useAccountSecurity] reloadStatus', e)
    }
  }, [status, accessToken])

  const reloadSessions = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) return
    try {
      const data = await apiCall<{ sessions: ActiveSession[] }>(
        '/api/v1/user/account/sessions',
        tokenRef.current,
      )
      setSessions(data.sessions)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useAccountSecurity] reloadSessions', e)
    }
  }, [status, accessToken])

  const reloadDevices = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) return
    try {
      const data = await apiCall<{ devices: KnownDevice[] }>(
        '/api/v1/user/account/known-devices',
        tokenRef.current,
      )
      setDevices(data.devices)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useAccountSecurity] reloadDevices', e)
    }
  }, [status, accessToken])

  const reloadAll = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setAccountStatus(null)
      setSessions([])
      setDevices([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      await Promise.all([reloadStatus(), reloadSessions(), reloadDevices()])
    } finally {
      setLoading(false)
    }
  }, [status, accessToken, reloadStatus, reloadSessions, reloadDevices])

  useEffect(() => {
    void reloadAll()
  }, [reloadAll])

  const revokeSession = useCallback(
    async (sessionId: string) => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<{ revoked: boolean; session_id: string }>(
          `/api/v1/user/account/sessions/${encodeURIComponent(sessionId)}`,
          token,
          { method: 'DELETE' },
        )
        await reloadSessions()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [reloadSessions],
  )

  const revokeAllOthers = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const token = await waitForToken(tokenRef)
      const data = await apiCall<{ revoked_count: number }>(
        '/api/v1/user/account/sessions/revoke-all',
        token,
        { method: 'POST' },
      )
      await reloadSessions()
      return data.revoked_count
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      throw e
    } finally {
      setSaving(false)
    }
  }, [reloadSessions])

  const forgetDevice = useCallback(
    async (deviceId: string) => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<unknown>(
          `/api/v1/user/account/known-devices/${encodeURIComponent(deviceId)}`,
          token,
          { method: 'DELETE' },
        )
        await reloadDevices()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [reloadDevices],
  )

  const requestDeletion = useCallback(
    async (input: DeletionRequestInput) => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const data = await apiCall<AccountStatus>(
          '/api/v1/user/account/delete',
          token,
          {
            method: 'POST',
            body: JSON.stringify({
              reason: input.reason ?? null,
              confirmation: input.confirmation,
            }),
          },
        )
        setAccountStatus(data)
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('rsends:account-deletion-state-changed', {
              detail: { scheduled_for: data.deletion_scheduled_for },
            }),
          )
        }
        return data
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  const cancelDeletion = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const token = await waitForToken(tokenRef)
      const data = await apiCall<AccountStatus>(
        '/api/v1/user/account/delete/cancel',
        token,
        { method: 'POST' },
      )
      setAccountStatus(data)
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('rsends:account-deletion-state-changed', {
            detail: { scheduled_for: null },
          }),
        )
      }
      return data
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      throw e
    } finally {
      setSaving(false)
    }
  }, [])

  return {
    status: accountStatus,
    sessions,
    devices,
    loading,
    saving,
    error,
    clearError,
    reloadAll,
    reloadStatus,
    reloadSessions,
    reloadDevices,
    revokeSession,
    revokeAllOthers,
    forgetDevice,
    requestDeletion,
    cancelDeletion,
  }
}
