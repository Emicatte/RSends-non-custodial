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
  WATCH_INTERVAL,
  WATCH_INTERVAL_SLOW,
  pollDelay,
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
