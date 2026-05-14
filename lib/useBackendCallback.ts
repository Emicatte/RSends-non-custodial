import { idempotencyKey, parseRSendError } from './rsendFetch'
import { logger } from './logger'

/**
 * Callback payload sent from the frontend to the Next.js server-side proxy.
 * The proxy computes the HMAC signature server-side and forwards to the Python backend.
 * The HMAC secret NEVER reaches the browser.
 */

interface CallbackPayload {
  txHash: string
  grossStr: string
  netStr: string
  feeStr: string
  symbol: string
  recipient?: string
  paymentRef?: string
  fiscalRef?: string
  eurValue?: string
  timestamp?: string
  isTestnet?: boolean
  complianceRecord?: {
    compliance_id: string
    block_timestamp: string
    fiat_rate?: number
    asset: string
    fiat_gross?: number
    ip_jurisdiction: string
    mica_applicable: boolean
    fiscal_ref: string
    network: string
  }
}

export function useBackendCallback() {
  return async (data: CallbackPayload) => {
    const ts = data.timestamp || new Date().toISOString()
    const grossAmount = parseFloat(data.grossStr)

    const payload = {
      fiscal_ref: data.fiscalRef || `RP-${Date.now()}`,
      payment_ref: data.paymentRef,
      tx_hash: data.txHash,
      gross_amount: grossAmount,
      net_amount: parseFloat(data.netStr),
      fee_amount: parseFloat(data.feeStr),
      currency: data.symbol,
      eur_value: data.eurValue ? parseFloat(data.eurValue) : undefined,
      network: data.isTestnet ? 'BASE_SEPOLIA' : 'BASE_MAINNET',
      is_testnet: data.isTestnet || false,
      recipient: data.recipient,
      status: 'completed',
      timestamp: ts,
      compliance_record: data.complianceRecord,
    }

    try {
      // Route through Next.js server-side proxy — HMAC computed server-side
      const res = await fetch('/api/tx/callback', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Idempotency-Key': idempotencyKey(),
        },
        body: JSON.stringify(payload),
      })
      // 409 Conflict is an idempotent-success condition, not an error.
      // The backend returns 409 when this tx_hash has already been processed
      // (Wave 2.1 UNIQUE constraint on payment_intents.matched_tx_hash, or
      // Wave 2.3 idempotency middleware hit). From the user's perspective the
      // transaction is already registered — treat it as success.
      if (res.status === 409) {
        logger.info('BackendCallback', 'TX already registered (idempotent)', {
          fiscalRef: String(payload.fiscal_ref),
          txHash: String(payload.tx_hash),
        })
        return { success: true, data: { status: 'already_processed' } }
      }

      if (!res.ok) {
        const errMsg = await parseRSendError(res)
        logger.error('BackendCallback', 'Callback failed', { status: String(res.status), error: errMsg })
        return { success: false, error: errMsg }
      }
      const result = await res.json()
      logger.debug('BackendCallback', 'TX logged', { fiscalRef: String(payload.fiscal_ref) })
      return { success: true, data: result }
    } catch (err) {
      logger.error('BackendCallback', 'Network error', { error: String(err) })
      return { success: false, error: err }
    }
  }
}

