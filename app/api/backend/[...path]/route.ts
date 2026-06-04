import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

export const maxDuration = 30

/**
 * Catch-all proxy to the Python rpagos-backend.
 *
 * Routes  /api/backend/{...path}  →  ${RPAGOS_BACKEND_URL}/{...path}
 *
 * Why this exists:
 *   • The browser only ever talks to the same Next.js origin → ZERO CORS.
 *   • Next.js (server-side) talks to the Python backend over the network →
 *     no CORS preflight, no Origin checks, no surprises.
 *   • All wallet-auth headers (X-Wallet-Address, X-Wallet-Signature,
 *     X-Timestamp) and idempotency keys are forwarded transparently, so the
 *     existing client-side hooks need only flip their base URL.
 *
 * Status codes (4xx/5xx) and response bodies are forwarded as-is so the
 * client-side error parser (parseRSendError) keeps working unchanged.
 *
 * NOTE: WebSocket upgrades are NOT proxied here — Next.js route handlers
 * don't support WS. WebSocket clients should keep talking to the backend
 * directly (cross-origin WS is allowed by the browser without CORS).
 */

function getBackendUrl(): string {
  return requireEnv('RPAGOS_BACKEND_URL')
}

// Headers forwarded from browser → backend.
// Anything not in this list is dropped (host/origin/cookie/etc would only
// confuse the backend or leak information).
const FORWARD_HEADERS = [
  'content-type',
  'accept',
  'x-wallet-address',
  'x-wallet-signature',
  'x-wallet-session',
  'x-wallet-nonce',
  'x-wallet-mac',
  'x-timestamp',
  'x-idempotency-key',
  'x-chain-id',
  'authorization',
] as const

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params
  const subPath = (path ?? []).join('/')

  // Deny-list (H3): sensitive backend prefixes must NOT be reachable from the
  // browser through this proxy — internal/admin/keys/audit/ledger and the
  // oracle's AML check are server-only. (The oracle calls the backend directly,
  // not through this proxy, so it is unaffected.)
  const DENY = [
    'api/internal', 'admin/aml', 'api/v1/keys',
    'api/v1/audit', 'api/v1/ledger', 'api/v1/aml/check',
  ]
  if (DENY.some((p) => subPath === p || subPath.startsWith(p + '/'))) {
    return NextResponse.json({ error: 'NOT_FOUND' }, { status: 404 })
  }

  const backend = getBackendUrl()
  const queryString = req.nextUrl.search // preserves ?owner_address=...&foo=bar
  const targetUrl = `${backend}/${subPath}${queryString}`

  // Build forwarded headers.
  const headers: Record<string, string> = {}
  for (const h of FORWARD_HEADERS) {
    const v = req.headers.get(h)
    if (v) headers[h] = v
  }

  // Read body for methods that have one.
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
      // Server-to-server: no caching, no credentials shenanigans.
      cache: 'no-store',
      signal: AbortSignal.timeout(25000),
    })

    // Forward response body and status verbatim. We use .text() (not .json())
    // so non-JSON error pages or empty bodies pass through correctly.
    const data = await backendRes.text()
    const contentType = backendRes.headers.get('content-type') || 'application/json'

    return new NextResponse(data, {
      status: backendRes.status,
      headers: { 'Content-Type': contentType },
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error(`[backend-proxy] ${req.method} /${subPath} failed:`, msg)
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
