import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'
import { clientIpHeaders } from '@/lib/proxyClientIp'

export const maxDuration = 30

/**
 * Cookie-aware proxy to the RPagos backend.
 *
 * Used exclusively by the auth flow (/api/v1/auth/login|refresh|logout|me).
 *
 * Differences vs /api/backend/[...path]/route.ts:
 *   • Forwards the browser `cookie` header to the backend (rsends_refresh +
 *     rsends_sid travel server-side so refresh/logout work).
 *   • Replays every `Set-Cookie` header from the backend response back on
 *     the browser, preserving HttpOnly / Secure / SameSite attributes —
 *     but REWRITING the Path attribute onto this proxy's mount (below).
 *
 * The existing /api/backend proxy is NOT modified — it stays Bearer-only
 * for non-auth calls.
 */

function getBackendUrl(): string {
  return requireEnv('RPAGOS_BACKEND_URL')
}

const FORWARD_HEADERS = [
  'content-type',
  'accept',
  'authorization',
  'cookie',
  'x-idempotency-key',
  // The client's correlation id (LoginForm sends both). Without these two the
  // id shown to a user on a failed login joins to nothing: the backend
  // generates its own, and auth_audit_log.correlation_id never sees the
  // browser's. PR #79 added the sender and not the allowlist.
  'x-request-id',
  'x-correlation-id',
] as const

/**
 * Backend response headers replayed to the browser.
 *
 * Explicit, like the Set-Cookie replay below: the body has already been read
 * and re-encoded by this route, so copying the backend's headers wholesale
 * would carry a content-length/content-encoding that no longer describes what
 * we send. These two are the correlation pair — the backend echoes
 * X-Correlation-ID (generating one when the client sent none), so replaying
 * them is what lets a user read back an id that exists on both sides.
 */
const REPLAY_HEADERS = ['x-correlation-id', 'x-request-id'] as const

/** Where this proxy is mounted on the web origin. */
const PROXY_PREFIX = '/api/rp-auth'

/**
 * The browser stores replayed cookies against THIS origin, where every auth
 * call the client makes lives under /api/rp-auth/... — so a backend Path
 * (Path=/api/v1/auth) replayed verbatim can NEVER path-match a request: the
 * cookie exists in the jar but is never sent, refresh is eternally 401
 * no_session, and any idle past the access-token TTL ends at /login. Prefix
 * the backend Path with the proxy mount; every other attribute (HttpOnly,
 * Secure, SameSite, Max-Age) replays byte-identical. Applies equally to
 * Max-Age=0 deletion cookies so logout clears what login set.
 */
function rewriteCookiePath(setCookie: string): string {
  return setCookie.replace(
    /;(\s*)path=(\/[^;]*)/i,
    (match, ws: string, p: string) =>
      p.startsWith(PROXY_PREFIX)
        ? match
        : `;${ws}Path=${PROXY_PREFIX}${p}`,
  )
}

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params
  const subPath = (path ?? []).join('/')
  const targetUrl = `${getBackendUrl()}/${subPath}${req.nextUrl.search}`

  // Derived, not forwarded: the allowlist above carries browser-supplied
  // headers, and the client IP must never come from one. Login/refresh are the
  // brute-force-sensitive surface, so this is the hop that most needs it.
  const headers: Record<string, string> = {}
  for (const h of FORWARD_HEADERS) {
    const v = req.headers.get(h)
    if (v) headers[h] = v
  }
  Object.assign(headers, clientIpHeaders(req))

  let body: string | undefined
  if (req.method !== 'GET' && req.method !== 'HEAD' && req.method !== 'DELETE') {
    try {
      body = await req.text()
    } catch {
      /* empty body is fine */
    }
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
      cache: 'no-store',
      signal: AbortSignal.timeout(25000),
    })

    const data = await backendRes.text()
    const contentType = backendRes.headers.get('content-type') || 'application/json'

    const response = new NextResponse(data, {
      status: backendRes.status,
      headers: { 'Content-Type': contentType },
    })

    // Replay every Set-Cookie so HttpOnly+Secure+SameSite attributes reach
    // the browser verbatim. Node 18 / Next 14 expose getSetCookie().
    const setCookies =
      typeof (backendRes.headers as unknown as { getSetCookie?: () => string[] })
        .getSetCookie === 'function'
        ? (backendRes.headers as unknown as { getSetCookie: () => string[] }).getSetCookie()
        : backendRes.headers.get('set-cookie')
          ? [backendRes.headers.get('set-cookie') as string]
          : []
    for (const c of setCookies) {
      response.headers.append('set-cookie', rewriteCookiePath(c))
    }

    for (const h of REPLAY_HEADERS) {
      const v = backendRes.headers.get(h)
      if (v) response.headers.set(h, v)
    }

    return response
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error(`[rp-auth-proxy] ${req.method} /${subPath} failed:`, msg)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: msg },
      { status: 502 },
    )
  }
}

export const GET = proxyRequest
export const POST = proxyRequest
export const PUT = proxyRequest
export const PATCH = proxyRequest
export const DELETE = proxyRequest
export const HEAD = proxyRequest
