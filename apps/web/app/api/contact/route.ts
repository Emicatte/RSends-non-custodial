import { NextRequest, NextResponse } from 'next/server'
import { checkRateLimit, getClientIp } from '@/lib/rateLimit'

export const maxDuration = 30

/**
 * Contact form endpoint — delivers "Talk to us" submissions to the inbox via
 * Resend. Runs fully standalone on Vercel (no FastAPI/Render dependency).
 *
 * Three server-side bot-protection layers gate every send, in strict order:
 *   1. Honeypot   — hidden field real users never fill; if set, drop silently.
 *   2. Validation — required fields, email shape, length bounds.
 *   3. Rate limit — per-IP, best-effort in-memory (lib/rateLimit).
 *   4. Turnstile  — Cloudflare token verified against siteverify with the
 *                   server-only secret BEFORE sending. Never trust the browser.
 * Only if all gates pass do we call Resend. Secrets come from env, never code.
 */

const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
const RESEND_URL = 'https://api.resend.com/emails'
const SUBJECT = 'RSends — richiesta di contatto'

// Simple, pragmatic email shape check (server-authoritative; the form also checks).
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

interface ContactFields {
  name: string
  surname: string
  company: string
  email: string
  message: string
}

function err(error: string, message: string, status: number, extra?: Record<string, unknown>) {
  return NextResponse.json({ error, message, ...extra }, { status })
}

function str(v: unknown): string {
  return typeof v === 'string' ? v.trim() : ''
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: Record<string, unknown>
  try {
    body = (await req.json()) as Record<string, unknown>
  } catch {
    return err('INVALID_REQUEST', 'Malformed request body.', 400)
  }

  // 1. Honeypot — a hidden field. If a bot filled it, pretend success and drop.
  if (str(body['company_website']).length > 0) {
    return NextResponse.json({ ok: true })
  }

  // 2. Server-side validation.
  const fields: ContactFields = {
    name: str(body['name']),
    surname: str(body['surname']),
    company: str(body['company']),
    email: str(body['email']),
    message: str(body['message']),
  }
  const invalid =
    !fields.name ||
    !fields.surname ||
    !fields.email ||
    !fields.message ||
    !EMAIL_RE.test(fields.email) ||
    fields.name.length > 100 ||
    fields.surname.length > 100 ||
    fields.company.length > 100 ||
    fields.email.length > 200 ||
    fields.message.length > 5000
  if (invalid) {
    return err('VALIDATION_FAILED', 'Please check the form fields and try again.', 422)
  }

  // 3. Per-IP rate limit (best-effort, in-memory): 5 requests / 10 min.
  const ip = getClientIp(req)
  const rl = checkRateLimit(ip, { max: 5, windowMs: 10 * 60_000, key: 'contact' })
  if (!rl.allowed) {
    return err(
      'RATE_LIMIT_EXCEEDED',
      'Too many requests. Please try again later.',
      429,
      { retry_after: rl.retryAfter },
    )
  }

  // 4. Verify Turnstile server-side (mirror app/api/auth/signup/route.ts).
  const secret = process.env.TURNSTILE_SECRET_KEY
  if (!secret) {
    // Fail closed: never send if the captcha can't be verified.
    return err('TURNSTILE_UNCONFIGURED', 'Captcha is not configured.', 500)
  }
  const token = str(body['turnstile_token'])
  if (!token) {
    return err('TURNSTILE_FAILED', 'Captcha required.', 422)
  }
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
    if (verdict.success !== true) {
      return err('TURNSTILE_FAILED', 'Captcha verification failed.', 422)
    }
  } catch {
    return err('TURNSTILE_FAILED', 'Captcha verification error.', 422)
  }

  // 5. Send via Resend REST API (no SDK dependency).
  const apiKey = process.env.RESEND_API_KEY
  const from = process.env.RESEND_FROM
  const to = process.env.CONTACT_TO
  if (!apiKey || !from || !to) {
    console.error('[contact] Resend not configured (RESEND_API_KEY/RESEND_FROM/CONTACT_TO)')
    return err('EMAIL_SEND_FAILED', 'Email delivery is not configured.', 500)
  }

  const who = fields.company ? `${fields.name} ${fields.surname} (${fields.company})` : `${fields.name} ${fields.surname}`
  const text =
    `Nuova richiesta di contatto — RSends\n\n` +
    `Nome:    ${fields.name} ${fields.surname}\n` +
    `Azienda: ${fields.company || '—'}\n` +
    `Email:   ${fields.email}\n\n` +
    `Messaggio:\n${fields.message}\n`
  const html =
    `<h2>Nuova richiesta di contatto — RSends</h2>` +
    `<p><strong>Nome:</strong> ${escapeHtml(fields.name)} ${escapeHtml(fields.surname)}<br/>` +
    `<strong>Azienda:</strong> ${escapeHtml(fields.company) || '—'}<br/>` +
    `<strong>Email:</strong> ${escapeHtml(fields.email)}</p>` +
    `<p><strong>Messaggio:</strong></p>` +
    `<p style="white-space:pre-wrap">${escapeHtml(fields.message)}</p>`

  try {
    const res = await fetch(RESEND_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({
        from,
        to: [to],
        reply_to: fields.email,
        subject: `${SUBJECT} — ${who}`,
        text,
        html,
      }),
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      console.error(`[contact] Resend send failed (${res.status}):`, detail)
      return err('EMAIL_SEND_FAILED', 'Could not send your message. Please try again.', 502)
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    console.error('[contact] Resend unreachable:', msg)
    return err('EMAIL_SEND_FAILED', 'Could not send your message. Please try again.', 502)
  }

  return NextResponse.json({ ok: true })
}
