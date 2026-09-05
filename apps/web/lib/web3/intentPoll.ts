/**
 * lib/web3/intentPoll — the hosted checkout's polling schedule, all timing
 * numbers in one place. Three phases:
 *
 * - initial: the first fetch of the intent; retries with backoff, raising a
 *   "taking longer than usual" notice after SLOW_NOTICE_AFTER and giving up
 *   after INITIAL_RETRY_GIVE_UP_AFTER into an explicit "unreachable" phase.
 *   The page still never sits blank or frozen: giving up means SAYING the
 *   service cannot be reached and offering a retry, which is more use to a
 *   payer than a shimmer that never resolves.
 * - watch:   a loaded, still-pending intent; steady polling to catch
 *   paid-elsewhere/expired, slowing down after a minute.
 * - sync:    the payer's tx just mined; quick checks backing off toward the
 *   cap until the backend reflects the payment (indexer finality is
 *   typically 12 to 15 seconds on Base Sepolia).
 */

export const INITIAL_RETRY_DELAYS = [1_000, 2_000, 4_000, 8_000] as const
export const INITIAL_RETRY_CAP = 10_000
export const SLOW_NOTICE_AFTER = 4_000
/**
 * How long the initial fetch keeps retrying before it admits defeat. Long
 * enough to ride out the blips the backoff ladder exists for, short enough
 * that a payer is not left guessing. After this the automatic timer stops and
 * the payer gets a plain statement plus a retry button; connectivity coming
 * back resumes it without a reload.
 */
export const INITIAL_RETRY_GIVE_UP_AFTER = 30_000

export const WATCH_INTERVAL = 5_000
export const WATCH_INTERVAL_SLOW = 10_000
export const WATCH_SLOWDOWN_AFTER = 60_000

export const SYNC_DELAYS = [2_000, 3_000, 5_000, 8_000] as const
export const SYNC_CAP = 10_000

/**
 * Backoff for a 429 (rate limited) or the limiter's own fail-closed 503.
 *
 * watch/sync deliberately hold their cadence through ordinary errors — a blip
 * must not kill a poll whose intent is already on screen. A 429 is the one
 * error where that is exactly wrong: every retry re-enters the bucket it is
 * waiting on, so a tab that ignores the limit stays limited for as long as it
 * is open. Hence a floor strictly above the slowest normal cadence.
 *
 * The ceiling exists because the backend sends its whole window (60s) as
 * Retry-After, and sitting out a full minute helps nobody: the window slides
 * continuously, so capacity returns gradually rather than all at once.
 */
export const THROTTLE_MIN_DELAY = 15_000
export const THROTTLE_MAX_DELAY = 30_000

export function throttleDelay(retryAfterSeconds: number | null): number {
  if (retryAfterSeconds != null && Number.isFinite(retryAfterSeconds)) {
    return Math.min(
      Math.max(retryAfterSeconds * 1_000, THROTTLE_MIN_DELAY),
      THROTTLE_MAX_DELAY,
    )
  }
  return THROTTLE_MIN_DELAY
}

export type PollKind = 'initial' | 'watch' | 'sync'

export function pollDelay(
  kind: PollKind,
  attempt: number,
  elapsedMs: number,
): number {
  if (kind === 'initial') {
    return INITIAL_RETRY_DELAYS[attempt] ?? INITIAL_RETRY_CAP
  }
  if (kind === 'watch') {
    return elapsedMs > WATCH_SLOWDOWN_AFTER ? WATCH_INTERVAL_SLOW : WATCH_INTERVAL
  }
  return SYNC_DELAYS[attempt] ?? SYNC_CAP
}
