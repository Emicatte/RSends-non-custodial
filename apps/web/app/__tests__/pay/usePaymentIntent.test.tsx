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
  INITIAL_RETRY_DELAYS,
  SLOW_NOTICE_AFTER,
  SYNC_DELAYS,
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
