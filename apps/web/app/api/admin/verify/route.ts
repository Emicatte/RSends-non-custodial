import { NextRequest, NextResponse } from 'next/server'

const COOKIE_NAME = 'admin_session'

export async function GET(req: NextRequest) {
  const token = req.cookies.get(COOKIE_NAME)?.value

  // Cookie-based auth (new flow). A SETUP-ONLY bootstrap session reports
  // requiresSetup so the UI sends the admin to TOTP enrollment, not the
  // dashboard (M11).
  if (token) {
    const { getTokenScope } = await import('@/lib/auth/adminTokens')
    const scope = getTokenScope(token)
    if (scope) {
      return NextResponse.json({ status: 'ok', auth: 'cookie', requiresSetup: scope === 'setup' })
    }
    // Token expired — clear cookie
    const res = NextResponse.json(
      { error: 'SESSION_EXPIRED', message: 'Session expired. Please log in again.' },
      { status: 401 },
    )
    res.cookies.set(COOKIE_NAME, '', { httpOnly: true, path: '/', maxAge: 0 })
    return res
  }

  // Fallback: Authorization header (backward compatibility, no 2FA) —
  // prod-disabled unless ADMIN_ALLOW_BEARER=1 (M11), shared implementation.
  const { bearerAdminAuthorized } = await import('@/lib/auth/adminTokens')
  if (bearerAdminAuthorized(req.headers.get('Authorization'))) {
    return NextResponse.json({ status: 'ok', auth: 'bearer' })
  }

  return NextResponse.json(
    { error: 'UNAUTHORIZED', message: 'Not authenticated.' },
    { status: 401 },
  )
}
