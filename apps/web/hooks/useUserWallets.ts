'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'

export interface UserWallet {
  id: string
  chain_family: string
  address: string
  display_address: string
  chain_id: number | null
  verified_chain_id: number
  label: string
  is_primary: boolean
  verified_at: string
  last_activity_at: string | null
  created_at: string
  extra_metadata: Record<string, unknown>
  // Prompt 11: team audit trail. Null when the creator's user record has been
  // deleted (FK is ON DELETE SET NULL).
  created_by_user_id?: string | null
  created_by_email?: string | null
}

export interface WalletListPayload {
  wallets: UserWallet[]
  max_allowed: number
  remaining_slots: number
}

export interface WalletChallenge {
  siwe_message: string
  nonce: string
  expires_at: string
}

export interface VerifyAndLinkInput {
  address: string
  chainId: number
  nonce: string
  signature: string
  label?: string
}

export function useUserWallets() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)
  const { activeOrg, role: currentUserRole } = useCurrentOrg()

  const [wallets, setWallets] = useState<UserWallet[]>([])
  const [maxAllowed, setMaxAllowed] = useState<number>(10)
  const [remainingSlots, setRemainingSlots] = useState<number>(10)
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
      setWallets([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<WalletListPayload>(
        '/api/v1/user/wallets',
        tokenRef.current,
      )
      setWallets(data.wallets)
      setMaxAllowed(data.max_allowed)
      setRemainingSlots(data.remaining_slots)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useUserWallets] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  // Prompt 11: when the user switches active org, wallets are a different set
  // (scoped by org) so we must reload.
  useEffect(() => {
    const onOrgChange = () => {
      void reload()
    }
    window.addEventListener('rsends:active-org-changed', onOrgChange)
    return () =>
      window.removeEventListener('rsends:active-org-changed', onOrgChange)
  }, [reload])

  const requestChallenge = useCallback(
    async (address: string, chainId: number): Promise<WalletChallenge> => {
      setError(null)
      const token = await waitForToken(tokenRef)
      return apiCall<WalletChallenge>(
        '/api/v1/user/wallets/challenge',
        token,
        {
          method: 'POST',
          body: JSON.stringify({
            chain_family: 'evm',
            address,
            chain_id: chainId,
          }),
        },
      )
    },
    [],
  )

  const verifyAndLink = useCallback(
    async (input: VerifyAndLinkInput): Promise<UserWallet> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const wallet = await apiCall<UserWallet>(
          '/api/v1/user/wallets/verify',
          token,
          {
            method: 'POST',
            body: JSON.stringify({
              chain_family: 'evm',
              address: input.address,
              chain_id: input.chainId,
              nonce: input.nonce,
              signature: input.signature,
              label: input.label,
            }),
          },
        )
        await reload()
        return wallet
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

  const setPrimary = useCallback(
    async (id: string): Promise<void> => {
      setSaving(true)
      setError(null)
      const prev = wallets
      setWallets((cur) =>
        cur.map((w) => ({ ...w, is_primary: w.id === id })),
      )
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<UserWallet>(
          `/api/v1/user/wallets/${id}`,
          token,
          {
            method: 'PATCH',
            body: JSON.stringify({ is_primary: true }),
          },
        )
        await reload()
      } catch (e) {
        setWallets(prev)
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [wallets, reload],
  )

  const updateLabel = useCallback(
    async (id: string, label: string): Promise<void> => {
      setSaving(true)
      setError(null)
      const prev = wallets
      setWallets((cur) =>
        cur.map((w) => (w.id === id ? { ...w, label } : w)),
      )
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<UserWallet>(
          `/api/v1/user/wallets/${id}`,
          token,
          {
            method: 'PATCH',
            body: JSON.stringify({ label }),
          },
        )
        await reload()
      } catch (e) {
        setWallets(prev)
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [wallets, reload],
  )

  const unlink = useCallback(
    async (id: string): Promise<void> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<void>(`/api/v1/user/wallets/${id}`, token, {
          method: 'DELETE',
        })
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

  return {
    wallets,
    maxAllowed,
    remainingSlots,
    loading,
    saving,
    error,
    isAuthed: status === 'authenticated',
    activeOrg,
    currentUserRole,
    reload,
    requestChallenge,
    verifyAndLink,
    setPrimary,
    updateLabel,
    unlink,
    clearError: () => setError(null),
  }
}
