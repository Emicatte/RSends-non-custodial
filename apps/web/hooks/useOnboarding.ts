'use client'

/**
 * Client hook for the aggregate onboarding state (GET /api/v1/user/onboarding).
 * Mirrors the useOrgStats token plumbing (session access_token +
 * rsends:token-refreshed) without polling — the gate page and wizard steps
 * read once and call reload() after mutations.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { waitForToken } from '@/lib/auth-client'
import { getOnboardingState } from '@/lib/onboarding-client'
import type { OnboardingState } from '@/lib/onboarding'

export function useOnboarding() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [state, setState] = useState<OnboardingState | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<boolean>(false)

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
    if (status !== 'authenticated') {
      setState(null)
      setError(false)
      setLoading(status === 'loading')
      return
    }
    let token = tokenRef.current
    if (!token) {
      // NextAuth reports 'authenticated' a beat before the access token lands
      // in the session. Wait briefly; on timeout resolve to the error state —
      // the old no-state/no-error limbo left the gate page loading forever.
      try {
        token = await waitForToken(tokenRef)
      } catch {
        setState(null)
        setError(true)
        setLoading(false)
        return
      }
    }
    try {
      const data = await getOnboardingState(token)
      setState(data)
      setError(false)
    } catch (e) {
      setError(true)
      setState(null)
      console.error('[useOnboarding] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  return {
    state,
    loading,
    error,
    isAuthed: status === 'authenticated',
    accessToken,
    tokenRef,
    reload,
  }
}
