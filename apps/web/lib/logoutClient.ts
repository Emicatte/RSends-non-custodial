'use client'

import { signOut } from 'next-auth/react'

/**
 * Blocking logout (audit finding #7).
 *
 * The backend logout is what actually revokes the Redis session and expires
 * the HttpOnly rsends_refresh/rsends_sid cookies (JS cannot clear them). So:
 * AWAIT it (with a bounded retry) and GATE the client-side signOut on its
 * success. On persistent failure return ok:false WITHOUT signing out — the
 * caller keeps the session visible and surfaces the error, instead of a
 * silent half-logout that leaves a live server session on a shared device.
 *
 * `skipBackend` is for the expired-session path (a failed token refresh):
 * the server session is already dead there, and requiring a successful
 * logout call would deadlock the sign-out.
 */

const LOGOUT_ENDPOINT = '/api/rp-auth/api/v1/auth/logout'
const LOGOUT_ATTEMPTS = 2
const LOGOUT_TIMEOUT_MS = 4000

export interface LogoutResult {
  ok: boolean
}

async function revokeBackendSession(): Promise<boolean> {
  for (let attempt = 0; attempt < LOGOUT_ATTEMPTS; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), LOGOUT_TIMEOUT_MS)
    try {
      const res = await fetch(LOGOUT_ENDPOINT, {
        method: 'POST',
        credentials: 'include',
        signal: controller.signal,
      })
      if (res.ok) return true
    } catch {
      // network error / timeout — fall through to the retry
    } finally {
      clearTimeout(timer)
    }
  }
  return false
}

export async function performLogout(
  opts: { skipBackend?: boolean; callbackUrl?: string } = {},
): Promise<LogoutResult> {
  const { skipBackend = false, callbackUrl } = opts

  if (!skipBackend && !(await revokeBackendSession())) {
    return { ok: false }
  }

  await signOut(callbackUrl ? { callbackUrl } : { redirect: false })
  return { ok: true }
}
