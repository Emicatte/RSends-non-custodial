'use client'

import { signOut, useSession } from 'next-auth/react'
import { useEffect, useRef } from 'react'
import { exchangeOAuthToken, OAUTH_CONFLICT_EVENT } from '@/lib/oauthExchange'

/**
 * After NextAuth completes an OAuth redirect (Google or GitHub), the
 * session carries a one-shot token. This effect exchanges it with the
 * RPagos backend via the same-origin cookie-aware proxy so the httpOnly
 * refresh + sid cookies land in the browser. The resulting `access_token`
 * is pushed back into the NextAuth JWT via `useSession().update()`.
 *
 *   Google → `id_token` → POST /api/v1/auth/google
 *   GitHub → `github_access_token` → POST /api/v1/auth/github
 *
 * Collision (409 email_already_registered — the email already belongs to an
 * account with another sign-in method): block-and-guide. The NextAuth
 * half-session is discarded (no backend account exists for it) and a
 * `rsends:oauth-conflict` event is dispatched; OAuthConflictListener (inside
 * the locale tree, where the i18n context lives) shows AccountLinkingModal.
 * This component sits OUTSIDE NextIntlClientProvider, hence the event.
 */
export function AuthBootstrap() {
  const { data: session, update } = useSession()
  const exchanging = useRef(false)
  // Per-token dedupe: session.update() is async and the next re-render can
  // fire this effect before access_token has propagated, with id_token still
  // set → without this guard we'd POST /auth/google twice and trip 429.
  const processedTokens = useRef<Set<string>>(new Set())

  useEffect(() => {
    const s = session as {
      id_token?: string
      github_access_token?: string
      access_token?: string
      user?: { email?: string | null }
    } | null
    const idToken = s?.id_token
    const githubAccessToken = s?.github_access_token
    const accessToken = s?.access_token
    if (accessToken || exchanging.current) return
    if (!idToken && !githubAccessToken) return
    const key = idToken ?? githubAccessToken!
    if (processedTokens.current.has(key)) return

    exchanging.current = true
    void (async () => {
      try {
        const endpoint = idToken
          ? '/api/rp-auth/api/v1/auth/google'
          : '/api/rp-auth/api/v1/auth/github'
        const body: Record<string, string> = idToken
          ? { id_token: idToken }
          : { access_token: githubAccessToken! }

        const result = await exchangeOAuthToken(endpoint, body)

        if (result.status === 'conflict') {
          // Don't retry this token, drop the half-session, guide the user.
          processedTokens.current.add(key)
          window.dispatchEvent(
            new CustomEvent(OAUTH_CONFLICT_EVENT, {
              detail: { email: s?.user?.email ?? '' },
            }),
          )
          await signOut({ redirect: false })
          return
        }
        if (result.status !== 'ok') return // transport error: next sign-in retries

        processedTokens.current.add(key)
        await update({ access_token: result.accessToken })
      } finally {
        exchanging.current = false
      }
    })()
  }, [session, update])

  return null
}
