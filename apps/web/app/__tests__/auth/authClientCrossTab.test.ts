/**
 * Cross-tab refresh hardening — the single-flight in authClient.test.ts only
 * covers ONE tab. Two tabs waking from sleep both present the same one-time
 * refresh cookie; the loser used to trip the backend's reuse detection and
 * revoke the whole session. Pinned here:
 *   • the refresh runs under the shared Web Lock (`rsends:refresh`);
 *   • a winning tab announces its token on the `rsends:auth`
 *     BroadcastChannel;
 *   • a tab that queued behind the lock REUSES a freshly-broadcast token
 *     instead of spending its own rotation;
 *   • …unless the broadcast token is the very one that just 401'd;
 *   • a received broadcast feeds the local `rsends:token-refreshed` event
 *     (tokenRefs + TokenRefreshBridge in that tab stay current).
 * Environments without Web Locks / BroadcastChannel keep the plain
 * single-flight behavior — that fallback is what authClient.test.ts runs.
 */

jest.mock('@/lib/logoutClient', () => ({
  performLogout: jest.fn().mockResolvedValue(undefined),
}))

const REFRESH_URL = '/api/rp-auth/api/v1/auth/refresh'
const CHANNEL_NAME = 'rsends:auth'

type AuthClientModule = typeof import('@/lib/auth-client')

class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = []
  onmessage: ((e: MessageEvent) => void) | null = null
  received: unknown[] = []

  constructor(public name: string) {
    FakeBroadcastChannel.instances.push(this)
  }

  postMessage(data: unknown) {
    // Like the real thing: delivered to every OTHER channel with this name.
    for (const inst of FakeBroadcastChannel.instances) {
      if (inst !== this && inst.name === this.name) {
        inst.received.push(data)
        inst.onmessage?.({ data } as MessageEvent)
      }
    }
  }

  close() {}
}

class FakeLockManager {
  requests: string[] = []
  private tail: Promise<unknown> = Promise.resolve()

  request(
    name: string,
    cb: (lock: { name: string } | null) => unknown,
  ): Promise<unknown> {
    this.requests.push(name)
    const run = this.tail.then(() => cb({ name }))
    this.tail = run.then(
      () => undefined,
      () => undefined,
    )
    return run
  }
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

const tick = () => new Promise((r) => setTimeout(r, 0))

let fetchMock: jest.Mock
let lockManager: FakeLockManager
let authClient: AuthClientModule

function refreshCalls(): number {
  return fetchMock.mock.calls.filter(([url]) => url === REFRESH_URL).length
}

beforeEach(async () => {
  jest.resetModules()
  fetchMock = jest.fn()
  global.fetch = fetchMock as unknown as typeof fetch

  FakeBroadcastChannel.instances = []
  ;(global as Record<string, unknown>).BroadcastChannel = FakeBroadcastChannel

  lockManager = new FakeLockManager()
  Object.defineProperty(global.navigator, 'locks', {
    value: lockManager,
    configurable: true,
  })

  // Fresh module state (channel, remoteToken, refreshInFlight) per test.
  authClient = await import('@/lib/auth-client')
})

afterEach(() => {
  delete (global as Record<string, unknown>).BroadcastChannel
  Object.defineProperty(global.navigator, 'locks', {
    value: undefined,
    configurable: true,
  })
})

describe('cross-tab refresh', () => {
  it('refresh runs under the shared Web Lock and announces the token', async () => {
    const otherTab = new FakeBroadcastChannel(CHANNEL_NAME)
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === REFRESH_URL) return jsonResponse(200, { access_token: 'tok-2' })
      const auth = new Headers(init?.headers).get('Authorization')
      return auth === 'Bearer tok-2'
        ? jsonResponse(200, { ok: true })
        : jsonResponse(401, {})
    })

    await authClient.apiCall('/x', 'tok-1')

    expect(lockManager.requests).toEqual(['rsends:refresh'])
    expect(otherTab.received).toEqual([{ access_token: 'tok-2' }])
  })

  it('a token broadcast while queued for the lock is reused — no own rotation', async () => {
    const otherTab = new FakeBroadcastChannel(CHANNEL_NAME)
    let releaseLock!: () => void
    // The "other tab" holds the lock: this tab's refresh has to queue.
    void lockManager.request(
      'rsends:refresh',
      () => new Promise<void>((r) => (releaseLock = r)),
    )

    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === REFRESH_URL) {
        throw new Error('this tab must not rotate — the broadcast token wins')
      }
      const auth = new Headers(init?.headers).get('Authorization')
      return auth === 'Bearer tok-remote'
        ? jsonResponse(200, { ok: true })
        : jsonResponse(401, {})
    })

    const call = authClient.apiCall<{ ok: boolean }>('/x', 'tok-1')
    await tick() // first request 401s; refresh queues behind the held lock
    otherTab.postMessage({ access_token: 'tok-remote' }) // winner announces
    releaseLock()

    const out = await call
    expect(out.ok).toBe(true)
    expect(refreshCalls()).toBe(0)
  })

  it('a broadcast token identical to the one that just 401ed is not reused', async () => {
    authClient.initAuthChannel()
    const otherTab = new FakeBroadcastChannel(CHANNEL_NAME)
    otherTab.postMessage({ access_token: 'tok-1' }) // recent, but it's the stale one

    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === REFRESH_URL) return jsonResponse(200, { access_token: 'tok-2' })
      const auth = new Headers(init?.headers).get('Authorization')
      return auth === 'Bearer tok-2'
        ? jsonResponse(200, { ok: true })
        : jsonResponse(401, {})
    })

    const out = await authClient.apiCall<{ ok: boolean }>('/x', 'tok-1')
    expect(out.ok).toBe(true)
    expect(refreshCalls()).toBe(1) // rotated for real despite the fresh broadcast
  })

  it('a received broadcast dispatches the local rsends:token-refreshed event', () => {
    authClient.initAuthChannel()
    const otherTab = new FakeBroadcastChannel(CHANNEL_NAME)

    const seen: string[] = []
    const listener = (e: Event) => {
      const token = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (token) seen.push(token)
    }
    window.addEventListener('rsends:token-refreshed', listener)
    try {
      otherTab.postMessage({ access_token: 'tok-x' })
    } finally {
      window.removeEventListener('rsends:token-refreshed', listener)
    }

    expect(seen).toEqual(['tok-x'])
  })
})
