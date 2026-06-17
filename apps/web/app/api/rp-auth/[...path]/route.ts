import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

export const maxDuration = 30

/**
 * Cookie-aware proxy to the RPagos backend.
 *
 * Used exclusively by the auth flow (/api/v1/auth/google|refresh|logout|me).
 *
 * Differences vs /api/backend/[...path]/route.ts:
 *   • Forwards the browser `cookie` header to the backend (rsends_refresh +
 *     rsends_sid travel server-side so refresh/logout work).
 *   • Replays every `Set-Cookie` header from the backend response back on
 *     the browser, preserving HttpOnly / Secure / SameSite attributes.
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
] as const

async function proxyRequest(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await params
  const subPath = (path ?? []).join('/')
  const targetUrl = `${getBackendUrl()}/${subPath}${req.nextUrl.search}`

  const headers: Record<string, string> = {}
  for (const h of FORWARD_HEADERS) {
    const v = req.headers.get(h)
    if (v) headers[h] = v
  }

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
      response.headers.append('set-cookie', c)
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
