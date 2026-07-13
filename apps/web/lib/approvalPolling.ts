/**
 * Approval waiting-screen polling policy — PURE module (no React, no I/O) so
 * the backoff and the transition decision are unit-testable.
 *
 * The screen polls GET /api/v1/user/onboarding every 15s, backing off to a
 * 60s cap (the operator may take a while; don't hammer the per-IP limit), and
 * transitions on its own the moment approval_status changes.
 */

export const APPROVAL_POLL_BASE_MS = 15_000
export const APPROVAL_POLL_MAX_MS = 60_000

/** Delay before poll number `attempt + 1` (attempt is 0-based): 15s, 30s, 60s cap. */
export function nextPollDelay(attempt: number): number {
  const delay = APPROVAL_POLL_BASE_MS * 2 ** Math.max(0, attempt)
  return Math.min(delay, APPROVAL_POLL_MAX_MS)
}

/** Where the waiting screen must go for a given approval_status (null = keep waiting). */
export function approvalTransition(
  status: string | null | undefined,
): '/app' | '/onboarding/declined' | null {
  if (status === 'approved') return '/app'
  if (status === 'declined') return '/onboarding/declined'
  return null
}
