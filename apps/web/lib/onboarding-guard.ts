/**
 * Server-side onboarding guard for the authenticated layouts (/app, /settings).
 *
 * FAIL-CLOSED for auth/onboarding states: a session whose onboarding state the
 * backend positively rejected (401/403/other 4xx) or that has no access token
 * yet (the post-OAuth window before AuthBootstrap exchanges the token) is
 * redirected to the /onboarding gate page, which resolves the state
 * client-side via apiCall (one-shot cookie refresh) and routes onward. This
 * is deliberately NOT a NextAuth JWT claim: session.update() lets the client
 * push claim values, so a consent bit in the JWT would be client-forgeable.
 *
 * UNREACHABLE is not a denial: a network error, a timeout, or a 5xx means the
 * backend could not answer (Render free-tier cold start, deploy, slow
 * network). Those resolve 'unreachable' instead of redirecting, so the layout
 * renders a client-side retry gate (BackendUnreachableGate) that waits the
 * cold start out — never a silent bounce away from the dashboard. The fetch
 * carries a short timeout so the RSC render itself never hangs; the long
 * retry budget lives in the client gate.
 *
 * No server-side token refresh here: a server component cannot persist the
 * rotated refresh-token cookies, and rotating them server-side would desync
 * the browser's refresh chain. A 401 therefore resolves 'stale-token' instead
 * of redirecting: the access token in the NextAuth cookie has expired (15-min
 * TTL) but the CLIENT can refresh it, so the layout renders the client gate
 * (same component as 'unreachable'), which refreshes in place and hands back
 * to this guard — the user stays on their URL instead of bouncing through
 * /onboarding on every hard refresh past the token TTL. A dead session still
 * ends at /login: the gate's probe classifies a failed refresh as terminal.
 */

import { redirect } from 'next/navigation'
import type { Session } from 'next-auth'
import { requireEnv } from '@/lib/env'
import {
  ONBOARDING_ENDPOINT,
  resolveOnboardingRedirect,
  type OnboardingState,
} from '@/lib/onboarding'

/** How long the RSC guard waits for the backend before handing the wait over
 * to the client-side retry gate (which owns the long cold-start budget). */
const GUARD_TIMEOUT_MS = 8_000

export type OnboardingGuardResult = 'ok' | 'unreachable' | 'stale-token'

export async function enforceOnboarding(
  session: Session,
  locale: string,
): Promise<OnboardingGuardResult> {
  const gate = `/${locale}/onboarding`
  const accessToken = (session as { access_token?: string }).access_token
  if (!accessToken) {
    redirect(gate)
  }

  let state: OnboardingState
  try {
    const res = await fetch(
      `${requireEnv('RPAGOS_BACKEND_URL')}${ONBOARDING_ENDPOINT}`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: 'no-store',
        signal: AbortSignal.timeout(GUARD_TIMEOUT_MS),
      },
    )
    if (res.status >= 500) {
      return 'unreachable'
    }
    if (res.status === 401) {
      // Expired access token — refreshable, but only by the client.
      return 'stale-token'
    }
    if (!res.ok) {
      redirect(gate)
    }
    state = (await res.json()) as OnboardingState
  } catch (e) {
    // next/navigation redirect() throws internally — let it propagate.
    if (e && typeof e === 'object' && 'digest' in e) throw e
    // Anything else (TypeError network failure, TimeoutError/AbortError from
    // the signal, malformed JSON) is the absence of an answer, not a denial.
    return 'unreachable'
  }

  const target = resolveOnboardingRedirect(state!, locale)
  if (target) {
    redirect(target)
  }
  return 'ok'
}
