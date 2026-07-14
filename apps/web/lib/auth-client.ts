'use client'

import type { MutableRefObject } from 'react'
import { performLogout } from '@/lib/logoutClient'

/**
 * Authenticated API helper for calls to the RPagos backend.
 *
 * Routing:
 *   • Data calls go through the existing /api/backend proxy (Bearer only).
 *   • 401s trigger ONE refresh through /api/rp-auth (cookie-aware proxy)
 *     and the original request is replayed with the new access_token.
 *   • Refresh outcomes are CLASSIFIED: a 401/403 from the refresh endpoint
 *     means the server session is dead (revoked/rotated away) → sign out and
 *     throw "session_expired". Network errors and 5xx are TRANSIENT (backend
 *     deploy, blip) → throw "refresh_unavailable" WITHOUT logging out, so a
 *     polling caller can simply retry later. Treating a transient failure as
 *     terminal is what killed live sessions during backend redeploys.
 *   • The refresh is SINGLE-FLIGHT: concurrent 401s share one refresh call.
 *     Two racing refreshes present the same rotated-away cookie and trip the
 *     backend's reuse detection, which revokes the whole session.
 */

let refreshInFlight: Promise<string> | null = null

async function doRefresh(): Promise<string> {
  let res: Response
  try {
    res = await fetch('/api/rp-auth/api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    })
  } catch {
    throw new Error('refresh_unavailable')
  }
  if (res.ok) {
    const { access_token } = (await res
      .json()
      .catch(() => ({}))) as { access_token?: string }
    if (access_token) {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('rsends:token-refreshed', { detail: { access_token } }),
        )
      }
      return access_token
    }
    // 200 without a token is a malformed response, not a dead session.
    throw new Error('refresh_unavailable')
  }
  if (res.status === 401 || res.status === 403) {
    // The server session is already dead — skipBackend: requiring a logout
    // call here would deadlock.
    await performLogout({ skipBackend: true })
    throw new Error('session_expired')
  }
  // 5xx / 429 / anything else: the auth service is unavailable, the session
  // may well still be valid — do NOT log out.
  throw new Error('refresh_unavailable')
}

function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null
    })
  }
  return refreshInFlight
}

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
    // Throws session_expired (terminal, signed out) or refresh_unavailable
    // (transient, session intact — caller retries).
    const access_token = await refreshAccessToken()
    headers.set('Authorization', `Bearer ${access_token}`)
    res = await fetch(`/api/backend${path}`, { ...init, headers })
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({ code: 'unknown' }))) as {
      code?: string
      detail?: { code?: string }
    }
    const code = err.code || err.detail?.code || `HTTP ${res.status}`
    // (The email_not_verified → banner event went away with the email wall,
    // 2026-07-13; approval_pending/approval_declined are handled by routing.)
    // Carry the HTTP status on the error so callers can classify by status
    // (reachable-but-denied vs unreachable) instead of matching the body code
    // string, which varies per route. Message stays the code (unchanged).
    const error = new Error(code) as Error & { status?: number }
    error.status = res.status
    throw error
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
