/**
 * lib/web3/usePaymentIntent — the fetch-only intent driver (the WebSocket
 * channel is gone). Fake timers + fetch stub; no wagmi involved.
 * Covers: initial retry with backoff + slow notice, 404 short-circuit,
 * pending watch cadence, post-mining sync backoff converging on paid, and
 * timer cleanup on unmount.
 */
import { act, renderHook } from '@testing-library/react'
import { usePaymentIntent } from '@/lib/web3/usePaymentIntent'
import {
  INITIAL_RETRY_CAP,
  INITIAL_RETRY_DELAYS,
  INITIAL_RETRY_GIVE_UP_AFTER,
  SLOW_NOTICE_AFTER,
  SYNC_DELAYS,
  THROTTLE_MAX_DELAY,
  WATCH_INTERVAL,
} from '@/lib/web3/intentPoll'

const RAW = {
  status: 'pending',
  expires_at: '2099-01-01T00:00:00Z',
  amount: 50,
  currency: 'USDC',
  chain: 'BASE_SEPOLIA',
}

function okResponse(raw: unknown) {
  return { ok: true, status: 200, json: async () => raw }
}

afterEach(() => {
  jest.useRealTimers()
})

async function flush() {
  // Let pending fetch promises settle inside act.
  await act(async () => {})
}

