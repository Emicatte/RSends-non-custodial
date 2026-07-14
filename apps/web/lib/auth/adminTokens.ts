import crypto from 'crypto'

// ── Token store (in-memory with TTL) ────────────────────────
// TODO: For multi-instance deployments, move token store to Redis

const TOKEN_TTL = 8 * 60 * 60 // 8 hours in seconds

// M11: `setupOnly` sessions come from a bootstrap (password-only) login when no
// ADMIN_TOTP_SECRET is configured. They may ONLY enroll TOTP via
// /api/admin/2fa/setup — never perform real admin actions. A full session is
// issued only after the second factor (TOTP) is verified.
const tokenStore = new Map<string, { expiresAt: number; setupOnly: boolean }>()

export function generateToken(setupOnly = false): string {
  const token = crypto.randomBytes(32).toString('hex')
  tokenStore.set(token, { expiresAt: Date.now() + TOKEN_TTL * 1000, setupOnly })
  return token
}

export function validateToken(token: string): boolean {
  const entry = tokenStore.get(token)
  if (!entry) return false
  if (entry.expiresAt < Date.now()) {
    tokenStore.delete(token)
    return false
  }
  return true
}

// Returns the session scope: 'full' (password + 2FA), 'setup' (bootstrap,
// TOTP-enrollment only), or null (invalid/expired).
export function getTokenScope(token: string): 'full' | 'setup' | null {
  const entry = tokenStore.get(token)
  if (!entry) return null
  if (entry.expiresAt < Date.now()) {
    tokenStore.delete(token)
    return null
  }
  return entry.setupOnly ? 'setup' : 'full'
}

export function revokeToken(token: string): void {
  tokenStore.delete(token)
}

export const TOKEN_TTL_SECONDS = TOKEN_TTL

// ── Bearer ADMIN_SECRET fallback (single implementation) ────
// The Bearer fallback is password-only (no 2FA), so it is disabled in
// production unless ADMIN_ALLOW_BEARER=1 is set explicitly (M11). Every
// admin surface must gate its Authorization-header path through this —
// a route with its own copy risks drifting (2fa/setup did).

function bearerAllowed(): boolean {
  return process.env.NODE_ENV !== 'production' || process.env.ADMIN_ALLOW_BEARER === '1'
}

export function bearerAdminAuthorized(authorizationHeader: string | null): boolean {
  if (!bearerAllowed()) return false
  const auth = authorizationHeader ?? ''
  const bearer = auth.startsWith('Bearer ') ? auth.slice(7) : ''
  const secret = process.env.ADMIN_SECRET || ''
  if (!secret || !bearer) return false
  const bearerBuf = Buffer.from(bearer)
  const secretBuf = Buffer.from(secret)
  return bearerBuf.length === secretBuf.length && crypto.timingSafeEqual(bearerBuf, secretBuf)
}
