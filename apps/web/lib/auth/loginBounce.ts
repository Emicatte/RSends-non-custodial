/**
 * The vocabulary of a server-side bounce to /login.
 *
 * Four doors send an unauthenticated visitor to the login page: `middleware.ts`
 * and the `/app`, `/onboarding` and `/settings` layouts. Until now they said
 * nothing — the user landed on a pristine form with no reason given, which is
 * how the 2026-08-26 incident presented. They all speak through this module so
 * the vocabulary cannot drift apart again.
 *
 * Import-safe from the edge runtime and from RSC: nothing here runs at module
 * load, and the two storage helpers touch `window` only when called, which only
 * ever happens in the browser.
 */

/** Not signed in. True of every one of the four doors, whatever the cause. */
export const SIGN_IN_REQUIRED = 'sign_in_required'

/** A session that existed and died. Set by the client-side bounces (PR #74). */
export const SESSION_EXPIRED = 'session_expired'

/**
 * Codes accepted FROM the `?error=` query parameter.
 *
 * This is a whitelist and must stay one: the value feeds a translation key, so
 * an arbitrary string from the URL must never reach the message lookup.
 */
export const BOUNCE_CODES: readonly string[] = [SIGN_IN_REQUIRED, SESSION_EXPIRED]

/**
 * Sign-in succeeded but the browser did not keep the session.
 *
 * Derived client-side ONLY, never accepted from the URL — a crafted link must
 * not be able to tell a user their browser is broken when it is not.
 */
export const SESSION_NOT_PERSISTED = 'session_not_persisted'

export const SIGNIN_MARKER_KEY = 'rsends:signed-in-at'

/**
 * How recently a sign-in must have completed for a `sign_in_required` bounce to
 * be read as "the session did not stick" rather than "you are simply logged
 * out". Long enough to cover the push + server round-trip, short enough that an
 * unrelated bounce minutes later is not mislabelled.
 */
export const SIGNIN_MARKER_TTL_MS = 15_000

/** Where a server-side door sends someone, and why. */
export function loginBounceUrl(locale: string, redirectTo?: string): string {
  const params = new URLSearchParams({ error: SIGN_IN_REQUIRED })
  if (redirectTo) params.set('redirect', redirectTo)
  return `/${locale}/login?${params.toString()}`
}

/** Record that a sign-in just completed. Storage refusal is not an error. */
export function markSignedIn(): void {
  try {
    window.sessionStorage.setItem(SIGNIN_MARKER_KEY, String(Date.now()))
  } catch {
    // Locked-down browser. The bounce will simply read as a generic logout,
    // which is the weaker message but never a false one.
  }
}

/**
 * Read AND clear the marker. True only when a sign-in completed within the TTL.
 *
 * Always clears, so a stale marker cannot upgrade an unrelated bounce later in
 * the same tab.
 */
export function consumeFreshSignInMarker(): boolean {
  try {
    const raw = window.sessionStorage.getItem(SIGNIN_MARKER_KEY)
    window.sessionStorage.removeItem(SIGNIN_MARKER_KEY)
    if (!raw) return false
    const at = Number(raw)
    return Number.isFinite(at) && Date.now() - at < SIGNIN_MARKER_TTL_MS
  } catch {
    return false
  }
}
