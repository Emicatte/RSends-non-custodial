/**
 * apiCall refresh hardening — the failure classification and single-flight
 * that keep a long-lived polling page (approval pending) alive:
 *   • 401 → one refresh → replay succeeds;
 *   • refresh 5xx/network = TRANSIENT: no logout, retryable error;
 *   • refresh 401/403 = TERMINAL: client sign-out + session_expired;
 *   • concurrent 401s share ONE refresh call (reuse-detection safety).
 */

jest.mock('@/lib/logoutClient', () => ({
  performLogout: jest.fn().mockResolvedValue(undefined),
}))

import { apiCall } from '@/lib/auth-client'
import { performLogout } from '@/lib/logoutClient'

const mockLogout = performLogout as jest.Mock

const REFRESH_URL = '/api/rp-auth/api/v1/auth/refresh'

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response
}

let fetchMock: jest.Mock

beforeEach(() => {
  fetchMock = jest.fn()
  global.fetch = fetchMock as unknown as typeof fetch
  mockLogout.mockClear()
})

function refreshCalls(): number {
  return fetchMock.mock.calls.filter(([url]) => url === REFRESH_URL).length
}

describe('apiCall refresh', () => {
  it('401 → refresh → replay succeeds (pinned: the poll survives token expiry)', async () => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === REFRESH_URL) return jsonResponse(200, { access_token: 'tok-2' })
      const auth = new Headers(init?.headers).get('Authorization')
      return auth === 'Bearer tok-2'
        ? jsonResponse(200, { approval_status: 'approved' })
        : jsonResponse(401, { code: 'token_expired' })
    })

    const out = await apiCall<{ approval_status: string }>('/api/v1/user/onboarding', 'tok-1')
    expect(out.approval_status).toBe('approved')
    expect(refreshCalls()).toBe(1)
    expect(mockLogout).not.toHaveBeenCalled()
  })

  it('transient refresh failure (503) throws refresh_unavailable WITHOUT logging out', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_URL ? jsonResponse(503, {}) : jsonResponse(401, {}),
    )

    await expect(apiCall('/x', 'tok-1')).rejects.toThrow('refresh_unavailable')
    expect(mockLogout).not.toHaveBeenCalled()
  })

  it('network failure on refresh is transient too', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === REFRESH_URL) throw new TypeError('fetch failed')
      return jsonResponse(401, {})
    })

    await expect(apiCall('/x', 'tok-1')).rejects.toThrow('refresh_unavailable')
    expect(mockLogout).not.toHaveBeenCalled()
  })

  it('terminal refresh failure (401) signs out and throws session_expired', async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url === REFRESH_URL ? jsonResponse(401, { code: 'no_session' }) : jsonResponse(401, {}),
    )

    await expect(apiCall('/x', 'tok-1')).rejects.toThrow('session_expired')
    expect(mockLogout).toHaveBeenCalledWith({ skipBackend: true })
  })

  it('single-flight: concurrent 401s share one refresh call', async () => {
    let releaseRefresh!: (r: Response) => void
    const gate = new Promise<Response>((resolve) => {
      releaseRefresh = resolve
    })
    let dataCalls = 0
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === REFRESH_URL) return gate
      const auth = new Headers(init?.headers).get('Authorization')
      if (auth === 'Bearer tok-2') return jsonResponse(200, { n: ++dataCalls })
      return jsonResponse(401, {})
    })

    const p1 = apiCall<{ n: number }>('/a', 'tok-1')
    const p2 = apiCall<{ n: number }>('/b', 'tok-1')
    // Let both first requests 401 and both callers reach the refresh gate.
    await new Promise((r) => setTimeout(r, 0))
    releaseRefresh(jsonResponse(200, { access_token: 'tok-2' }))

    await Promise.all([p1, p2])
    expect(refreshCalls()).toBe(1)
    expect(mockLogout).not.toHaveBeenCalled()
  })
})
