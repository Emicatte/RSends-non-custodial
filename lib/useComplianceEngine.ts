/**
 * useComplianceEngine.ts — MiCA Compliance Module
 *
 * Genera report fiscali real-time per ogni transazione:
 * - Timestamp certificato (ISO 8601 + unix)
 * - Riferimento fiscale
 * - Tasso di cambio al blocco (CoinGecko)
 * - Geolocation IP → giurisdizione UE
 * - Hash di conformità SHA-256
 * - Persistenza in localStorage (mock DB)
 * - Export CSV/JSON per reporting fiscale
 */

import { useCallback } from 'react'
import { formatUnits } from 'viem'

export const COMPLIANCE_DB_KEY = 'rp_compliance_db'

// ── Tipi ───────────────────────────────────────────────────────────────────
export interface ComplianceRecord {
  // Identificatori
  compliance_id:     string   // SHA-256 dei dati chiave
  tx_hash:           string
  block_timestamp:   string   // ISO 8601
  block_timestamp_ts: number  // unix

  // Parti
  sender_address:    string
  recipient_address: string

  // Asset
  asset:             string
  gross_amount:      string
  net_amount:        string
  fee_amount:        string

  // Fiat
  fiat_currency:     'EUR'
  fiat_rate:         number | null    // tasso al blocco
  fiat_gross:        string | null    // importo in EUR
  fiat_fee:          string | null    // fee in EUR

  payment_ref:       string
  fiscal_ref:        string

  // Giurisdizione
  ip_jurisdiction:   string   // es. 'IT', 'DE', 'EU_UNKNOWN'
  mica_applicable:   boolean  // true se nell'UE

  // Rete
  network:           'BASE' | 'BASE_SEPOLIA'
  chain_id:          number

  // Integrità
  x_signature:       string   // HMAC placeholder
  created_at:        string
}

// ── Geolocation IP → giurisdizione ────────────────────────────────────────
async function detectJurisdiction(): Promise<{ country: string; mica: boolean }> {
  try {
    const res  = await fetch('https://ipapi.co/json/')
    const data = await res.json()
    const country = data?.country_code ?? 'UNKNOWN'
    const euCountries = ['AT','BE','BG','CY','CZ','DE','DK','EE','ES','FI','FR','GR','HR','HU','IE','IT','LT','LU','LV','MT','NL','PL','PT','RO','SE','SI','SK']
    return { country, mica: euCountries.includes(country) }
  } catch {
    return { country: 'EU_UNKNOWN', mica: true } // default conservativo
  }
}

// ── Rate di cambio al blocco ───────────────────────────────────────────────
async function fetchFiatRate(symbol: string): Promise<number | null> {
  try {
    const id = symbol === 'ETH' ? 'ethereum' : symbol === 'USDC' ? 'usd-coin'
      : symbol === 'DEGEN' ? 'degen-base' : symbol === 'cbBTC' ? 'coinbase-wrapped-btc' : null
    if (!id) return null
    const res  = await fetch(`/api/market/simple/price?ids=${id}&vs_currencies=eur`)
    const data = await res.json()
    return data?.[id]?.eur ?? null
  } catch { return null }
}

// ── Hash di conformità (SHA-256 via Web Crypto) ────────────────────────────
async function generateComplianceHash(data: string): Promise<string> {
  try {
    const encoder = new TextEncoder()
    const encoded = encoder.encode(data)
    const buffer  = await crypto.subtle.digest('SHA-256', encoded.buffer as ArrayBuffer)
    const arr     = Array.from(new Uint8Array(buffer))
    return arr.map(b => b.toString(16).padStart(2, '0')).join('')
  } catch {
    return 'HASH_UNAVAILABLE_' + Date.now()
  }
}

// ── Hook principale ────────────────────────────────────────────────────────
export function useComplianceEngine() {

  const generateRecord = useCallback(async (params: {
    txHash:     string
    sender:     string
    recipient:  string
    gross:      bigint
    net:        bigint
    fee:        bigint
    decimals:   number
    symbol:     string
    paymentRef: string
    fiscalRef:  string
    chainId:    number
    isTestnet:  boolean
  }): Promise<ComplianceRecord> => {

    const now      = new Date()
    const isoNow   = now.toISOString()
    const tsNow    = Math.floor(now.getTime() / 1000)
    const fmtAmt   = (n: bigint) => parseFloat(formatUnits(n, params.decimals)).toFixed(params.decimals)
    const grossStr = fmtAmt(params.gross)
    const netStr   = fmtAmt(params.net)
    const feeStr   = fmtAmt(params.fee)

    // Fetch paralleli
    const [jurisdiction, fiatRate] = await Promise.all([
      detectJurisdiction(),
      fetchFiatRate(params.symbol),
    ])

    // Calcolo fiat
    const grossNum  = parseFloat(grossStr)
    const feeNum    = parseFloat(feeStr)
    const fiatGross = fiatRate ? (grossNum * fiatRate).toFixed(2) : null
    const fiatFee   = fiatRate ? (feeNum   * fiatRate).toFixed(2) : null

    // Hash di conformità
    const hashInput = [params.txHash, params.sender, params.recipient, grossStr, params.symbol, isoNow].join('|')
    const complianceId = await generateComplianceHash(hashInput)

    const record: ComplianceRecord = {
      compliance_id:      complianceId,
      tx_hash:            params.txHash,
      block_timestamp:    isoNow,
      block_timestamp_ts: tsNow,
      sender_address:     params.sender,
      recipient_address:  params.recipient,
      asset:              params.symbol,
      gross_amount:       grossStr,
      net_amount:         netStr,
      fee_amount:         feeStr,
      fiat_currency:      'EUR',
      fiat_rate:          fiatRate,
      fiat_gross:         fiatGross,
      fiat_fee:           fiatFee,
      payment_ref:        params.paymentRef || '—',
      fiscal_ref:         params.fiscalRef  || '—',
      ip_jurisdiction:    jurisdiction.country,
      mica_applicable:    jurisdiction.mica,
      network:            params.isTestnet ? 'BASE_SEPOLIA' : 'BASE',
      chain_id:           params.chainId,
      x_signature:        'PENDING_SERVER_SIDE_HMAC_SHA256',
      created_at:         isoNow,
    }

    // Persist in localStorage (mock DB)
    persistRecord(record)

    return record
  }, [])

  return { generateRecord, getHistory, exportCsv, exportJson, clearHistory }
}

// ── Persistence helpers ────────────────────────────────────────────────────
function persistRecord(record: ComplianceRecord) {
  try {
    const raw      = localStorage.getItem(COMPLIANCE_DB_KEY)
    const db: ComplianceRecord[] = raw ? JSON.parse(raw) : []
    db.push(record)
    if (db.length > 500) db.splice(0, db.length - 500)
    localStorage.setItem(COMPLIANCE_DB_KEY, JSON.stringify(db))
  } catch { /* SSR */ }
}

export function getHistory(): ComplianceRecord[] {
  try {
    const raw = localStorage.getItem(COMPLIANCE_DB_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

export function exportJson(): string {
  return JSON.stringify(getHistory(), null, 2)
}

export function exportCsv(): string {
  const records = getHistory()
  if (!records.length) return ''
  const headers = Object.keys(records[0]).join(',')
  const rows    = records.map(r => Object.values(r).map(v => `"${v}"`).join(','))
  return [headers, ...rows].join('\n')
}

export function clearHistory() {
  try { localStorage.removeItem(COMPLIANCE_DB_KEY) } catch { /* SSR */ }
}
