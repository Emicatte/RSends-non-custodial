'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'

export interface ApiKeyListItem {
  id: string
  label: string
  scopes: string[]
  display_prefix: string
  environment: string
  rate_limit_rpm: number
  is_active: boolean
  revoked_at: string | null
  created_at: string
  last_used_at: string | null
  last_used_ip: string | null
  total_requests: number
  // Prompt 11: team audit trail. Null when the creator's user record has been
  // deleted (FK is ON DELETE SET NULL).
  created_by_user_id?: string | null
  created_by_email?: string | null
}

export interface ApiKeyListPayload {
  keys: ApiKeyListItem[]
  max_allowed: number
  remaining_slots: number
}

export interface ApiKeyCreateResult {
  id: string
  label: string
  scopes: string[]
  plaintext_key: string
  display_prefix: string
  created_at: string
}

export interface CreateApiKeyInput {
  label: string
  scopes: string[]
}

export function useUserApiKeys() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const { activeOrg, role: currentUserRole } = useCurrentOrg()

  const [keys, setKeys] = useState<ApiKeyListItem[]>([])
  const [maxAllowed, setMaxAllowed] = useState<number>(5)
  const [remainingSlots, setRemainingSlots] = useState<number>(5)
  const [availableScopes, setAvailableScopes] = useState<string[]>([])
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

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) {
      setKeys([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<ApiKeyListPayload>(
        '/api/v1/user/api-keys',
        tokenRef.current,
      )
      setKeys(data.keys)
      setMaxAllowed(data.max_allowed)
      setRemainingSlots(data.remaining_slots)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useUserApiKeys] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  // Prompt 11: when the user switches active org, api-keys are a different
  // set (scoped by org) so we must reload.
  useEffect(() => {
    const onOrgChange = () => {
      void reload()
    }
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [reload])

  const loadAvailableScopes = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken) return
    try {
      const data = await apiCall<{ scopes: string[] }>(
        '/api/v1/user/api-keys/available-scopes',
        tokenRef.current,
      )
      setAvailableScopes(data.scopes)
    } catch (e) {
      console.error('[useUserApiKeys] loadAvailableScopes', e)
    }
  }, [status, accessToken])

  const createKey = useCallback(
    async (input: CreateApiKeyInput): Promise<ApiKeyCreateResult> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const result = await apiCall<ApiKeyCreateResult>(
          '/api/v1/user/api-keys',
          token,
          {
            method: 'POST',
            body: JSON.stringify({
              label: input.label,
              scopes: input.scopes,
            }),
          },
        )
        // Mutation succeeded. Reload is best-effort — a transient failure
        // here must not surface as a mutation error and must not cascade
        // into apiCall's 401-triggered signout path.
        try {
          await reload()
        } catch (reloadErr) {
          console.warn(
            '[useUserApiKeys] reload after createKey failed:',
            reloadErr,
          )
        }
        return result
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

  const updateLabel = useCallback(
    async (id: string, label: string): Promise<void> => {
      setSaving(true)
      setError(null)
      const prev = keys
      setKeys((cur) =>
        cur.map((k) => (k.id === id ? { ...k, label } : k)),
      )
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<ApiKeyListItem>(
          `/api/v1/user/api-keys/${id}`,
          token,
          {
            method: 'PATCH',
            body: JSON.stringify({ label }),
          },
        )
        // Mutation succeeded. Reload is best-effort — a transient failure
        // here must not surface as a mutation error and must not cascade
        // into apiCall's 401-triggered signout path.
        try {
          await reload()
        } catch (reloadErr) {
          console.warn(
            '[useUserApiKeys] reload after updateLabel failed:',
            reloadErr,
          )
        }
      } catch (e) {
        setKeys(prev)
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [keys, reload],
  )

  const revokeKey = useCallback(
    async (id: string): Promise<void> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<void>(`/api/v1/user/api-keys/${id}`, token, {
          method: 'DELETE',
        })
        // Mutation succeeded. Reload is best-effort — a transient failure
        // here must not surface as a mutation error and must not cascade
        // into apiCall's 401-triggered signout path.
        try {
          await reload()
        } catch (reloadErr) {
          console.warn(
            '[useUserApiKeys] reload after revokeKey failed:',
            reloadErr,
          )
        }
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

  return {
    keys,
    maxAllowed,
    remainingSlots,
    availableScopes,
    loading,
    saving,
    error,
    isAuthed: status === 'authenticated',
    activeOrg,
    currentUserRole,
    reload,
    loadAvailableScopes,
    createKey,
    updateLabel,
    revokeKey,
    clearError: () => setError(null),
  }
}
