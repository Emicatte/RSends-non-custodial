'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export interface NotificationPreferences {
  email_login_new_device: boolean
  telegram_tx_confirmed: boolean
  telegram_tx_failed: boolean
  telegram_price_alerts: boolean
  telegram_chat_id: string | null
  updated_at: string
}

type BoolKey =
  | 'email_login_new_device'
  | 'telegram_tx_confirmed'
  | 'telegram_tx_failed'
  | 'telegram_price_alerts'

export function useNotificationPreferences() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const [preferences, setPreferences] =
    useState<NotificationPreferences | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

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
      setPreferences(null)
      return
    }
    setLoading(true)
    try {
      const data = await apiCall<NotificationPreferences>(
        '/api/v1/user/notifications/preferences',
        tokenRef.current,
      )
      setPreferences(data)
    } catch (e) {
      console.error('[useNotificationPreferences] load', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const toggle = useCallback(
    async (key: BoolKey, value: boolean) => {
      if (status !== 'authenticated' || !preferences) return
      setSaving(true)
      const prev = preferences
      setPreferences({ ...preferences, [key]: value })
      try {
        const token = await waitForToken(tokenRef)
        const updated = await apiCall<NotificationPreferences>(
          '/api/v1/user/notifications/preferences',
          token,
          { method: 'PATCH', body: JSON.stringify({ [key]: value }) },
        )
        setPreferences(updated)
      } catch (e) {
        console.error('[useNotificationPreferences] toggle', e)
        setPreferences(prev)
      } finally {
        setSaving(false)
      }
    },
    [status, preferences],
  )

  return {
    preferences,
    loading,
    saving,
    isAuthed: status === 'authenticated',
    reload,
    toggle,
  }
}
