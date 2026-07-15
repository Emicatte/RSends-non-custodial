/**
 * @jest-environment node
 *
 * rp-auth proxy — Set-Cookie Path rewrite.
 *
 * The backend scopes its auth cookies to Path=/api/v1/auth, but the browser
 * stores the replayed cookies against THIS origin, where the auth routes are
 * mounted at /api/rp-auth/api/v1/auth/*. Replaying the backend Path verbatim
 * stored a cookie that never path-matched any request the client makes — the
 * refresh cookie existed but was never sent, so every refresh was 401
 * no_session and any idle >15 min ended at /login. Pinned here:
 *   • Path=/api/v1/auth is rewritten to Path=/api/rp-auth/api/v1/auth —
 *     including on Max-Age=0 deletion cookies (logout must clear what login
 *     set) — with every other attribute preserved verbatim;
 *   • multiple Set-Cookie headers all survive the replay;
 *   • an already-proxy-scoped Path is not double-prefixed; a cookie without
 *     a Path attribute passes through untouched;
 *   • the browser Cookie header is forwarded to the backend unchanged.
 */

import { POST } from '@/app/api/rp-auth/[...path]/route'
import { NextRequest } from 'next/server'

const BACKEND = 'http://backend.test'

let fetchMock: jest.Mock

beforeAll(() => {
  process.env.RPAGOS_BACKEND_URL = BACKEND
})

beforeEach(() => {
  fetchMock = jest.fn()
  global.fetch = fetchMock as unknown as typeof fetch
})

function backendResponse(setCookies: string[], body = '{"ok":true}'): Response {
  const headers = new Headers({ 'content-type': 'application/json' })
  for (const c of setCookies) headers.append('set-cookie', c)
  return new Response(body, { status: 200, headers })
}

async function callProxy(cookieHeader?: string) {
  const req = new NextRequest(
    'http://localhost/api/rp-auth/api/v1/auth/refresh',
    {
      method: 'POST',
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    },
  )
  return POST(req, {
    params: Promise.resolve({ path: ['api', 'v1', 'auth', 'refresh'] }),
  })
}

describe('rp-auth proxy Set-Cookie replay', () => {
  it('rewrites the backend cookie Path onto the proxy mount, attributes intact', async () => {
    fetchMock.mockResolvedValue(
      backendResponse([
        'rsends_refresh=tok; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=strict; Secure',
        'rsends_sid=sid1; HttpOnly; Max-Age=604800; Path=/api/v1/auth; SameSite=strict; Secure',
      ]),
    )

    const res = await callProxy()
    const cookies = res.headers.getSetCookie()

    expect(cookies).toHaveLength(2)
    expect(cookies[0]).toBe(
      'rsends_refresh=tok; HttpOnly; Max-Age=604800; Path=/api/rp-auth/api/v1/auth; SameSite=strict; Secure',
    )
    expect(cookies[1]).toBe(
      'rsends_sid=sid1; HttpOnly; Max-Age=604800; Path=/api/rp-auth/api/v1/auth; SameSite=strict; Secure',
    )
  })

  it('rewrites deletion cookies too, so logout clears what login set', async () => {
    fetchMock.mockResolvedValue(
      backendResponse([
        'rsends_refresh=""; Max-Age=0; Path=/api/v1/auth',
        'rsends_sid=""; Max-Age=0; Path=/api/v1/auth',
      ]),
    )

    const res = await callProxy()
    const cookies = res.headers.getSetCookie()
    expect(cookies).toEqual([
      'rsends_refresh=""; Max-Age=0; Path=/api/rp-auth/api/v1/auth',
      'rsends_sid=""; Max-Age=0; Path=/api/rp-auth/api/v1/auth',
    ])
  })

  it('does not double-prefix an already-proxy-scoped Path', async () => {
    fetchMock.mockResolvedValue(
      backendResponse(['a=b; Path=/api/rp-auth/api/v1/auth; HttpOnly']),
    )

    const res = await callProxy()
    expect(res.headers.getSetCookie()).toEqual([
      'a=b; Path=/api/rp-auth/api/v1/auth; HttpOnly',
    ])
  })

  it('passes a cookie without a Path attribute through untouched', async () => {
    fetchMock.mockResolvedValue(backendResponse(['plain=1; HttpOnly']))

    const res = await callProxy()
    expect(res.headers.getSetCookie()).toEqual(['plain=1; HttpOnly'])
  })

  it('forwards the browser Cookie header to the backend unchanged', async () => {
    fetchMock.mockResolvedValue(backendResponse([]))

    await callProxy('rsends_sid=sid1; rsends_refresh=tok')

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${BACKEND}/api/v1/auth/refresh`)
    expect((init.headers as Record<string, string>).cookie).toBe(
      'rsends_sid=sid1; rsends_refresh=tok',
    )
  })
})
