/**
 * useBackendCallback.ts (DOCS / EXAMPLE)
 *
 * Hook esempio per inviare i dati di TransactionStatus.tsx al backend RPagos
 * via il proxy server-side `app/api/tx/callback/route.ts`.
 *
 * Pattern attuale (sicuro):
 *   - Il browser NON conosce mai HMAC_SECRET.
 *   - Il client invia il payload in chiaro a `/api/tx/callback` (Next.js API route).
 *   - Il proxy server-side legge `HMAC_SECRET` da env var (server-only) e firma
 *     il payload prima di inoltrarlo al backend Python.
 *
 * NON usare più `NEXT_PUBLIC_HMAC_SECRET` né calcolare HMAC nel browser:
 * qualsiasi NEXT_PUBLIC_* viene compilata nel bundle JS lato client.
 *
 * Esempio d'uso:
 *
 *   const sendCallback = useBackendCallback()
 *
 *   useEffect(() => {
 *     if (phase === 'done' && txHash) {
 *       sendCallback({
 *         txHash, grossStr, netStr, feeStr, symbol,
 *         recipient, paymentRef, fiscalRef, eurValue,
 *         timestamp, complianceRecord, isTestnet,
 *       })
 *     }
 *   }, [phase])
 */

// ── Tipo del payload (corrisponde al backend) ────────────────
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

// ── Hook ─────────────────────────────────────────────────────
export function useBackendCallback() {
  return async (data: CallbackPayload) => {
    const ts = data.timestamp || new Date().toISOString()

    // Mappa i nomi del frontend → backend.
    // Niente x_signature qui: lo aggiunge il proxy server-side.
    const payload = {
      fiscal_ref: data.fiscalRef || `RP-${Date.now()}`,
      payment_ref: data.paymentRef,
      tx_hash: data.txHash,
      gross_amount: parseFloat(data.grossStr),
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
      // POST al proxy Next.js — same-origin, nessun secret nel browser.
      const res = await fetch('/api/tx/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const err = await res.json()
        console.error('[RPagos Backend] Callback failed:', err)
        return { success: false, error: err }
      }

      const result = await res.json()
      console.log('[RPagos Backend] TX logged:', result)
      return { success: true, data: result }
    } catch (err) {
      console.error('[RPagos Backend] Network error:', err)
      return { success: false, error: err }
    }
  }
}
