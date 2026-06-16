'use client'

/**
 * useMerchantProfile — anagrafica di fatturazione del merchant (Settings → Fatturazione).
 *
 * GET  /api/v1/merchant/profile  → precompila il form (exists=false ⇒ campi vuoti).
 * PUT  /api/v1/merchant/profile  → upsert dei campi billing_*.
 *
 * Il profilo è ancorato al wallet PRIMARIO EVM dell'org attiva (lato backend).
 * Se l'org non ha wallet primario, il backend risponde 409 {"code":"no_primary_wallet"}:
 * lo intercettiamo qui e lo esponiamo come `noPrimaryWallet` per mostrare la CTA wallet.
 *
 * Usa lo stesso pattern auth delle altre pagine settings: apiCall (Bearer JWT) +
 * tokenRef + waitForToken. NON usare mutationHeaders (è per la wallet-auth del Command Center).
 */

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'

export interface MerchantProfileData {
  owner_address: string
  exists: boolean
  billing_legal_name: string | null
  billing_vat_number: string | null
  billing_tax_code: string | null
  billing_address_line: string | null
  billing_city: string | null
  billing_postal_code: string | null
  billing_country: string | null
  billing_email: string | null
  billing_pec: string | null
  created_at: string | null
  updated_at: string | null
}

export interface MerchantProfileInput {
  billing_legal_name: string
  billing_vat_number: string
  billing_tax_code: string
  billing_address_line: string
  billing_city: string
  billing_postal_code: string
  billing_country: string
  billing_email: string
  billing_pec: string
}

const PROFILE_PATH = '/api/v1/merchant/profile'

export function useMerchantProfile() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const { activeOrg, role: currentUserRole } = useCurrentOrg()

  const [profile, setProfile] = useState<MerchantProfileData | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [noPrimaryWallet, setNoPrimaryWallet] = useState<boolean>(false)

  // Sync token from session to ref
  useEffect(() => {
    tokenRef.current = (session as { access_token?: string } | null)?.access_token
  }, [session])

  // Listen for token refresh events (same as useUserApiKeys)
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
      setProfile(null)
      return
    }
    setLoading(true)
    setError(null)
    setNoPrimaryWallet(false)
    try {
      const token = await waitForToken(tokenRef)
      const data = await apiCall<MerchantProfileData>(PROFILE_PATH, token)
      setProfile(data)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      if (code === 'no_primary_wallet') {
        setNoPrimaryWallet(true)
      } else {
        setError(code)
      }
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const save = useCallback(
    async (input: MerchantProfileInput): Promise<boolean> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const data = await apiCall<MerchantProfileData>(PROFILE_PATH, token, {
          method: 'PUT',
          body: JSON.stringify(input),
        })
        setProfile(data)
        return true
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        if (code === 'no_primary_wallet') {
          setNoPrimaryWallet(true)
        }
        setError(code)
        return false
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  return {
    profile,
    loading,
    saving,
    error,
    noPrimaryWallet,
    isAuthed: status === 'authenticated',
    activeOrg,
    currentUserRole,
    reload,
    save,
    clearError: () => setError(null),
  }
}
