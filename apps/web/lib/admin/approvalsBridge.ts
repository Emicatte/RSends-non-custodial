import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'
import { mapAdminBackendError } from '@/lib/admin/adminBackendError'

export { mapAdminBackendError }

/**
 * Server-side bridge to the backend's admin approval queue.
 *
 * Browser side: protected by the existing /admin cookie+2FA session (full
 * scope only — same rules as /api/admin/transactions).
 * Backend side: speaks the backend's EXISTING admin auth — the X-Admin-Token
 * header (BACKEND_ADMIN_API_TOKEN, a server-only env holding the backend's
 * ADMIN_API_TOKEN value; never shipped to the client). The shared /api/backend
 * proxy denylists admin/* and strips this header by design — admin traffic
 * only flows through the dedicated /api/admin/approvals server routes.
 */

const COOKIE_NAME = 'admin_session'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

function getBackendAdminToken() {
  return process.env.BACKEND_ADMIN_API_TOKEN || ''
}

export async function isAuthorized(req: NextRequest): Promise<boolean> {
  const cookie = req.cookies.get(COOKIE_NAME)?.value
  if (cookie) {
    const { getTokenScope } = await import('@/lib/auth/adminTokens')
    return getTokenScope(cookie) === 'full'
  }
  // Bearer ADMIN_SECRET fallback (password-only, no 2FA) — prod-disabled
  // unless ADMIN_ALLOW_BEARER=1 (M11), shared implementation.
  const { bearerAdminAuthorized } = await import('@/lib/auth/adminTokens')
  return bearerAdminAuthorized(req.headers.get('Authorization'))
}

export function notConfigured(): NextResponse | null {
  if (!getBackendAdminToken()) {
    return NextResponse.json(
      {
        error: 'ADMIN_NOT_CONFIGURED',
        message: 'BACKEND_ADMIN_API_TOKEN is not set.',
      },
      { status: 503 },
    )
  }
  return null
}

export async function forwardToBackend(
  path: string,
  init?: RequestInit,
): Promise<NextResponse> {
  try {
    const backendRes = await fetch(`${getBackendUrl()}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Token': getBackendAdminToken(),
        ...(init?.headers ?? {}),
      },
      signal: AbortSignal.timeout(10000),
    })
    const classified = mapAdminBackendError(backendRes.status)
    if (classified) {
      return NextResponse.json(classified, { status: backendRes.status })
    }
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
