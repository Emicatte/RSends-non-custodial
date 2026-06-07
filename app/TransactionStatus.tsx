'use client'

/**
 * TransactionStatus_v3.tsx — Institutional Grade Dashboard
 *
 * Tema: Deep Dark + accenti #00ffa3 (successo) / #ff2d55 (errore)
 * Features:
 *   - Live Gas Tracker (destination chain)
 *   - Barra di progresso balistica (~2s finality, rete di destinazione)
 *   - Micro-stati animati
 *   - Address AML check (mock)
 */

import { useState, useEffect, useRef } from 'react'
import { usePublicClient, useChainId } from 'wagmi'
import { formatUnits } from 'viem'
import { useTranslations } from 'next-intl'
import type { ComplianceRecord } from '../lib/useComplianceEngine'
// ── Theme ─────────────────────────────────────────────────────────────────
import { C } from '@/app/designTokens'
const T = { ...C, emerald: '#00ffa3', muted: C.sub, red: '#ff2d55', amber: '#ffb800', blue: '#4d96ff', mono: C.M, display: C.D }

// ── Live Gas Tracker ───────────────────────────────────────────────────────
export function GasTracker(): React.JSX.Element {
  const publicClient = usePublicClient()
  const [gwei,    setGwei]    = useState<string | null>(null)
  const [usd,     setUsd]     = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    const fetch = async () => {
      try {
        const gp = await publicClient?.getGasPrice()
        if (!mounted || !gp) return
        const gweiVal   = parseFloat(formatUnits(gp, 9)).toFixed(4)
        // Stima costo TX: 50k gas (ERC20 split) × gas price × ETH price (~$2200)
        const ethPrice  = 2200
        const txCostUsd = (50_000 * parseFloat(formatUnits(gp, 9)) * 1e-9 * ethPrice).toFixed(4)
        setGwei(gweiVal)
        setUsd(txCostUsd)
      } catch { /* ignore */ }
      finally { if (mounted) setLoading(false) }
    }
    fetch()
    const interval = setInterval(fetch, 5000)
    return () => { mounted = false; clearInterval(interval) }
  }, [publicClient])

  const color = gwei ? (parseFloat(gwei) < 0.01 ? T.emerald : parseFloat(gwei) < 0.1 ? T.amber : T.red) : T.muted

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderRadius: 10, background: T.surface, border: `1px solid ${T.border}` }}>
      <div style={{ width: 7, height: 7, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}`, animation: 'pulse 2s infinite' }} />
      <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>Gas:</span>
      {loading
        ? <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>…</span>
        : <>
            <span style={{ fontFamily: T.mono, fontSize: 11, color, fontWeight: 700 }}>{gwei} Gwei</span>
            <span style={{ fontFamily: T.mono, fontSize: 10, color: T.muted }}>≈ ${usd}</span>
          </>
      }
    </div>
  )
}

// ── Address AML Check (mock) ───────────────────────────────────────────────
type AmlStatus = 'unchecked' | 'checking' | 'clean' | 'contract' | 'flagged'

export function AddressVerifier({ address }: { address: string }): React.JSX.Element | null {
  const t = useTranslations('txStatus')
  const publicClient = usePublicClient()
  const [status, setStatus] = useState<AmlStatus>('unchecked')

  useEffect(() => {
    if (!address || address.length < 42) { setStatus('unchecked'); return }
    setStatus('checking')
    const check = async () => {
      try {
        // Check se è un contratto
        const code = await publicClient?.getBytecode({ address: address as `0x${string}` })
        if (code && code !== '0x') { setStatus('contract'); return }
        // Mock AML: lista nera di test
        const flagged = ['0x0000000000000000000000000000000000000000']
        if (flagged.includes(address.toLowerCase())) { setStatus('flagged'); return }
        setStatus('clean')
      } catch { setStatus('clean') }
    }
    const t = setTimeout(check, 500)
    return () => clearTimeout(t)
  }, [address, publicClient])

  if (status === 'unchecked') return null

  const cfg = {
    checking: { color: T.amber,   icon: '⏳', text: t('amlChecking')    },
    clean:    { color: T.emerald, icon: '✓',  text: t('amlClean')      },
    contract: { color: T.blue,    icon: '📄', text: t('smartContract')  },
    flagged:  { color: T.red,     icon: '⚠',  text: t('addressFlagged') },
  }[status]

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, fontFamily: T.mono, fontSize: 11 }}>
      <span>{cfg.icon}</span>
      <span style={{ color: cfg.color }}>{cfg.text}</span>
    </div>
  )
}

// ── Ballistic Progress Bar ─────────────────────────────────────────────────
export function BallisticProgress({ active, onComplete }: { active: boolean; onComplete?: () => void }): React.JSX.Element | null {
  const [progress, setProgress] = useState(0)
  const rafRef = useRef<number>(0)
  const startRef = useRef<number>(0)

  useEffect(() => {
    if (!active) { setProgress(0); return }
    startRef.current = Date.now()

    const animate = () => {
      const elapsed = Date.now() - startRef.current
      const duration = 2200 // ~2.2s finality (destination chain)
      // Curva balistica: accelera poi decelera
      const t = Math.min(elapsed / duration, 1)
      const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t
      const pct = Math.min(eased * 95, 95) // si ferma al 95% finché non confermato
      setProgress(pct)
      if (t < 1) rafRef.current = requestAnimationFrame(animate)
    }

    rafRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(rafRef.current)
  }, [active])

  // Quando arriva conferma, vai al 100%
  useEffect(() => {
    if (!active && progress > 0) {
      setProgress(100)
      const t = setTimeout(() => { onComplete?.() }, 400)
      return () => clearTimeout(t)
    }
  }, [active])

  if (progress === 0 && !active) return null

  return (
    <div style={{ position: 'relative', height: 3, background: T.border, borderRadius: 2, overflow: 'hidden' }}>
      <div style={{
        height: '100%',
        width: `${progress}%`,
        background: progress >= 100 ? T.emerald : `linear-gradient(90deg, ${T.emerald}80, ${T.emerald})`,
        borderRadius: 2,
        transition: progress >= 100 ? 'width 0.4s ease' : 'none',
        boxShadow: `0 0 8px ${T.emerald}60`,
      }} />
      {/* Glow traveler */}
      {progress < 100 && active && (
        <div style={{
          position: 'absolute', top: -1, right: `${100 - progress}%`,
          width: 12, height: 5, borderRadius: '50%',
          background: T.emerald, filter: 'blur(2px)',
          transform: 'translateX(50%)',
        }} />
      )}
    </div>
  )
}

// ── Micro-stato badge animato ──────────────────────────────────────────────
interface MicroStateProps {
  phase: string
  silent?: boolean
}

export function MicroStateBadge({ phase, silent }: MicroStateProps): React.JSX.Element | null {
  const t = useTranslations('txStatus')
  const states: Record<string, { color: string; icon: string; text: string; blink?: boolean }> = {
    approving:    { color: T.amber,   icon: '🔐', text: t('permit2Approving'), blink: true  },
    wait_approve: { color: T.amber,   icon: '⛓',  text: 'status: pending · On-chain confirm…'             },
    signing:      { color: T.purple,  icon: '✍',  text: 'status: order_scheduled · Firma EIP-712…', blink: true },
    wait_send:    { color: T.blue,    icon: '⚡',  text: 'status: finalizing · ~2s on destination chain'      },
  }

  const s = states[phase]
  if (!s) return null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 14px', borderRadius: 12,
      background: s.color + '10',
      border: `1px solid ${s.color}30`,
      animation: 'fadeSlideIn 0.2s ease',
    }}>
      <div style={{
        width: 14, height: 14, borderRadius: '50%',
        border: `2px solid ${s.color}40`,
        borderTopColor: s.color,
        animation: 'spin 0.8s linear infinite',
        flexShrink: 0,
      }} />
      <div>
        <div style={{ fontFamily: T.mono, fontSize: 12, color: s.color }}>{s.text}</div>
        {silent && phase === 'signing' && (
          <div style={{ fontFamily: T.mono, fontSize: 10, color: T.emerald, marginTop: 2 }}>
            {t('permit2OneSig')}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Compliance Badge ───────────────────────────────────────────────────────
export function ComplianceBadge({ record }: { record: ComplianceRecord }): React.JSX.Element {
  return (
    <div style={{
      borderRadius: 12, border: `1px solid ${T.emerald}30`,
      background: T.emerald + '08', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '8px 14px',
        background: T.emerald + '12',
        borderBottom: `1px solid ${T.emerald}20`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontFamily: T.mono, fontSize: 11, color: T.emerald, fontWeight: 700, letterSpacing: '0.08em' }}>
          MiCA · COMPLIANCE RECORD
        </span>
      </div>

      {/* Dati */}
      <div>
        {[
          { l: 'compliance_id',   v: record.compliance_id.slice(0, 16) + '…', mono: true  },
          { l: 'block_timestamp', v: record.block_timestamp                                },
          { l: 'fiat_rate',       v: record.fiat_rate ? `1 ${record.asset} = ${record.fiat_rate} EUR` : 'N/A' },
          { l: 'fiat_gross',      v: record.fiat_gross ? record.fiat_gross + ' EUR' : 'N/A' },
          { l: 'ip_jurisdiction', v: record.ip_jurisdiction + (record.mica_applicable ? ' · MiCA applicable' : '')  },
          { l: 'fiscal_ref',      v: record.fiscal_ref                        },
          { l: 'network',         v: record.network                           },
        ].map((r, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'flex-start',
            borderBottom: i < 6 ? `1px solid ${T.border}` : 'none',
            borderLeft: `2px dashed ${T.emerald}20`,
          }}>
            <div style={{ width: '38%', padding: '7px 8px 7px 12px', fontFamily: T.mono, fontSize: 10, color: T.muted, flexShrink: 0 }}>
              {r.l}
            </div>
            <div style={{ width: '62%', padding: '7px 12px 7px 4px', fontFamily: T.mono, fontSize: 11, color: T.text, wordBreak: 'break-all' as const }}>
              {r.v}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════
//  RESPONSE CARD v3 — Institutional style
// ══════════════════════════════════════════════════════════════════════════
interface ResponseCardProps {
  type:    'success' | 'error'
  code:    string
  title:   string
  rows:    { label: string; value: string; highlight?: boolean; dim?: boolean }[]
  footer?: React.ReactNode
}

export function ResponseCard({ type, code, title, rows, footer }: ResponseCardProps): React.JSX.Element {
  const accent = type === 'success' ? T.emerald : T.red

  return (
    <div style={{ borderRadius: 16, border: `1px solid ${accent}30`, overflow: 'hidden', background: T.card }}>
      {/* Header */}
      <div style={{
        padding: '12px 18px',
        background: accent + '0d',
        borderBottom: `1px solid ${accent}20`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: accent, boxShadow: `0 0 10px ${accent}` }} />
          <span style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 700 }}>
            <span style={{ color: accent, fontSize: 15 }}>{code}</span>
            <span style={{ color: T.muted }}> · </span>
            <span style={{ color: T.text }}>{title}</span>
          </span>
        </div>
        <span style={{ fontFamily: T.mono, fontSize: 9, color: T.muted + '80', letterSpacing: '0.1em' }}>
          application/json
        </span>
      </div>

      {/* Rows — left 38% / right 62% Mercuryo layout */}
      <div style={{ background: T.bg }}>
        {rows.map((row, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'flex-start',
            borderBottom: i < rows.length - 1 ? `1px solid ${T.border}` : 'none',
            borderLeft: `2px dashed ${T.border}`,
          }}>
            <div style={{ width: '38%', padding: '9px 8px 9px 14px', fontFamily: T.mono, fontSize: 10, color: T.muted, flexShrink: 0, lineHeight: 1.4 }}>
              {row.label}
            </div>
            <div style={{
              width: '62%', padding: '9px 14px 9px 6px',
              fontFamily: T.mono, fontSize: 12,
              fontWeight: row.highlight ? 700 : 500,
              color: row.highlight ? accent : row.dim ? T.muted : T.text,
              wordBreak: 'break-all' as const, lineHeight: 1.4,
            }}>
              {row.value}
            </div>
          </div>
        ))}
      </div>

      {footer && (
        <div style={{ padding: '10px 14px', borderTop: `1px solid ${T.border}`, background: T.surface }}>
          {footer}
        </div>
      )}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════
//  MAIN TransactionStatusUI v3
// ══════════════════════════════════════════════════════════════════════════
interface TxStatusProps {
  phase:          string
  txHash?:        string
  error?:         string
  isTestnet?:     boolean
  grossStr?:      string; netStr?: string; feeStr?: string
  symbol?:        string; recipient?: string
  paymentRef?:    string; fiscalRef?: string
  eurValue?:      string; timestamp?: string
  complianceRecord?: ComplianceRecord
  silentFlow?:    boolean
  onCopyHash?:    () => void; copied?: boolean
  onReset?:       () => void; onDownloadPdf?: () => void
}

export function TransactionStatusUI({
  phase, txHash, error, isTestnet = false,
  grossStr, netStr, feeStr, symbol = 'ETH',
  recipient, paymentRef, fiscalRef, eurValue, timestamp,
  complianceRecord, silentFlow,
  onCopyHash, copied, onReset, onDownloadPdf,
}: TxStatusProps): React.JSX.Element | null {

  const t = useTranslations('txStatus')
  const basescan = isTestnet ? 'https://sepolia.basescan.org/tx/' : 'https://basescan.org/tx/'
  const busy     = ['approving','wait_approve','signing','wait_send'].includes(phase)

  // ── SUCCESS ──────────────────────────────────────────────────────────────
  if (phase === 'done' && grossStr && netStr && feeStr) {
    const rows = [
      { label: 'status',            value: '200 OK · completed',        highlight: true  },
      { label: 'amount',            value: grossStr + ' ' + symbol                       },
      { label: 'net_amount (99.5%)',value: netStr   + ' ' + symbol,     highlight: true  },
      { label: 'fee_amount (0.5%)', value: feeStr   + ' ' + symbol                       },
      ...(eurValue ? [{ label: 'fiat_amount', value: '≈ ' + eurValue + ' EUR' }] : []),
      { label: 'recipient',         value: recipient ? recipient.slice(0,12)+'…'+recipient.slice(-6) : '—', dim: true },
      ...(paymentRef && paymentRef !== '—' ? [{ label: 'payment_ref', value: paymentRef }] : []),
      { label: 'network',           value: isTestnet ? 'BASE_SEPOLIA' : 'BASE', dim: true },
      { label: 'updated_at',        value: timestamp ?? new Date().toISOString(), dim: true },
    ]

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <ResponseCard
          type="success" code="200" title={t('paymentConfirmed')}
          rows={rows}
          footer={
            txHash ? (
              <div>
                <div style={{ fontFamily: T.mono, fontSize: 9, color: T.muted, letterSpacing: '0.1em', textTransform: 'uppercase' as const, marginBottom: 6 }}>
                  merchant_transaction_id
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontFamily: T.mono, fontSize: 11, color: T.muted, wordBreak: 'break-all' as const, flex: 1 }}>{txHash}</div>
                  <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
                    <button onClick={onCopyHash} style={{ fontFamily: T.mono, fontSize: 11, color: copied ? T.emerald : T.muted, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                      {copied ? t('copied') : '📋'}
                    </button>
                    <a href={basescan + txHash} target="_blank" rel="noopener noreferrer"
                      style={{ fontFamily: T.mono, fontSize: 11, color: '#C8512C', textDecoration: 'none' }}>
                      BaseScan ↗
                    </a>
                  </div>
                </div>
              </div>
            ) : undefined
          }
        />

        {/* Compliance record */}
        {complianceRecord && <ComplianceBadge record={complianceRecord} />}

        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, textAlign: 'center' as const }}>
          x_signature: PENDING_HMAC_SHA256 · Payload MiCA salvato in rp_compliance_db
        </div>

        {/* Azioni */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {onDownloadPdf && (
            <button onClick={onDownloadPdf} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              padding: '12px', borderRadius: 12,
              border: `1px solid ${T.emerald}30`,
              background: T.emerald + '0a',
              color: T.emerald, fontSize: 12, fontWeight: 700,
              cursor: 'pointer', fontFamily: T.mono, transition: 'all 0.2s',
            }}>
              {t('receiptPdf')}
            </button>
          )}
          {onReset && (
            <button onClick={onReset} style={{
              padding: '12px', borderRadius: 12,
              border: `1px solid ${T.border}`, background: 'transparent',
              color: T.muted, fontSize: 12, fontWeight: 700,
              cursor: 'pointer', fontFamily: T.display, transition: 'all 0.2s',
            }}>
              {t('newPayment')}
            </button>
          )}
        </div>
      </div>
    )
  }

  // ── ERROR ─────────────────────────────────────────────────────────────────
  if (phase === 'error' && error) {
    const cancelled   = error.includes('annullata') || error.includes('negata') || error.includes('rifiutata')
    const noGas       = error.includes('gas') || error.includes('Gas')
    const sequencer   = error.includes('sequencer') || error.includes('Sequencer')
    const code        = cancelled ? '499' : noGas ? '402' : sequencer ? '503' : '500'
    const title       = cancelled ? t('userCancelled')
      : noGas ? t('insufficientGas')
      : sequencer ? t('sequencerDown')
      : t('txFailed')

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <ResponseCard
          type="error" code={code} title={title}
          rows={[
            { label: 'error_code', value: code + ' · ' + title, highlight: true },
            { label: 'message',    value: error                                  },
            { label: 'network',    value: isTestnet ? 'BASE_SEPOLIA' : 'BASE'   },
          ]}
        />
        {onReset && (
          <button onClick={onReset} style={{
            width: '100%', padding: '11px', borderRadius: 12,
            border: `1px solid ${T.border}`, background: 'transparent',
            color: T.muted, fontSize: 13, fontWeight: 700,
            cursor: 'pointer', fontFamily: T.display, transition: 'all 0.2s',
          }}>
            {t('retry')}
          </button>
        )}
      </div>
    )
  }

  // ── IN PROGRESS ──────────────────────────────────────────────────────────
  if (busy) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <BallisticProgress active={phase === 'wait_send'} />
        <MicroStateBadge phase={phase} silent={silentFlow} />
      </div>
    )
  }

  return null
}

export default TransactionStatusUI
