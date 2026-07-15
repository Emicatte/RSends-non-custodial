'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'

/**
 * Session-minted rsend_ merchant API keys (Option B, 2026-07-15).
 *
 * Mirrors useUserApiKeys against /api/v1/user/org/merchant-keys. These are the
 * REAL merchant payment-API keys (same table and verify path as the
 * wallet-signed mints), pinned to environment=test / scope=write server-side.
 *
 * Expected error codes surfaced via `error`:
 *   no_primary_wallet          — org has neither a linked wallet nor a
 *                                settlement wallet: mint/list gated until the
 *                                settlement wallet is set in Settings.
 *   settlement_wallet_conflict — contested identity, loud by design.
 *   max_keys_reached           — 5 active test keys per owner.
 */

export interface MerchantKeyItem {
  id: number
  prefix: string
  label: string
  scope: string
  environment: string
  is_active: boolean
  session_minted: boolean
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

export interface MerchantKeyListPayload {
  keys: MerchantKeyItem[]
  max_allowed: number
  remaining_slots: number
  owner_address: string
}

export interface MerchantKeyCreateResult {
  id: number
  key: string // plaintext — shown once, never retrievable again
  prefix: string
  label: string
  scope: string
  environment: string
  created_at: string
}

const BASE = '/api/v1/user/org/merchant-keys'

export function useMerchantApiKeys() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const { activeOrg, role: currentUserRole } = useCurrentOrg()

  const [keys, setKeys] = useState<MerchantKeyItem[]>([])
  const [maxAllowed, setMaxAllowed] = useState<number>(5)
  const [remainingSlots, setRemainingSlots] = useState<number>(5)
  const [ownerAddress, setOwnerAddress] = useState<string | null>(null)
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
      const data = await apiCall<MerchantKeyListPayload>(BASE, tokenRef.current)
      setKeys(data.keys)
      setMaxAllowed(data.max_allowed)
      setRemainingSlots(data.remaining_slots)
      setOwnerAddress(data.owner_address)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      // no_primary_wallet is the expected fresh-merchant state, not a fault.
      if (code !== 'no_primary_wallet') {
        console.error('[useMerchantApiKeys] reload', e)
      }
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    const onOrgChange = () => {
      void reload()
    }
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [reload])

  const createKey = useCallback(
    async (label: string): Promise<MerchantKeyCreateResult> => {
      setSaving(true)
      try {
        const token = await waitForToken(tokenRef)
        const result = await apiCall<MerchantKeyCreateResult>(BASE, token, {
          method: 'POST',
          body: JSON.stringify({ label }),
        })
        // Mutation succeeded. Reload is best-effort — a transient failure
        // here must not surface as a mutation error.
        try {
          await reload()
        } catch (reloadErr) {
          console.warn('[useMerchantApiKeys] reload after create failed:', reloadErr)
        }
        return result
      } finally {
        setSaving(false)
      }
    },
    [reload],
  )

  const revokeKey = useCallback(
    async (id: number): Promise<void> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<MerchantKeyItem>(`${BASE}/${id}/revoke`, token, {
          method: 'POST',
        })
        try {
          await reload()
        } catch (reloadErr) {
          console.warn('[useMerchantApiKeys] reload after revoke failed:', reloadErr)
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
    ownerAddress,
    loading,
    saving,
    error,
    isAuthed: status === 'authenticated',
    activeOrg,
    currentUserRole,
    reload,
    createKey,
    revokeKey,
  }
}
