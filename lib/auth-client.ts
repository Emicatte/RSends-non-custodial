'use client'

import type { MutableRefObject } from 'react'
import { signOut } from 'next-auth/react'

/**
 * Authenticated API helper for calls to the RPagos backend.
 *
 * Routing:
 *   • Data calls go through the existing /api/backend proxy (Bearer only).
 *   • 401s trigger ONE refresh through /api/rp-auth (cookie-aware proxy)
 *     and the original request is replayed with the new access_token.
 *   • If refresh fails, signs the user out (client-side) and throws
 *     "session_expired".
 */
export async function apiCall<T>(
  path: string,
  accessToken: string | undefined,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let res = await fetch(`/api/backend${path}`, { ...init, headers })

  if (res.status === 401 && accessToken) {
    const refresh = await fetch('/api/rp-auth/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
    if (refresh.ok) {
      const { access_token } = (await refresh.json()) as { access_token?: string }
      if (access_token) {
        headers.set('Authorization', `Bearer ${access_token}`)
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('rsends:token-refreshed', { detail: { access_token } }),
          )
        }
        res = await fetch(`/api/backend${path}`, { ...init, headers })
      }
    } else {
      await signOut({ redirect: false })
      throw new Error('session_expired')
    }
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ code: 'unknown' }))) as {
      code?: string
      detail?: { code?: string }
    }
    const code = err.code || err.detail?.code || `HTTP ${res.status}`
    // A gated route was hit by an unverified user. Surface it globally so the
    // "verify your email" banner can show even if the session looked verified.
    if (res.status === 403 && code === 'email_not_verified' && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('rsends:email-unverified'))
    }
    throw new Error(code)
  }
  return res.json() as Promise<T>
}

/**
 * Resolve as soon as the shared tokenRef gets a non-empty access_token, or
 * throw 'session_not_ready' after `timeoutMs` if it never lands. Used by
 * mutation callbacks to bridge the 0-2s window post-login where NextAuth says
 * `authenticated` but AuthBootstrap hasn't yet produced the server token.
 */
export async function waitForToken(
  tokenRef: MutableRefObject<string | undefined>,
  timeoutMs = 2000,
  intervalMs = 100,
): Promise<string> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (tokenRef.current) return tokenRef.current
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error('session_not_ready')
}
