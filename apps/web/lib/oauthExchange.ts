'use client'

/**
 * OAuth token exchange with the backend (Google id_token / GitHub
 * access_token → RSends session + access token).
 *
 * Three-way outcome so the caller can't accidentally swallow the
 * block-and-guide collision (account-linking audit, layer 3):
 *   'ok'       — session created, access token returned;
 *   'conflict' — 409 email_already_registered: the email already belongs to
 *                an account with another sign-in method. The caller surfaces
 *                the AccountLinkingModal; NO auto-linking.
 *   'error'    — transport/other failure; safe to retry on next sign-in.
 */

export const OAUTH_CONFLICT_EVENT = 'rsends:oauth-conflict'

export type OAuthExchangeResult =
  | { status: 'ok'; accessToken: string }
  | { status: 'conflict' }
  | { status: 'error' }

export async function exchangeOAuthToken(
  endpoint: string,
  body: Record<string, string>,
): Promise<OAuthExchangeResult> {
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'include',
    })
    if (res.status === 409) return { status: 'conflict' }
    if (!res.ok) return { status: 'error' }
    const data = (await res.json()) as { access_token?: string }
    if (!data.access_token) return { status: 'error' }
    return { status: 'ok', accessToken: data.access_token }
  } catch {
    return { status: 'error' }
  }
}
