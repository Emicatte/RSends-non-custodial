'use client'

import { useSession } from 'next-auth/react'
import { useEffect, useRef } from 'react'

/**
 * After NextAuth completes an OAuth redirect (Google or GitHub), the
 * session carries a one-shot token. This effect exchanges it with the
 * RPagos backend via the same-origin cookie-aware proxy so the httpOnly
 * refresh + sid cookies land in the browser. The resulting `access_token`
 * is pushed back into the NextAuth JWT via `useSession().update()`.
 *
 *   Google → `id_token` → POST /api/v1/auth/google
 *   GitHub → `github_access_token` → POST /api/v1/auth/github
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
        const body = idToken
          ? { id_token: idToken }
          : { access_token: githubAccessToken }
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          credentials: 'include',
        })
        if (!res.ok) return
        const data = (await res.json()) as { access_token?: string }
        if (!data.access_token) return
        processedTokens.current.add(key)
        await update({ access_token: data.access_token })
      } catch {
        /* swallow: the next sign-in attempt will retry */
      } finally {
        exchanging.current = false
      }
    })()
  }, [session, update])

  return null
}
