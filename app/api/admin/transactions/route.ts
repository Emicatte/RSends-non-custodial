import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

const COOKIE_NAME = 'admin_session'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

function getAdminSecret() {
  return process.env.ADMIN_SECRET || ''
}

async function isAuthorized(req: NextRequest): Promise<boolean> {
  // 1. Cookie-based auth (new httpOnly session)
  const cookie = req.cookies.get(COOKIE_NAME)?.value
  if (cookie) {
    const { validateToken } = await import('@/lib/auth/adminTokens')
    return validateToken(cookie)
  }

  // 2. Fallback: Authorization header (backward compatibility)
  const auth = req.headers.get('Authorization') ?? ''
  const bearer = auth.startsWith('Bearer ') ? auth.slice(7) : ''
  const secret = getAdminSecret()
  return !!(secret && bearer && bearer === secret)
}

export async function GET(req: NextRequest) {
  const secret = getAdminSecret()

  if (!secret) {
    return NextResponse.json(
      { error: 'ADMIN_NOT_CONFIGURED', message: 'ADMIN_SECRET is not set.' },
      { status: 503 },
    )
  }

  if (!(await isAuthorized(req))) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Invalid or missing admin token.' },
      { status: 401 },
    )
  }

  const { searchParams } = req.nextUrl
  const limit    = searchParams.get('limit') ?? '20'
  const page     = parseInt(searchParams.get('page') ?? '1', 10)
  const wallet   = searchParams.get('wallet')
  const currency = searchParams.get('currency')
  const status   = searchParams.get('status')
  const network  = searchParams.get('network')

  const backendParams = new URLSearchParams()
  backendParams.set('limit', limit)
  if (wallet)   backendParams.set('wallet', wallet)
  if (currency) backendParams.set('currency', currency)
  if (status)   backendParams.set('status', status)
  if (network)  backendParams.set('network', network)
  if (page > 1) backendParams.set('offset', String((page - 1) * parseInt(limit, 10)))

  const url = `${getBackendUrl()}/api/v1/tx/recent?${backendParams.toString()}`

  try {
    const backendRes = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(10000),
    })

    const data = await backendRes.json().catch(() => ({}))
    return NextResponse.json(data, { status: backendRes.status })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: `Failed to reach backend: ${msg}` },
      { status: 502 },
    )
  }
}
