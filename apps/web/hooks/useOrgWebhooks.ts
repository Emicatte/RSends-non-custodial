'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

/**
 * Phase E — session-authed org webhooks (list + health + register + test).
 *
 * Reads/writes the active org's webhooks through the browser/session path
 * (`/api/v1/user/org/webhooks*`) via the `/api/backend` proxy + `apiCall`
 * Bearer/refresh helper. NO wallet-signature auth, NO API key in the browser.
 * Hard-locked to `test` (no `environment` param → backend `test` default).
 * `secret` is returned by `register` ONCE and never re-read by `list`.
 */

export interface OrgWebhook {
  webhook_id: number
  url: string
  events: string[]
  is_active: boolean
  created_at: string
  /**
   * Set when auto-disable switched this endpoint off after three consecutive
   * PERMANENT delivery failures; both null while it has never been disabled.
   *
   * `disabled_reason` is a STABLE CODE, not a sentence — the copy lives in
   * `disabledReasonText` (WebhookCard) so it can be reworded or translated
   * without a data migration. Known codes: `endpoint_not_found_404`,
   * `endpoint_gone_410`, `dns_resolution_failed`, `url_not_allowed:<why>`.
   */
  disabled_reason: string | null
  disabled_at: string | null
}

export interface OrgWebhookDelivery {
  id: number
  event_type: string
  status: string
  response_code: number | null
  retries: number
  next_retry_at: string | null
  created_at: string
  delivered_at: string | null
}

export interface RegisterWebhookResult {
  webhook_id: number
  url: string
  secret: string
  events: string[]
  is_active: boolean
}

export interface TestWebhookResult {
  status: string
  response_code: number | null
  message: string
}

export function useOrgWebhooks() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [webhooks, setWebhooks] = useState<OrgWebhook[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState<number>(0)

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
      setWebhooks([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<{ total: number; records: OrgWebhook[] }>(
        '/api/v1/user/org/webhooks',
        tokenRef.current,
      )
      setWebhooks(data.records)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'unknown')
      setWebhooks([])
      console.error('[useOrgWebhooks] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken, nonce])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    const onOrgChange = () => setNonce((n) => n + 1)
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [])

  const fetchDeliveries = useCallback(
    async (webhookId: number): Promise<OrgWebhookDelivery[]> => {
      const data = await apiCall<{ records: OrgWebhookDelivery[] }>(
        `/api/v1/user/org/webhooks/${webhookId}/deliveries?page=1&per_page=50`,
        tokenRef.current,
      )
      return data.records
    },
    [],
  )

  const register = useCallback(
    async (url: string, events: string[]): Promise<RegisterWebhookResult> => {
      const token = await waitForToken(tokenRef)
      const result = await apiCall<RegisterWebhookResult>(
        '/api/v1/user/org/webhooks',
        token,
        { method: 'POST', body: JSON.stringify({ url, events }) },
      )
      try {
        await reload()
      } catch (e) {
        console.warn('[useOrgWebhooks] reload after register failed', e)
      }
      return result
    },
    [reload],
  )

  const sendTest = useCallback(
    async (webhookId: number): Promise<TestWebhookResult> => {
      const token = await waitForToken(tokenRef)
      return apiCall<TestWebhookResult>(
        `/api/v1/user/org/webhooks/${webhookId}/test`,
        token,
        { method: 'POST' },
      )
    },
    [],
  )

  const reEnable = useCallback(
    async (webhookId: number): Promise<OrgWebhook> => {
      const token = await waitForToken(tokenRef)
      const result = await apiCall<OrgWebhook>(
        `/api/v1/user/org/webhooks/${webhookId}/enable`,
        token,
        { method: 'POST' },
      )
      // Same manual revalidation as `register` — the list must stop showing the
      // disabled banner, and a failed reload must not mask a successful enable.
      try {
        await reload()
      } catch (e) {
        console.warn('[useOrgWebhooks] reload after re-enable failed', e)
      }
      return result
    },
    [reload],
  )

  return {
    webhooks,
    loading,
    error,
    isAuthed: status === 'authenticated',
    reload,
    fetchDeliveries,
    register,
    sendTest,
    reEnable,
  }
}
