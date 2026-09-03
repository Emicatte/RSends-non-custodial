import { NextRequest, NextResponse } from 'next/server'
import { requireEnv } from '@/lib/env'

function getBackendUrl() {
  return requireEnv('RPAGOS_BACKEND_URL')
}

/** TRON txids are 64 hex characters, unprefixed — no `0x`, unlike EVM. */
const TX_HASH_RE = /^[0-9a-fA-F]{64}$/

/**
 * POST /api/pay/{intentId}/tx-hint
 *
 * The payer's wallet has broadcast a TRC-20 transfer and this is the hash. It
 * is a HINT, never proof: the backend's poller and matcher remain the only
 * things that can mark an intent paid, and the checkout learns the outcome by
 * polling the public view exactly as before. Submitting a hash that does not
 * verify leaves the intent precisely as matchable as it was.
 *
 * Which is why this endpoint is allowed to fail without anyone noticing. Until
 * migration 0023 and the backend route land it returns 404 or 502, and the
 * payment flow is unaffected — the transfer is already on chain, and the poller
 * will find it by scanning the merchant's address as it does today. The hint
 * only lets the backend close the intent from the transaction it was told about
 * rather than the one it happened to observe.
 *
 * Nothing here is trusted. The body carries a hash and the payer's address and
 * nothing else — no recipient, no amount, no token, no chain — so there is no
 * field a caller could use to redirect a payment. The backend re-derives every
 * one of those from the intent and verifies them on chain.
 */
export async function POST(
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

  let body: unknown
  try {
    body = await req.json()
  } catch {
    return NextResponse.json(
      { error: 'INVALID_BODY', message: 'Expected a JSON body.' },
      { status: 400 },
    )
  }

  const { tx_hash: txHash, payer_address: payerAddress } =
    (body ?? {}) as { tx_hash?: unknown; payer_address?: unknown }

  if (typeof txHash !== 'string' || !TX_HASH_RE.test(txHash)) {
    return NextResponse.json(
      { error: 'INVALID_TX_HASH', message: 'Expected a 64-character hex transaction id.' },
      { status: 400 },
    )
  }

  const backend = getBackendUrl()
  const url = `${backend}/api/v1/public/payment-intent/${encodeURIComponent(intentId)}/tx-hint`

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      cache: 'no-store',
      // Forwarded as an allowlist rather than by passing the body through, so a
      // field added to the client can never reach the backend unreviewed.
      body: JSON.stringify({
        tx_hash: txHash.toLowerCase(),
        // base58check is case-sensitive: never folded, only omitted if absent.
        ...(typeof payerAddress === 'string' && payerAddress
          ? { payer_address: payerAddress }
          : {}),
      }),
    })

    const payload = await res.json().catch(() => ({}))
    return NextResponse.json(payload, { status: res.status })
  } catch (err) {
    console.error('[pay tx-hint proxy] Backend post failed:', err)
    return NextResponse.json(
      { error: 'BACKEND_UNREACHABLE', message: 'Payment service is temporarily unavailable.' },
      { status: 502 },
    )
  }
}
