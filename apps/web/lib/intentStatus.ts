// The ONE expiry derivation for a payment intent, shared by every consumer.
//
// `expired` is written by a Celery beat task that runs every 60s, and the
// session list serializes `i.status.value` raw — so a past-expiry intent still
// arrives from the API reading `pending`. `expires_at` is on the wire precisely
// so the client can close that window; the public /pay route already does the
// same thing in `_effective_status` (app/api/public_routes.py).
//
// This lives in one function on purpose. The status chip and the row action ask
// the same question and must never answer it differently: a "Pending" label
// beside a "Repeat" button is worse than a label a minute stale, because in a
// UI about money an internal contradiction costs more trust than imprecision.
//
// TEMPORARY. The durable fix is deriving this in the backend serializer, so the
// list, the status filter, the chip and the action all agree and the Celery task
// goes back to owning only side effects. Delete this module when issue #80 lands.
// Until then the FILTER half stays wrong: the status dropdown queries the stored
// column server-side, so it disagrees with the chip this function produces.

import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'

/**
 * The status this intent effectively has right now.
 *
 * Only `pending` is ever derived — every other status is a settled fact the
 * backend owns, and a past expiry says nothing about it. Every uncertain case
 * (no clock yet, no expiry, unparseable expiry) defers to the STORED status: a
 * display-side guess must never overrule what the backend recorded.
 *
 * @param nowMs epoch ms, or `null` for "before hydration" — the server has no
 *   trustworthy clock here, so the first client render must match it and defer.
 */
export function effectiveStatus(
  row: Pick<OrgPaymentRecord, 'status' | 'expires_at'>,
  nowMs: number | null,
): string {
  if (row.status !== 'pending') return row.status
  if (nowMs === null || !row.expires_at) return row.status
  const expiresAt = new Date(row.expires_at).getTime()
  if (!Number.isFinite(expiresAt)) return row.status
  return expiresAt <= nowMs ? 'expired' : row.status
}
