'use client'

import { useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { initAuthChannel } from '@/lib/auth-client'

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
 *
 * Also opens the cross-tab auth channel from page load, so a token refreshed
 * in another tab lands here (as the same event) before this tab ever 401s.
 */
export function TokenRefreshBridge() {
  const { update } = useSession()

  useEffect(() => {
    initAuthChannel()
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
