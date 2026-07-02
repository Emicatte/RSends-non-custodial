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

/**
 * User-PII localStorage keys wiped on sign-out (audit finding #8): on a
 * shared device a logged-out user's address book / fiscal records must not
 * stay readable. None of these are per-user-namespaced, so clearing them
 * consciously trades away cross-logout offline-first persistence (incl. the
 * pendingMerge retry-after-relogin convenience). Non-PII caches (rs_cg_*
 * prices) and the merchant-dashboard sessionStorage stay untouched.
 */
const USER_PII_STORAGE_KEYS = [
  'rp_address_book', // offline address book (contacts)
  'rsends.pendingMerge', // transactions queued for post-login merge
  'rsend_antiphishing_code', // user's anti-phishing hint
  'rp_pending_queue', // compliance queue (tx metadata)
  'rp_compliance_db', // fiscal records (addresses, amounts, rates)
] as const

function clearUserPiiStorage(): void {
  if (typeof window === 'undefined') return
  for (const key of USER_PII_STORAGE_KEYS) {
    try {
      window.localStorage.removeItem(key)
      window.sessionStorage.removeItem(key)
    } catch {
      // storage unavailable (private mode/quota) — nothing to clear
    }
  }
}

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
    // Still signed in server-side: keep client state AND local PII intact.
    return { ok: false }
  }

  clearUserPiiStorage()
  await signOut(callbackUrl ? { callbackUrl } : { redirect: false })
  return { ok: true }
}
