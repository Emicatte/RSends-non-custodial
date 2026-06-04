import { NextRequest, NextResponse } from 'next/server'
import crypto from 'crypto'
import { verifySync } from 'otplib'
import { generateToken, TOKEN_TTL_SECONDS } from '@/lib/auth/adminTokens'

// ── Config ──────────────────────────────────────────────────

const COOKIE_NAME = 'admin_session'

function getAdminSecret(): string {
  return process.env.ADMIN_SECRET || ''
}

// ── In-memory rate limiting ─────────────────────────────────

interface RateEntry {
  timestamps: number[]
  bannedUntil: number
}

const rateLimits = new Map<string, RateEntry>()
const RATE_WINDOW = 60_000       // 1 minute
const RATE_MAX = 5               // 5 attempts per minute
const BAN_WINDOW = 60 * 60_000   // 1 hour
const BAN_THRESHOLD = 10         // 10 failures in 1 hour → ban
const BAN_DURATION = 15 * 60_000 // 15 minutes

// Cleanup stale entries every 10 minutes
let lastCleanup = Date.now()
function cleanupRateLimits() {
  const now = Date.now()
  if (now - lastCleanup < 10 * 60_000) return
  lastCleanup = now
  for (const [ip, entry] of rateLimits.entries()) {
    const recent = entry.timestamps.filter(t => t > now - BAN_WINDOW)
    if (recent.length === 0 && entry.bannedUntil < now) {
      rateLimits.delete(ip)
    }
  }
}

function getClientIp(req: NextRequest): string {
  return (
    req.headers.get('x-real-ip') ||
    req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ||
    '127.0.0.1'
  )
}

function checkRateLimit(ip: string): { allowed: boolean; retryAfter?: number } {
  cleanupRateLimits()
  const now = Date.now()
  let entry = rateLimits.get(ip)
  if (!entry) {
    entry = { timestamps: [], bannedUntil: 0 }
    rateLimits.set(ip, entry)
  }

  // Check ban
  if (entry.bannedUntil > now) {
    return { allowed: false, retryAfter: Math.ceil((entry.bannedUntil - now) / 1000) }
  }

  // Check per-minute rate
  const recentMinute = entry.timestamps.filter(t => t > now - RATE_WINDOW)
  if (recentMinute.length >= RATE_MAX) {
    return { allowed: false, retryAfter: 60 }
  }

  return { allowed: true }
}

function recordFailure(ip: string): void {
  const now = Date.now()
  let entry = rateLimits.get(ip)
  if (!entry) {
    entry = { timestamps: [], bannedUntil: 0 }
    rateLimits.set(ip, entry)
  }
  entry.timestamps.push(now)

  // Check if ban threshold exceeded (failures in last hour)
  const recentHour = entry.timestamps.filter(t => t > now - BAN_WINDOW)
  entry.timestamps = recentHour // trim old entries
  if (recentHour.length >= BAN_THRESHOLD) {
    entry.bannedUntil = now + BAN_DURATION
  }
}

// ── POST /api/admin/login ───────────────────────────────────

export async function POST(req: NextRequest) {
  const secret = getAdminSecret()
  if (!secret) {
    return NextResponse.json(
      { error: 'ADMIN_NOT_CONFIGURED', message: 'ADMIN_SECRET is not set.' },
      { status: 503 },
    )
  }

  const ip = getClientIp(req)
  const rateCheck = checkRateLimit(ip)
  if (!rateCheck.allowed) {
    return NextResponse.json(
      { error: 'RATE_LIMIT_EXCEEDED', message: 'Too many login attempts. Try again later.', retry_after: rateCheck.retryAfter },
      { status: 429, headers: { 'Retry-After': String(rateCheck.retryAfter) } },
    )
  }

  let body: { password?: string; totp_code?: string }
  try {
    body = await req.json()
  } catch {
    return NextResponse.json(
      { error: 'BAD_REQUEST', message: 'Invalid JSON body.' },
      { status: 400 },
    )
  }

  const password = body.password?.trim()
  if (!password) {
    return NextResponse.json(
      { error: 'BAD_REQUEST', message: 'Password is required.' },
      { status: 400 },
    )
  }

  // Constant-time comparison to prevent timing attacks
  const passwordBuf = Buffer.from(password)
  const secretBuf = Buffer.from(secret)
  const isValid = passwordBuf.length === secretBuf.length && crypto.timingSafeEqual(passwordBuf, secretBuf)

  if (!isValid) {
    recordFailure(ip)
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Invalid credentials.' },
      { status: 401 },
    )
  }

  // ── TOTP 2FA ─────────────────────────────────────────────
  // If ADMIN_TOTP_SECRET is set, the second factor is enforced.
  // Otherwise we enter bootstrap mode: the response includes
  // requiresSetup=true so the frontend can redirect to the setup flow.
  const totpSecret = process.env.ADMIN_TOTP_SECRET || ''
  let requiresSetup = false
  if (totpSecret) {
    const totpCode = body.totp_code?.trim()
    if (!totpCode) {
      recordFailure(ip)
      return NextResponse.json(
        { error: 'MFA_REQUIRED', message: 'TOTP code is required.' },
        { status: 401 },
      )
    }
    const result = verifySync({ token: totpCode, secret: totpSecret })
    if (!result.valid) {
      recordFailure(ip)
      return NextResponse.json(
        { error: 'MFA_INVALID', message: 'Invalid TOTP code.' },
        { status: 401 },
      )
    }
  } else {
    requiresSetup = true
  }

  // Generate session token and set httpOnly cookie. In bootstrap mode
  // (requiresSetup) the session is SETUP-ONLY — it can only enroll TOTP, not
  // perform admin actions (M11). A full session needs the verified TOTP above.
  const token = generateToken(requiresSetup)
  const isSecure = process.env.NODE_ENV === 'production'

  const res = NextResponse.json({ status: 'ok', requiresSetup })
  res.cookies.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: isSecure,
    sameSite: 'strict',
    path: '/',
    maxAge: TOKEN_TTL_SECONDS,
  })

  return res
}
