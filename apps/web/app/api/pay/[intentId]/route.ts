import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

/**
 * GET /api/pay/{intentId}
 *
 * Public proxy — no auth required.
 * Forwards to GET /api/v1/merchant/payment-intent/{intentId} on the backend.
 *
 * The backend enforces merchant ownership via API key, but this checkout
 * endpoint is public: anyone with the intent link can view payment status.
 * We pass a special header to signal "public checkout" to the backend.
 */
export async function GET(
  _req: NextRequest,
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
  const url = `${backend}/api/v1/merchant/payment-intent/${encodeURIComponent(intentId)}`

  try {
    const res = await fetch(url, {
      headers: { 'X-Checkout-Public': '1' },
      cache: 'no-store',
    })

    const body = await res.json()
    return NextResponse.json(body, { status: res.status })
  } catch (err) {
    console.error('[pay proxy] Backend fetch failed:', err)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: 'Payment service is temporarily unavailable.' },
      { status: 502 },
    )
  }
}
