import { NextRequest, NextResponse } from 'next/server'
import { createHmac } from 'crypto'

/**
 * POST /api/tx/callback — Server-side HMAC proxy.
 *
 * The frontend sends the callback payload HERE (no secret needed client-side).
 * This route:
 *  1. Reads HMAC_SECRET from server-only env var
 *  2. Computes HMAC-SHA256 over the canonical message
 *  3. Forwards the signed payload to the Python backend
 *
 * The HMAC secret NEVER leaves the server.
 *
 * ── Field contract ──────────────────────────────────────────────────────────
 *
 * Frontend (useBackendCallback.ts) sends:
 *   fiscal_ref, tx_hash, gross_amount, net_amount, fee_amount,
 *   currency, eur_value?, network, is_testnet, recipient, status,
 *   timestamp, compliance_record?: { compliance_id, block_timestamp,
 *   fiat_rate?, asset, fiat_gross?, ip_jurisdiction, mica_applicable,
 *   fiscal_ref, network }
 *
 * rpagos-backend (routes.py + schemas.py) expects:
 *   All of the above + x_signature (body field, pipe-separated HMAC)
 *   compliance_record as nested Pydantic model
 *
 * compliance_oracle.py expects:
 *   X-Signature header (HMAC-SHA256 of full body)
 *   compliance_id at root level
 *   merchant_transaction_id at root level (= tx_hash)
 */

function getSecret() {
  return process.env.HMAC_SECRET || ''
}

function getBackendUrl() {
  return process.env.RPAGOS_BACKEND_URL || process.env.NEXT_PUBLIC_RPAGOS_BACKEND_URL || 'http://localhost:8000'
}

function computeHmac(message: string): string {
  return createHmac('sha256', getSecret()).update(message).digest('hex')
}

/**
 * Normalize timestamp to match Python datetime.isoformat() output.
 * JS:     "2026-04-09T14:30:00.123Z"
 * Python: "2026-04-09T14:30:00.123000+00:00"
 *
 * Pydantic parses the ISO string → datetime, then routes.py calls .isoformat()
 * which always outputs +HH:MM timezone and pads microseconds to 6 digits.
 */
function normalizeTsForPython(ts: string): string {
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  // Python isoformat(): YYYY-MM-DDTHH:MM:SS.ffffff+00:00
  const iso = d.toISOString()                     // "2026-04-09T14:30:00.123Z"
  const noZ = iso.replace('Z', '')                // "2026-04-09T14:30:00.123"
  const [sec, ms] = noZ.split('.')
  const microseconds = (ms || '0').padEnd(6, '0') // "123" → "123000"
  return `${sec}.${microseconds}+00:00`
}

/**
 * Normalize gross_amount to match Python str(float(x)) output.
 * JS may send 10 (integer) but Python str(float(10)) → "10.0"
 */
function normalizeAmountForPython(v: string | number): string {
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (isNaN(n)) return String(v)
  // Python str(float(x)): always has decimal point
  const s = String(n)
  return s.includes('.') ? s : s + '.0'
}

export async function POST(req: NextRequest) {
  const HMAC_SECRET = getSecret()
  const BACKEND_URL = getBackendUrl()

  const isDev = process.env.NODE_ENV !== 'production'
    && process.env.VERCEL_ENV !== 'production'

  console.log('[tx/callback] NODE_ENV:', process.env.NODE_ENV, 'HMAC:', HMAC_SECRET ? 'SET' : 'EMPTY')

  if (!HMAC_SECRET && process.env.NODE_ENV === 'production') {
    // Produzione: HMAC obbligatorio
    return NextResponse.json(
      { error: 'HMAC_NOT_CONFIGURED', message: 'Server HMAC_SECRET is not set.' },
      { status: 503 },
    )
  }

  if (!HMAC_SECRET && isDev) {
    console.warn('[rp_proxy] ⚠ HMAC_SECRET not set — running in dev mode without signature verification')
  }

  let body: Record<string, unknown>
  try {
    body = await req.json()
  } catch {
    return NextResponse.json(
      { error: 'INVALID_JSON', message: 'Request body is not valid JSON.' },
      { status: 400 },
    )
  }

  const {
    fiscal_ref, tx_hash, gross_amount, currency, timestamp,
  } = body as Record<string, string | number>

  if (!fiscal_ref || !tx_hash || gross_amount == null || !currency || !timestamp) {
    return NextResponse.json(
      { error: 'MISSING_FIELDS', message: 'fiscal_ref, tx_hash, gross_amount, currency, timestamp are required.' },
      { status: 400 },
    )
  }

  // Normalize values to match Python's str(float(x)) and datetime.isoformat()
  const normAmount = normalizeAmountForPython(gross_amount)
  const normTs     = normalizeTsForPython(String(timestamp))

  // Canonical pipe-separated message — matches rpagos-backend hmac_service.py
  // Backend: f"{fiscal_ref}|{tx_hash}|{str(payload.gross_amount)}|{currency}|{payload.timestamp.isoformat()}"
  const canonicalMsg = `${fiscal_ref}|${tx_hash}|${normAmount}|${currency}|${normTs}`
  const signature = HMAC_SECRET
    ? computeHmac(canonicalMsg)
    : 'PENDING_HMAC_SHA256'

  // Full spread of frontend body + x_signature in body (backend reads it from body)
  const payload = { ...body, x_signature: signature }

  const payloadStr = JSON.stringify(payload)

  // Forward idempotency key from client if present
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const idempKey = req.headers.get('X-Idempotency-Key')
  if (idempKey) headers['X-Idempotency-Key'] = idempKey

  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/v1/tx/callback`, {
      method: 'POST',
      headers,
      body: payloadStr,
      signal: AbortSignal.timeout(8000),
    })

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


