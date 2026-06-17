import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

export const maxDuration = 30

/**
 * Signup entry point with server-side Cloudflare Turnstile verification.
 *
 * The Turnstile SECRET lives only on the server (TURNSTILE_SECRET_KEY in env),
 * so verification happens here — BEFORE the request reaches the FastAPI signup
 * endpoint and before any user is created. On a failed/absent token we return
 * 422 {detail:{code:"turnstile_failed"}} (shape the frontend already handles).
 * On success we strip the token and forward the rest to the backend, relaying
 * its status/body (and any Set-Cookie, though signup sets none).
 */

const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

function clientIp(req: NextRequest): string {
  const xff = req.headers.get('x-forwarded-for')
  if (xff) return xff.split(',')[0].trim()
  return req.headers.get('x-real-ip') ?? ''
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: Record<string, unknown>
  try {
    body = (await req.json()) as Record<string, unknown>
  } catch {
    return NextResponse.json({ detail: { code: 'invalid_request' } }, { status: 400 })
  }

  const secret = process.env.TURNSTILE_SECRET_KEY
  if (!secret) {
    // Fail closed: never create a user if the captcha can't be verified.
    return NextResponse.json(
      { detail: { code: 'turnstile_unconfigured', message: 'Captcha is not configured.' } },
      { status: 500 },
    )
  }

  const token = body['turnstile_token']
  if (typeof token !== 'string' || token.length === 0) {
    return NextResponse.json(
      { detail: { code: 'turnstile_failed', message: 'Captcha required.' } },
      { status: 422 },
    )
  }

  const ip = clientIp(req)
  try {
    const form = new URLSearchParams()
    form.set('secret', secret)
    form.set('response', token)
    if (ip) form.set('remoteip', ip)
    const vr = await fetch(SITEVERIFY_URL, {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(10000),
    })
    const verdict = (await vr.json().catch(() => ({ success: false }))) as { success?: boolean }
    if (!verdict.success) {
      return NextResponse.json(
        { detail: { code: 'turnstile_failed', message: 'Captcha verification failed.' } },
        { status: 422 },
      )
    }
  } catch {
    return NextResponse.json(
      { detail: { code: 'turnstile_failed', message: 'Captcha verification error.' } },
      { status: 422 },
    )
  }

  // Strip the captcha token; forward the rest to the FastAPI signup endpoint.
  const { turnstile_token: _omit, ...forward } = body
  const backend = requireEnv('RPAGOS_BACKEND_URL')
  try {
    const res = await fetch(`${backend}/api/v1/auth/signup`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(forward),
      cache: 'no-store',
      signal: AbortSignal.timeout(25000),
    })
    const data = await res.text()
    return new NextResponse(data, {
      status: res.status,
      headers: { 'Content-Type': res.headers.get('content-type') || 'application/json' },
    })
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[auth/signup] backend unreachable:', msg)
    return NextResponse.json({ error: 'BACKEND_UNREACHABLE', message: msg }, { status: 502 })
  }
}
