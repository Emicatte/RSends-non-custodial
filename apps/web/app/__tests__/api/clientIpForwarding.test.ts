/**
 * @jest-environment node
 *
 * Client-IP forwarding across all three backend proxies.
 *
 * The backend derives every per-IP rate-limit bucket and every audit row from
 * the address it sees. Before this, none of these proxies sent one, so the
 * backend fell back to its socket peer — identical for every request on earth,
 * which quietly turned each per-IP limit into a global one.
 *
 * Two properties are pinned here, and the second matters more than the first:
 *
 *   • the observed client IP is forwarded, together with the shared secret
 *     that proves the hop is ours;
 *   • the IP is DERIVED from platform-set sources, never passed through from
 *     the browser. A caller who sets x-forwarded-for or the claim header
 *     themselves must not be able to choose their own bucket. The backend
 *     rejects unproven claims independently (test_trusted_proxy.py), so this
 *     is defence in depth on the other side of the same boundary.
 */

import { GET as payGet } from '@/app/api/pay/[intentId]/route'
import { GET as backendGet } from '@/app/api/backend/[...path]/route'
import { POST as rpAuthPost } from '@/app/api/rp-auth/[...path]/route'
import { NextRequest } from 'next/server'

const BACKEND = 'http://backend.test'
const SECRET = 'test-proxy-secret-value'

const CLIENT_IP_HEADER = 'x-rsend-client-ip'
const PROXY_SECRET_HEADER = 'x-rsend-proxy-secret'

let fetchMock: jest.Mock

beforeAll(() => {
  process.env.RPAGOS_BACKEND_URL = BACKEND
  process.env.INTERNAL_PROXY_SECRET = SECRET
})

beforeEach(() => {
  fetchMock = jest.fn().mockResolvedValue(
    new Response('{"ok":true}', {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  )
  global.fetch = fetchMock as unknown as typeof fetch
})

/** Headers the proxy actually put on the wire, lowercased. */
function sentHeaders(): Record<string, string> {
  expect(fetchMock).toHaveBeenCalled()
  const init = fetchMock.mock.calls[0][1] ?? {}
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(
    (init.headers ?? {}) as Record<string, string>,
  )) {
    out[k.toLowerCase()] = v
  }
  return out
}

async function callPay(headers?: Record<string, string>) {
  const req = new NextRequest('http://localhost/api/pay/pi_abcdef0123456789', {
    headers,
  })
  return payGet(req, {
    params: Promise.resolve({ intentId: 'pi_abcdef0123456789' }),
  })
}

async function callBackend(headers?: Record<string, string>) {
  const req = new NextRequest(
    'http://localhost/api/backend/api/v1/user/org/stats',
    { headers },
  )
  return backendGet(req, {
    params: Promise.resolve({ path: ['api', 'v1', 'user', 'org', 'stats'] }),
  })
}

async function callRpAuth(headers?: Record<string, string>) {
  const req = new NextRequest(
    'http://localhost/api/rp-auth/api/v1/auth/login',
    { method: 'POST', headers },
  )
  return rpAuthPost(req, {
    params: Promise.resolve({ path: ['api', 'v1', 'auth', 'login'] }),
  })
}

const PROXIES: [string, (h?: Record<string, string>) => Promise<unknown>][] = [
  ['pay', callPay],
  ['backend', callBackend],
  ['rp-auth', callRpAuth],
]

describe.each(PROXIES)('%s proxy', (_name, call) => {
  it('forwards the observed client IP with the shared proxy secret', async () => {
    await call({ 'x-real-ip': '203.0.113.42' })

    const sent = sentHeaders()
    expect(sent[CLIENT_IP_HEADER]).toBe('203.0.113.42')
    expect(sent[PROXY_SECRET_HEADER]).toBe(SECRET)
  })

  it('derives the IP rather than echoing a browser-supplied claim header', async () => {
    await call({
      'x-real-ip': '203.0.113.42',
      [CLIENT_IP_HEADER]: '1.2.3.4',
    })

    // The spoofed value must not survive: whoever holds the link would
    // otherwise mint a fresh rate-limit bucket per request.
    expect(sentHeaders()[CLIENT_IP_HEADER]).toBe('203.0.113.42')
  })

  it('never lets the browser choose the value through x-forwarded-for alone', async () => {
    await call({ 'x-forwarded-for': '9.9.9.9, 203.0.113.42' })

    // getClientIp counts from the RIGHT: the leftmost hop is client-controlled.
    expect(sentHeaders()[CLIENT_IP_HEADER]).toBe('203.0.113.42')
  })

  it('omits the pair entirely when no secret is configured', async () => {
    const prev = process.env.INTERNAL_PROXY_SECRET
    delete process.env.INTERNAL_PROXY_SECRET
    try {
      await call({ 'x-real-ip': '203.0.113.42' })
      const sent = sentHeaders()
      // Sending an unprovable claim would be pure noise — the backend drops it
      // and logs a mismatch warning that would then be permanent.
      expect(sent[CLIENT_IP_HEADER]).toBeUndefined()
      expect(sent[PROXY_SECRET_HEADER]).toBeUndefined()
    } finally {
      process.env.INTERNAL_PROXY_SECRET = prev
    }
  })
})

describe('pay proxy rate-limit headers', () => {
  it('replays Retry-After and the X-RateLimit trio on a 429', async () => {
    // The route re-encodes the body, so backend headers are not copied
    // wholesale. These are the ones the client needs: without Retry-After a
    // 429-aware poller has nothing to back off by.
    fetchMock.mockResolvedValue(
      new Response('{"error":"RATE_LIMIT_EXCEEDED","retry_after":60}', {
        status: 429,
        headers: {
          'content-type': 'application/json',
          'retry-after': '60',
          'x-ratelimit-limit': '40',
          'x-ratelimit-remaining': '0',
          'x-ratelimit-reset': '1789999999',
        },
      }),
    )

    const res = await callPay()

    expect(res.status).toBe(429)
    expect(res.headers.get('retry-after')).toBe('60')
    expect(res.headers.get('x-ratelimit-limit')).toBe('40')
    expect(res.headers.get('x-ratelimit-remaining')).toBe('0')
    expect(res.headers.get('x-ratelimit-reset')).toBe('1789999999')
  })

  it('leaves the headers off when the backend sends none', async () => {
    const res = await callPay()
    expect(res.status).toBe(200)
    expect(res.headers.get('retry-after')).toBeNull()
  })
})
