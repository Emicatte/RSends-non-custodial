'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { effectiveStatus } from '@/lib/intentStatus'
// The one explorer resolver. This file used to carry its own chain->base map,
// which meant a chain the checkout could link was still unlinked here: a TRON
// row degraded to a bare hash because the local map had no tron key.
import { explorerTxUrl } from '@/lib/web3/explorer'
import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'

/**
 * The payments history table, lifted verbatim out of
 * app/[locale]/app/payments/page.tsx so it can be rendered from something other
 * than that route.
 *
 * It is presentational: it takes rows and two callbacks and owns no data
 * fetching, no session and no org. That is what lets the marketing landing page
 * render the SAME table the merchant sees (components/landing/DeviceShowcase.tsx)
 * against a fixture, instead of a screenshot that drifts the first time a label
 * changes here.
 *
 * Two consequences worth knowing before editing:
 *
 *  - It keeps its own `useTranslations('app.payments')`, so it localizes
 *    wherever it is mounted. Do not lift the strings out into props.
 *  - Anything added here shows up on the public landing page. That is the point,
 *    and it is also the risk: no merchant-identifying default, ever.
 */

// Visual language mirrors the /app home (app/[locale]/app/page.tsx) so the
// full payments history composes with the home summary widget.
export const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  accent: '#C45A3C',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.08)',
  orange: '#D97A2E',
  orangeLight: 'rgba(217, 122, 46, 0.08)',
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.08)',
}

// Backend IntentStatus → chip palette + i18n key under app.payments.status.
type StatusTone = { bg: string; text: string }
const STATUS_TONE: Record<string, StatusTone> = {
  paid: { bg: COLORS.greenLight, text: COLORS.green },
  completed: { bg: COLORS.greenLight, text: COLORS.green },
  pending: { bg: COLORS.orangeLight, text: COLORS.orange },
  partial: { bg: COLORS.orangeLight, text: COLORS.orange },
  overpaid: { bg: COLORS.orangeLight, text: COLORS.orange },
  review: { bg: COLORS.orangeLight, text: COLORS.orange },
  expired: { bg: COLORS.redLight, text: COLORS.red },
  cancelled: { bg: COLORS.redLight, text: COLORS.red },
  refunded: { bg: COLORS.redLight, text: COLORS.red },
}
// Statuses with an app.payments.status.<key> label (guards the i18n lookup).
const KNOWN_STATUS = new Set([
  'pending', 'paid', 'completed', 'expired', 'cancelled',
  'review', 'refunded', 'partial', 'overpaid',
])

const CHAIN_LABEL: Record<string, string> = {
  base_sepolia: 'Base Sepolia',
  base: 'Base',
  sepolia: 'Sepolia',
  ethereum: 'Ethereum',
  eth: 'Ethereum',
}

function truncAddr(addr: string): string {
  return addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr
}

// Locale and timezone are PINNED, never resolved from the ambient environment.
// `Intl.*Format(undefined, …)` asks the runtime to decide, which means Node's
// ICU default in the server process and the visitor's browser settings on the
// client — the same row then renders as two different strings (observed:
// "Jul 8, 2026, 11:30 PM" vs "2026/07/09 8:30", a different calendar day), and
// React tears the whole root down on the mismatch. `timeZoneName: 'short'` makes
// the pinned zone visible so a UTC stamp is never mistaken for local time.
// Pinned to en-US to match the rest of the dashboard (app/[locale]/app/page.tsx).
const DATE_FMT = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZone: 'UTC',
  timeZoneName: 'short',
})
function fmtDate(iso: string): string {
  const ts = new Date(iso).getTime()
  return Number.isFinite(ts) ? DATE_FMT.format(ts) : iso
}

const AMOUNT_FMT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 })

// Spacing lives in the className (default `px-3.5 py-2 rounded-lg`, small
// inline variant `px-2 py-1 rounded-lg`); this const keeps only the shared
// non-spacing button chrome.
export const btnStyle: React.CSSProperties = {
  border: 'none',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
}

// Cell padding lives in the shared `px-4 py-3` className on every th/td.
const cellStyle: React.CSSProperties = {
  fontSize: 13,
  color: COLORS.ink,
  borderBottom: `1px solid ${COLORS.border}`,
  textAlign: 'left',
  whiteSpace: 'nowrap',
}
const headStyle: React.CSSProperties = {
  ...cellStyle,
  fontFamily: 'var(--font-display)',
  fontSize: 10,
  fontWeight: 700,
  color: COLORS.muted,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
}

// ── Per-row "copy pay link" button (self-contained copied state) ──
function CopyLinkButton({ intentId }: { intentId: string }) {
  const t = useTranslations('app.payments')
  const [copied, setCopied] = useState(false)
  function copy() {
    if (typeof window === 'undefined' || !navigator.clipboard) return
    navigator.clipboard.writeText(`${window.location.origin}/pay/${intentId}`).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {},
    )
  }
  return (
    <button
      type="button"
      onClick={copy}
      className="px-2 py-1 rounded-lg"
      style={{ ...btnStyle, background: 'transparent', color: COLORS.accent, fontSize: 12 }}
    >
      {copied ? t('row.copied') : t('row.copyLink')}
    </button>
  )
}

export interface PaymentsTableProps {
  records: OrgPaymentRecord[]
  /** Expiry clock. Null until the client has one — see the page's useEffect. */
  nowMs: number | null
  canManage: boolean
  loading?: boolean
  /** Matches useOrgPayments' own `useState<string | null>` — not `unknown`, or
   *  the `{error && …}` guard below leaks a non-ReactNode into the JSX. */
  error?: string | null
  onRepeat: (r: OrgPaymentRecord) => void
  onCancel: (intentId: string) => void
}

