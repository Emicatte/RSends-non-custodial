import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'
import { clientIpHeaders } from '@/lib/proxyClientIp'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

/** Replayed to the browser so the poll can honour the limit it just hit. */
const RATE_LIMIT_HEADERS = [
  'retry-after',
  'x-ratelimit-limit',
  'x-ratelimit-remaining',
  'x-ratelimit-reset',
] as const

/**
 * GET /api/pay/{intentId}
 *
 * Public proxy — no auth required.
 * Forwards to GET /api/v1/public/payment-intent/{intentId} on the backend:
 * the dedicated payer-facing endpoint (id-as-secret — anyone with the intent
 * link can view that one intent's limited, pay-relevant view). Per-IP rate
 * limited backend-side; merchant-private fields are never returned.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ intentId: string }> },
) {
  const { intentId } = await params

  if (!intentId || intentId.length < 8) {
    return NextResponse.json(
      { error: 'INVALID_INTENT_ID', message: 'Intent ID is missing or too short.' },
      { status: 400 },
    )
  }

  const backend = getBackendUrl()
  const url = `${backend}/api/v1/public/payment-intent/${encodeURIComponent(intentId)}`

  try {
    const res = await fetch(url, {
      cache: 'no-store',
      headers: clientIpHeaders(req),
    })

    const body = await res.json()

    // The body is re-encoded here, so backend headers are not copied wholesale
    // (content-length/encoding would no longer describe what we send). These
    // four are replayed explicitly: without Retry-After the checkout's poll has
    // nothing to back off by, and a client that cannot back off keeps the
    // bucket it is waiting on permanently full.
    const headers = new Headers()
    for (const h of RATE_LIMIT_HEADERS) {
      const v = res.headers.get(h)
      if (v) headers.set(h, v)
    }

    return NextResponse.json(body, { status: res.status, headers })
  } catch (err) {
    console.error('[pay proxy] Backend fetch failed:', err)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: 'Payment service is temporarily unavailable.' },
      { status: 502 },
    )
  }
}
