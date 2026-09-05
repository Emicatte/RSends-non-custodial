/**
 * lib/web3/intentPoll — the pure polling schedule (all timing numbers in one
 * place). Three phases: initial fetch retry, pending watch, post-mining sync.
 */
import {
  INITIAL_RETRY_CAP,
  INITIAL_RETRY_DELAYS,
  SLOW_NOTICE_AFTER,
  SYNC_CAP,
  SYNC_DELAYS,
  THROTTLE_MAX_DELAY,
  THROTTLE_MIN_DELAY,
  WATCH_INTERVAL,
  WATCH_INTERVAL_SLOW,
  pollDelay,
  throttleDelay,
} from '@/lib/web3/intentPoll'

describe('pollDelay', () => {
  it('initial retries back off then cap', () => {
    expect(pollDelay('initial', 0, 0)).toBe(INITIAL_RETRY_DELAYS[0])
    expect(pollDelay('initial', 1, 0)).toBe(INITIAL_RETRY_DELAYS[1])
    expect(pollDelay('initial', 3, 0)).toBe(INITIAL_RETRY_DELAYS[3])
    expect(pollDelay('initial', 4, 0)).toBe(INITIAL_RETRY_CAP)
    expect(pollDelay('initial', 40, 0)).toBe(INITIAL_RETRY_CAP)
  })

  it('watch polls steadily, slowing down after a minute', () => {
    expect(pollDelay('watch', 0, 0)).toBe(WATCH_INTERVAL)
    expect(pollDelay('watch', 5, 59_000)).toBe(WATCH_INTERVAL)
    expect(pollDelay('watch', 6, 61_000)).toBe(WATCH_INTERVAL_SLOW)
  })

  it('sync backs off from quick checks to the cap (indexer finality)', () => {
    expect(pollDelay('sync', 0, 0)).toBe(SYNC_DELAYS[0])
    expect(pollDelay('sync', 3, 0)).toBe(SYNC_DELAYS[3])
    expect(pollDelay('sync', 4, 0)).toBe(SYNC_CAP)
  })

  it('slow notice threshold is a small number of seconds', () => {
    expect(SLOW_NOTICE_AFTER).toBeGreaterThan(0)
    expect(SLOW_NOTICE_AFTER).toBeLessThanOrEqual(5_000)
  })
})

describe('throttleDelay', () => {
  it('always waits longer than the normal watch cadence', () => {
    // The point of the whole thing: a limiter the client ignores is no limiter.
    expect(THROTTLE_MIN_DELAY).toBeGreaterThan(WATCH_INTERVAL_SLOW)
    expect(throttleDelay(null)).toBeGreaterThan(WATCH_INTERVAL_SLOW)
  })

  it('honours the server Retry-After', () => {
    expect(throttleDelay(20)).toBe(20_000)
  })

  it('clamps Retry-After at both ends', () => {
    // The backend sends the whole window (60s); waiting it out in full helps
    // nobody, since the sliding window drains continuously.
    expect(throttleDelay(60)).toBe(THROTTLE_MAX_DELAY)
    expect(throttleDelay(1)).toBe(THROTTLE_MIN_DELAY)
    expect(throttleDelay(0)).toBe(THROTTLE_MIN_DELAY)
    expect(throttleDelay(-5)).toBe(THROTTLE_MIN_DELAY)
  })

  it('falls back to the floor when the header is absent or unparseable', () => {
    expect(throttleDelay(null)).toBe(THROTTLE_MIN_DELAY)
    expect(throttleDelay(NaN)).toBe(THROTTLE_MIN_DELAY)
    expect(throttleDelay(Infinity)).toBe(THROTTLE_MIN_DELAY)
  })
})
