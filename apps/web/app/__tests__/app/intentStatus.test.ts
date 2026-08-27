/**
 * The one expiry derivation, shared by the status chip and the row action.
 *
 * It exists because `expired` is written by a 60s Celery task, so the session
 * list ships `pending` for intents that are already dead. Deriving it in two
 * places would let the chip and the action disagree about the same row — a
 * "Pending" label beside a "Repeat" button — which in a UI about money costs
 * more trust than a label a minute stale. These tests pin the derivation itself
 * so that invariant is checkable without rendering a page.
 *
 * Every uncertain case defers to the STORED status: a display-side guess must
 * never overrule what the backend recorded.
 */
import { effectiveStatus } from '@/lib/intentStatus'

const NOW = Date.UTC(2026, 7, 27, 12, 0, 0) // 2026-08-27T12:00:00Z
const PAST = '2026-08-27T11:59:59Z'
const FUTURE = '2026-08-27T12:00:01Z'

it('reports a pending intent past its expiry as expired', () => {
  expect(effectiveStatus({ status: 'pending', expires_at: PAST }, NOW)).toBe('expired')
})

it('leaves a pending intent that has not expired alone', () => {
  expect(effectiveStatus({ status: 'pending', expires_at: FUTURE }, NOW)).toBe('pending')
})

it('treats the exact expiry instant as expired', () => {
  const exact = new Date(NOW).toISOString()
  expect(effectiveStatus({ status: 'pending', expires_at: exact }, NOW)).toBe('expired')
})

it('defers to the stored status before hydration, when there is no clock', () => {
  // The server has no trustworthy clock here; the first client render must
  // match it, so `null` means "do not derive".
  expect(effectiveStatus({ status: 'pending', expires_at: PAST }, null)).toBe('pending')
})

it('defers to the stored status when the intent carries no expiry', () => {
  expect(effectiveStatus({ status: 'pending', expires_at: null }, NOW)).toBe('pending')
})

it('defers to the stored status when the expiry cannot be parsed', () => {
  expect(effectiveStatus({ status: 'pending', expires_at: 'not-a-date' }, NOW)).toBe('pending')
})

it.each([
  'paid',
  'completed',
  'expired',
  'cancelled',
  'review',
  'refunded',
  'partial',
  'overpaid',
])('passes %s through untouched, whatever the expiry says', (status) => {
  // Only `pending` is ever derived — every other status is a settled fact the
  // backend owns, and a past expiry says nothing about it.
  expect(effectiveStatus({ status, expires_at: PAST }, NOW)).toBe(status)
})

it('passes an unknown future status through rather than swallowing it', () => {
  expect(effectiveStatus({ status: 'some_new_status', expires_at: PAST }, NOW)).toBe(
    'some_new_status',
  )
})
