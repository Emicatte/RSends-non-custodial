/**
 * Server-side onboarding guard for the authenticated layouts (/app, /settings).
 *
 * FAIL-CLOSED by design: a session whose onboarding state cannot be positively
 * confirmed (missing access token — e.g. the post-OAuth window before
 * AuthBootstrap exchanges the token — backend 4xx/5xx, network error) is
 * redirected to the /onboarding gate page, which resolves the state
 * client-side via apiCall (one-shot cookie refresh) and routes onward. This
 * is deliberately NOT a NextAuth JWT claim: session.update() lets the client
 * push claim values, so a consent bit in the JWT would be client-forgeable.
 *
 * No server-side token refresh here: a server component cannot persist the
 * rotated refresh-token cookies, and rotating them server-side would desync
 * the browser's refresh chain. An expired access token costs one bounce
 * through the gate page.
 */

import { redirect } from 'next/navigation'
import type { Session } from 'next-auth'
import { requireEnv } from '@/lib/env'
import { resolveOnboardingRedirect, type OnboardingState } from '@/lib/onboarding'

export async function enforceOnboarding(
  session: Session,
  locale: string,
): Promise<void> {
  const gate = `/${locale}/onboarding`
  const accessToken = (session as { access_token?: string }).access_token
  if (!accessToken) {
    redirect(gate)
  }

  let state: OnboardingState
  try {
    const res = await fetch(
      `${requireEnv('RPAGOS_BACKEND_URL')}/api/v1/user/onboarding`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: 'no-store',
      },
    )
    if (!res.ok) {
      redirect(gate)
    }
    state = (await res.json()) as OnboardingState
  } catch (e) {
    // next/navigation redirect() throws internally — let it propagate.
    if (e && typeof e === 'object' && 'digest' in e) throw e
    redirect(gate)
  }

  const target = resolveOnboardingRedirect(state!, locale)
  if (target) {
    redirect(target)
  }
}