export function PaymentsTable({
  records,
  nowMs,
  canManage,
  loading = false,
  error = null,
  onRepeat,
  onCancel,
}: PaymentsTableProps) {
  const t = useTranslations('app.payments')

  return (
    /* Full-bleed card variant: border/radius/bg without the p-5 (the table
       supplies its own px-4 py-3 cell padding). */
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        background: COLORS.white,
        borderColor: COLORS.border,
      }}
    >
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: COLORS.paper }}>
              <th className="px-4 py-3" style={headStyle}>{t('columns.date')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.amount')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.network')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.status')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.recipient')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.tx')}</th>
              <th className="px-4 py-3" style={headStyle}>{t('columns.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r: OrgPaymentRecord) => {
              // ONE derivation, feeding both the chip and the row action, so
              // they cannot disagree about the same row.
              const shown = effectiveStatus(r, nowMs)
              const tone = STATUS_TONE[shown] ?? {
                bg: 'rgba(26,26,26,0.06)',
                text: COLORS.muted,
              }
              const statusLabel = KNOWN_STATUS.has(shown)
                ? t(`status.${shown}`)
                : shown
              const txHash = r.matched_tx_hash || r.tx_hash
              // A payments row carries a chain NAME and never a chain id, so
              // the name is the lookup and the id argument is null.
              const txUrl = txHash ? explorerTxUrl(null, txHash, r.chain) : null
              return (
                <tr key={r.intent_id}>
                  <td className="px-4 py-3" style={{ ...cellStyle, color: COLORS.muted }}>
                    {fmtDate(r.created_at)}
                  </td>
                  <td className="px-4 py-3" style={{ ...cellStyle, fontWeight: 600 }}>
                    {AMOUNT_FMT.format(r.amount)} {r.currency}
                  </td>
                  <td className="px-4 py-3" style={cellStyle}>
                    {CHAIN_LABEL[r.chain?.toLowerCase()] ?? r.chain}
                  </td>
                  <td className="px-4 py-3" style={cellStyle}>
                    <span
                      className="inline-block px-2 py-0.5 rounded-full"
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        background: tone.bg,
                        color: tone.text,
                      }}
                    >
                      {statusLabel}
                    </span>
                  </td>
                  <td
                    className="px-4 py-3"
                    style={{
                      ...cellStyle,
                      fontFamily: 'var(--font-mono, monospace)',
                      color: COLORS.subtle,
                    }}
                  >
                    {r.split && r.split.length > 0 ? (
                      <span
                        title={r.split
                          .map(
                            (leg) =>
                              `${truncAddr(leg.address)} — ${leg.share_bps / 100}%`,
                          )
                          .join('\n')}
                      >
                        {t('row.split')} · {r.split.length}
                      </span>
                    ) : r.recipient ? (
                      truncAddr(r.recipient)
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-3" style={cellStyle}>
                    {txUrl ? (
                      <a
                        href={txUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: COLORS.green, textDecoration: 'none', fontWeight: 600 }}
                      >
                        {t('txView')}
                      </a>
                    ) : txHash ? (
                      <span
                        style={{
                          fontFamily: 'var(--font-mono, monospace)',
                          color: COLORS.subtle,
                        }}
                      >
                        {truncAddr(txHash)}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-4 py-3" style={cellStyle}>
                    {/* Two independent questions, deliberately keyed to
                        different values.

                        "Is this link still worth sharing?" is a DERIVED
                        question — a live link is copyable, a dead one is
                        repeatable. Repeat needs the create capability, so a
                        viewer gets neither rather than a dead URL.

                        "Will the backend accept a cancel?" is a STORED
                        question — the cancel route is pending-only, and it
                        reads the column, not our clock. Hiding a working
                        action on a display-side computation would be the UI
                        overruling backend truth, which is never what you want
                        on the money path.

                        So a past-expiry intent that the Celery task has not
                        reached yet shows Repeat AND Cancel: the link is dead,
                        regenerate one, and close the original record. */}
                    <div className="flex items-center gap-1.5">
                      {shown === 'pending' ? (
                        <CopyLinkButton intentId={r.intent_id} />
                      ) : (
                        canManage && (
                          <button
                            type="button"
                            onClick={() => onRepeat(r)}
                            className="px-2 py-1 rounded-lg"
                            style={{ ...btnStyle, background: 'transparent', color: COLORS.accent, fontSize: 12 }}
                          >
                            {t('row.repeat')}
                          </button>
                        )
                      )}
                      {canManage && r.status === 'pending' && (
                        <button
                          type="button"
                          onClick={() => onCancel(r.intent_id)}
                          className="px-2 py-1 rounded-lg"
                          style={{ ...btnStyle, background: 'transparent', color: COLORS.red, fontSize: 12 }}
                        >
                          {t('row.cancel')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {loading && records.length === 0 && (
        <div className="px-4 py-7" style={{ textAlign: 'center', fontSize: 13, color: COLORS.muted }}>
          {t('loading')}
        </div>
      )}
      {error && !loading && (
        <div className="px-4 py-7" style={{ textAlign: 'center', fontSize: 13, color: COLORS.red }}>
          {t('errorLoading')}
        </div>
      )}
      {!loading && !error && records.length === 0 && (
        <div className="px-4 py-10" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>
            {t('empty.title')}
          </div>
          <div className="mt-1" style={{ fontSize: 13, color: COLORS.muted }}>
            {t('empty.hint')}
          </div>
        </div>
      )}
    </div>
  )
}
