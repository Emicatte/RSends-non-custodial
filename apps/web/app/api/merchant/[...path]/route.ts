import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

/**
 * Catch-all proxy: /api/merchant/{...path}
 *
 * Forwards every request to ${RPAGOS_BACKEND_URL}/api/v1/merchant/{...path}
 * passing the Authorization header from the client (Bearer API key).
 */
async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params
  const subPath = path.join('/')

  const backend = getBackendUrl()
  const url = new URL(`/api/v1/merchant/${subPath}`, backend)

  // Forward query string
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.set(k, v))

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const auth = req.headers.get('authorization')
  if (auth) headers['Authorization'] = auth

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: 'no-store',
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    try {
      init.body = await req.text()
    } catch { /* empty body is fine */ }
  }

  try {
    const res = await fetch(url.toString(), init)
    const body = await res.text()

    return new NextResponse(body, {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (err) {
    console.error('[merchant proxy] Backend fetch failed:', err)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: 'Payment service is temporarily unavailable.' },
      { status: 502 },
    )
  }
}

export const GET = handler
export const POST = handler
export const PUT = handler
export const PATCH = handler
export const DELETE = handler
