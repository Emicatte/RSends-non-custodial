'use client'

import { useEffect } from 'react'
import { useSession } from 'next-auth/react'

/**
 * Persists reactively-refreshed backend access tokens into the NextAuth JWT.
 *
 * apiCall's 401-refresh dispatches `rsends:token-refreshed` — that keeps the
 * in-memory tokenRefs current, but the NextAuth session cookie kept the
 * LOGIN-TIME token forever, so every server-side guard reading
 * `session.access_token` (enforceOnboarding on /app) worked with a token that
 * was permanently expired after 15 minutes and bounced users to /onboarding.
 * The jwt callback already accepts `trigger === 'update'` (auth-options.ts);
 * this bridge is the missing caller.
 */
export function TokenRefreshBridge() {
  const { update } = useSession()

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const access_token = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (access_token) void update({ access_token })
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [update])

  return null
}