describe('usePaymentIntent', () => {
  it('loads a pending intent and exposes it as ready', async () => {
    global.fetch = jest.fn().mockResolvedValue(okResponse(RAW)) as never
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_x'))
    expect(result.current.phase.kind).toBe('loading')
    await flush()
    expect(result.current.phase.kind).toBe('ready')
    if (result.current.phase.kind === 'ready') {
      expect(result.current.phase.intent.status).toBe('pending')
    }
    unmount()
  })

  it('404 short-circuits to not_found without retrying', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_gone'))
    await flush()
    expect(result.current.phase.kind).toBe('not_found')
    await act(async () => {
      jest.advanceTimersByTime(60_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    unmount()
  })

  it('retries failures with backoff and raises the slow notice', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('network down'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_slow'))
    await flush()
    expect(result.current.phase).toEqual({ kind: 'loading', slow: false })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      jest.advanceTimersByTime(INITIAL_RETRY_DELAYS[0])
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      jest.advanceTimersByTime(INITIAL_RETRY_DELAYS[1])
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)

    // Past the slow threshold the notice flag flips while still retrying.
    await act(async () => {
      jest.advanceTimersByTime(SLOW_NOTICE_AFTER)
    })
    expect(result.current.phase).toEqual({ kind: 'loading', slow: true })

    // Recovery: next retry succeeds.
    fetchMock.mockResolvedValue(okResponse(RAW))
    await act(async () => {
      jest.advanceTimersByTime(INITIAL_RETRY_DELAYS[3])
    })
    await flush()
    expect(result.current.phase.kind).toBe('ready')
    unmount()
  })

  it('watches a pending intent and stops once terminal', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW)) // initial
      .mockResolvedValueOnce(okResponse(RAW)) // watch 1
      .mockResolvedValue(okResponse({ ...RAW, status: 'expired' })) // watch 2+
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_watch'))
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    if (result.current.phase.kind === 'ready') {
      expect(result.current.phase.intent.status).toBe('expired')
    }

    // Terminal → watching stops.
    await act(async () => {
      jest.advanceTimersByTime(10 * WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    unmount()
  })

  it('sync polling after mining backs off until the backend reflects paid', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW)) // initial
      .mockResolvedValueOnce(okResponse(RAW)) // sync 1: still pending
      .mockResolvedValueOnce(okResponse(RAW)) // sync 2: still pending
      .mockResolvedValue(okResponse({ ...RAW, status: 'paid' })) // sync 3+
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_sync'))
    await flush()

    act(() => {
      result.current.startSyncPolling()
    })

    await act(async () => {
      jest.advanceTimersByTime(SYNC_DELAYS[0])
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      jest.advanceTimersByTime(SYNC_DELAYS[1])
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)

    await act(async () => {
      jest.advanceTimersByTime(SYNC_DELAYS[2])
    })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(result.current.backendPaid).toBe(true)

    // Paid → sync polling stops.
    await act(async () => {
      jest.advanceTimersByTime(60_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    unmount()
  })

  it('cleans its timers on unmount', async () => {
    const fetchMock = jest.fn().mockResolvedValue(okResponse(RAW))
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { unmount } = renderHook(() => usePaymentIntent('pi_cleanup'))
    await flush()
    unmount()
    await act(async () => {
      jest.advanceTimersByTime(120_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

// ── Giving up honestly, and coming back ──────────────────────────
//
// The initial fetch used to retry forever behind a shimmer: the payer never
// learned that anything was wrong and had nothing to press. It now gives up
// into an explicit `unreachable` phase with a manual retry, and resumes by
// itself when connectivity returns.

describe('usePaymentIntent when the payment service cannot be reached', () => {
  async function failUntilGiveUp(fetchMock: jest.Mock) {
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_down'))
    await flush()
    // Walk past the whole backoff ladder and then past the give-up window.
    for (const delay of INITIAL_RETRY_DELAYS) {
      await act(async () => {
        jest.advanceTimersByTime(delay)
      })
    }
    for (let i = 0; i < 10; i += 1) {
      await act(async () => {
        jest.advanceTimersByTime(INITIAL_RETRY_CAP)
      })
    }
    return { result, unmount, fetchMock }
  }

  it('stops retrying after the give-up window and says so', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('Failed to fetch'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { result, unmount } = await failUntilGiveUp(fetchMock)
    expect(result.current.phase.kind).toBe('unreachable')

    const callsAtGiveUp = fetchMock.mock.calls.length
    await act(async () => {
      jest.advanceTimersByTime(10 * 60_000)
    })
    expect(fetchMock).toHaveBeenCalledTimes(callsAtGiveUp)
    unmount()
  })

  it('keeps the slow notice and never gives up before the window', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('Failed to fetch'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_slow2'))
    await flush()

    await act(async () => {
      jest.advanceTimersByTime(SLOW_NOTICE_AFTER + INITIAL_RETRY_DELAYS[0])
    })
    expect(result.current.phase).toEqual({ kind: 'loading', slow: true })
    expect(INITIAL_RETRY_GIVE_UP_AFTER).toBeGreaterThan(SLOW_NOTICE_AFTER)
    unmount()
  })

  it('the manual retry still works after it has given up', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('Failed to fetch'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { result, unmount } = await failUntilGiveUp(fetchMock)
    expect(result.current.phase.kind).toBe('unreachable')

    fetchMock.mockResolvedValue(okResponse(RAW))
    await act(async () => {
      result.current.refresh()
    })
    await flush()
    expect(result.current.phase.kind).toBe('ready')
    unmount()
  })

  it('resumes on its own when connectivity returns, with no reload', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('Failed to fetch'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { result, unmount } = await failUntilGiveUp(fetchMock)
    expect(result.current.phase.kind).toBe('unreachable')

    fetchMock.mockResolvedValue(okResponse(RAW))
    await act(async () => {
      window.dispatchEvent(new Event('online'))
    })
    await flush()
    expect(result.current.phase.kind).toBe('ready')
    unmount()
  })

  it('recovers before the window without ever showing unreachable', async () => {
    const fetchMock = jest
      .fn()
      .mockRejectedValueOnce(new Error('Failed to fetch'))
      .mockResolvedValue(okResponse(RAW))
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { result, unmount } = renderHook(() => usePaymentIntent('pi_blip'))
    await flush()
    expect(result.current.phase.kind).toBe('loading')

    await act(async () => {
      jest.advanceTimersByTime(INITIAL_RETRY_DELAYS[0])
    })
    await flush()
    expect(result.current.phase.kind).toBe('ready')
    unmount()
  })

  it('stops listening for connectivity after unmount', async () => {
    const fetchMock = jest.fn().mockRejectedValue(new Error('Failed to fetch'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()
    const { unmount } = await failUntilGiveUp(fetchMock)
    const callsAtGiveUp = fetchMock.mock.calls.length

    unmount()
    await act(async () => {
      window.dispatchEvent(new Event('online'))
    })
    expect(fetchMock).toHaveBeenCalledTimes(callsAtGiveUp)
  })
})

// ── rate limiting ────────────────────────────────────────────
//
// The watch poll deliberately keeps its cadence through errors (a transient
// blip must not kill a poll whose intent is already on screen). A 429 is not a
// blip: holding the cadence means hammering a bucket that then never drains,
// so the tab stays limited for as long as it is open. Back off instead.

describe('usePaymentIntent when the backend rate limits it', () => {
  function limited(retryAfter?: string) {
    return {
      ok: false,
      status: 429,
      headers: { get: (h: string) => (h.toLowerCase() === 'retry-after' ? retryAfter ?? null : null) },
      json: async () => ({ error: 'RATE_LIMIT_EXCEEDED', retry_after: 60 }),
    }
  }

  it('backs off instead of holding the watch cadence', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW)) // initial load succeeds
      .mockResolvedValue(limited('60'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { unmount } = renderHook(() => usePaymentIntent('pi_limited'))
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // First watch tick is rate limited.
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    // The normal cadence would fire again here. It must not.
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      jest.advanceTimersByTime(THROTTLE_MAX_DELAY)
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    unmount()
  })

  it('keeps the loaded intent on screen while throttled', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW))
      .mockResolvedValue(limited('60'))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { result, unmount } = renderHook(() => usePaymentIntent('pi_limited2'))
    await flush()
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })

    // Being throttled is not being unreachable: the intent is still valid.
    expect(result.current.phase.kind).toBe('ready')
    unmount()
  })

  it('recovers the normal cadence once the limit clears', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW))
      .mockResolvedValueOnce(limited('60'))
      .mockResolvedValue(okResponse(RAW))
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { unmount } = renderHook(() => usePaymentIntent('pi_recover'))
    await flush()
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    // Backoff elapses, the retry succeeds...
    await act(async () => {
      jest.advanceTimersByTime(THROTTLE_MAX_DELAY)
    })
    expect(fetchMock).toHaveBeenCalledTimes(3)

    // ...and the steady cadence resumes: one watch interval, exactly one call.
    // Still throttled, this window (well under THROTTLE_MIN_DELAY) would be
    // silent.
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    unmount()
  })

  it('backs off on the fail-closed 503 too', async () => {
    // Redis loss makes the limiter itself answer 503 RATE_LIMIT_UNAVAILABLE.
    // Retrying every 5s through an outage is exactly the wrong response.
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(okResponse(RAW))
      .mockResolvedValue({
        ok: false,
        status: 503,
        headers: { get: () => '5' },
        json: async () => ({ error: 'RATE_LIMIT_UNAVAILABLE' }),
      })
    global.fetch = fetchMock as never
    jest.useFakeTimers()

    const { unmount } = renderHook(() => usePaymentIntent('pi_503'))
    await flush()
    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    await act(async () => {
      jest.advanceTimersByTime(WATCH_INTERVAL)
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    unmount()
  })
})
