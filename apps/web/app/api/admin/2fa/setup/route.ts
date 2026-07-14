import { NextRequest, NextResponse } from 'next/server'
import { generateSecret, generateURI } from 'otplib'
import QRCode from 'qrcode'

const COOKIE_NAME = 'admin_session'

async function isAuthorized(req: NextRequest): Promise<boolean> {
  // Same pattern as app/api/admin/transactions/route.ts. A setup-only
  // (bootstrap) session is accepted here on purpose — enrolling TOTP is the
  // one thing it exists for.
  const cookie = req.cookies.get(COOKIE_NAME)?.value
  if (cookie) {
    const { validateToken } = await import('@/lib/auth/adminTokens')
    return validateToken(cookie)
  }
  const { bearerAdminAuthorized } = await import('@/lib/auth/adminTokens')
  return bearerAdminAuthorized(req.headers.get('Authorization'))
}

// POST /api/admin/2fa/setup
// Protected: requires an existing admin_session (password-only login in
// bootstrap mode). Generates a fresh TOTP secret, returns it together
// with the otpauth:// URI and a base64 PNG QR code. The secret is NOT
// persisted server-side — the admin must store ADMIN_TOTP_SECRET in
// Vercel Secrets (or .env.local for dev) and redeploy for the
// subsequent login to require the TOTP code.
//
// TODO: encrypt at rest once we have a KMS-backed storage layer; for
// now the secret is base32 plaintext in the env var, which is the same
// trust model used for ADMIN_SECRET itself.
export async function POST(req: NextRequest) {
  if (!(await isAuthorized(req))) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Admin session required.' },
      { status: 401 },
    )
  }

  const secret = generateSecret() // base32, RFC 4648
  const otpauthUrl = generateURI({
    label: 'admin',
    issuer: 'RSends',
    secret,
  })
  // produces: otpauth://totp/RSends:admin?secret=...&issuer=RSends

  const qrDataUrl = await QRCode.toDataURL(otpauthUrl, {
    errorCorrectionLevel: 'M',
    margin: 1,
    width: 256,
  })

  return NextResponse.json({
    secret,
    otpauthUrl,
    qrDataUrl,
    instructions:
      `1) Scan the QR with an authenticator app (1Password, Authy, Google Authenticator). ` +
      `2) Set ADMIN_TOTP_SECRET=${secret} in Vercel Secrets (or .env.local for dev). ` +
      `3) Redeploy/restart so the next login requires the 6-digit code.`,
  })
}
