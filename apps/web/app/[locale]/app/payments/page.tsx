'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'
import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'
import { appPage } from '@/components/app/pageStyles'
import { effectiveStatus } from '@/lib/intentStatus'
import {
  resolveRepeatPrefill,
  type CreatePrefill,
  type PrefillFailure,
} from '@/lib/repeatPrefill'
import { useOrgPayments, type OrgPaymentRecord } from '@/hooks/useOrgPayments'

// Visual language mirrors the /app home (app/[locale]/app/page.tsx) so the
// full payments history composes with the home summary widget.
const COLORS = {
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
// The status values offered in the filter dropdown (the operational set).
//
// KNOWN MISMATCH: this filter is applied SERVER-side against the stored column,
// while the chip and row action derive expiry client-side (lib/intentStatus.ts).
// So filtering "Expired" will not return an intent the Celery task has not
// flipped yet, and filtering "Pending" can return rows whose chip reads Expired.
// The fix is deriving expiry in the backend serializer — issue #80; do not paper
// over it here with a client-side re-filter, which would break pagination counts.
const FILTER_STATUSES = ['pending', 'paid', 'expired', 'cancelled'] as const

const CHAIN_LABEL: Record<string, string> = {
  base_sepolia: 'Base Sepolia',
  base: 'Base',
  sepolia: 'Sepolia',
  ethereum: 'Ethereum',
  eth: 'Ethereum',
}

// Chain string → block-explorer base (testnet-first; the UI is locked to test).
const EXPLORER_BASE: Record<string, string> = {
  base_sepolia: 'https://sepolia.basescan.org',
  base: 'https://basescan.org',
  sepolia: 'https://sepolia.etherscan.io',
  ethereum: 'https://etherscan.io',
  eth: 'https://etherscan.io',
}

function explorerTxUrl(chain: string, hash: string): string | null {
  const base = EXPLORER_BASE[(chain || '').toLowerCase()]
  return base ? `${base}/tx/${hash}` : null
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
const btnStyle: React.CSSProperties = {
  border: 'none',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
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

export default function AppPaymentsPage() {
  const t = useTranslations('app.payments')
  const { role, activeOrg } = useCurrentOrg()
  const {
    records,
    total,
    page,
    hasPrev,
    hasNext,
    loading,
    error,
    statusFilter,
    setStatusFilter,
    setPage,
    createIntent,
    cancelIntent,
  } = useOrgPayments()

  const [modalOpen, setModalOpen] = useState(false)
  // Seed values for a repeat, plus a counter that remounts the modal so a second
  // repeat re-seeds instead of reusing the first one's state.
  const [prefill, setPrefill] = useState<CreatePrefill | null>(null)
  const [modalSeq, setModalSeq] = useState(0)
  const [prefillError, setPrefillError] = useState<PrefillFailure | null>(null)
  const canManage = role === 'operator' || role === 'admin'
  const settlementWallet = activeOrg?.settlement_wallet ?? null

  // Expiry clock. Deliberately NOT read during render: this file already pins
  // its Intl formats because an SSR/client divergence tears the React root, and
  // a render-time Date.now() is the same hazard. First client render matches the
  // server (null), then this effect drives a second render — an update, not a
  // mismatch.
  const [nowMs, setNowMs] = useState<number | null>(null)
  useEffect(() => {
    setNowMs(Date.now())
  }, [records])

  function openCreate() {
    setPrefill(null)
    setPrefillError(null)
    setModalSeq((n) => n + 1)
    setModalOpen(true)
  }

  // Repeat: resolve the source row into create-form values, or refuse and say
  // which field failed. NEVER creates an intent — it only opens the same modal a
  // manual create opens, prefilled; the merchant still confirms.
  function onRepeat(r: OrgPaymentRecord) {
    const result = resolveRepeatPrefill(r, settlementWallet)
    if (!result.ok) {
      setPrefillError(result.field)
      setModalOpen(false)
      return
    }
    setPrefillError(null)
    setPrefill(result.values)
    setModalSeq((n) => n + 1)
    setModalOpen(true)
  }

  async function onCancel(intentId: string) {
    if (typeof window !== 'undefined' && !window.confirm(t('row.cancelConfirm'))) return
    try {
      await cancelIntent(intentId)
    } catch (e) {
      console.error('[payments] cancel failed', e)
    }
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

  return (
    <main className={appPage}>
      {/* The page title lives in the topbar (AppTopbar resolves it from the
          pathname) — the page opens with its one-line intro, mb-6 above the
          toolbar, which binds mb-4 to its table. */}
      <p className="m-0 mb-6" style={{ fontSize: 13, color: COLORS.muted }}>
        {t('subtitle')}
      </p>

      {/* Toolbar: status filter + create */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <select
          aria-label={t('columns.status')}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 rounded-lg"
          style={{
            border: `1px solid ${COLORS.border}`,
            fontSize: 13,
            background: COLORS.white,
            color: COLORS.ink,
          }}
        >
          <option value="">{t('filter.all')}</option>
          {FILTER_STATUSES.map((s) => (
            <option key={s} value={s}>{t(`status.${s}`)}</option>
          ))}
        </select>
        {canManage && (
          <button
            type="button"
            onClick={openCreate}
            className="px-3.5 py-2 rounded-lg"
            style={{ ...btnStyle, background: COLORS.accent, color: COLORS.white }}
          >
            {t('newButton')}
          </button>
        )}
      </div>

      {/* A repeat that cannot be resolved into a valid current configuration
          names the field that failed. It never opens the modal half-filled: a
          silent default here would issue a request the merchant never chose. */}
      {prefillError && (
        <div
          role="alert"
          className="mb-4 px-4 py-3 rounded-xl border"
          style={{
            fontSize: 13,
            color: COLORS.red,
            background: COLORS.redLight,
            borderColor: COLORS.border,
          }}
        >
          {t(`row.repeatError.${prefillError}`)}
        </div>
      )}

      {/* Full-bleed card variant: border/radius/bg without the p-5 (the table
          supplies its own px-4 py-3 cell padding). */}
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
                const txUrl = txHash ? explorerTxUrl(r.chain, txHash) : null
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

      {/* Pagination */}
      {(hasPrev || hasNext) && (
        <div className="mt-4 flex items-center justify-between">
          <span style={{ fontSize: 12, color: COLORS.muted }}>
            {t('pagination.page')} {page} · {total} {t('pagination.results')}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={!hasPrev}
              className="rp-page-btn px-3.5 py-1.5 rounded-lg"
              style={{
                border: `1px solid ${COLORS.border}`,
                background: COLORS.white,
                fontSize: 13,
                color: hasPrev ? COLORS.ink : COLORS.subtle,
                cursor: hasPrev ? 'pointer' : 'not-allowed',
              }}
            >
              {t('pagination.prev')}
            </button>
            <button
              type="button"
              onClick={() => setPage(page + 1)}
              disabled={!hasNext}
              className="rp-page-btn px-3.5 py-1.5 rounded-lg"
              style={{
                border: `1px solid ${COLORS.border}`,
                background: COLORS.white,
                fontSize: 13,
                color: hasNext ? COLORS.ink : COLORS.subtle,
                cursor: hasNext ? 'pointer' : 'not-allowed',
              }}
            >
              {t('pagination.next')}
            </button>
          </div>
        </div>
      )}

      {modalOpen && (
        <CreatePaymentModal
          key={modalSeq}
          settlementWallet={settlementWallet}
          initialValues={prefill ?? undefined}
          onCreate={createIntent}
          onClose={() => {
            setModalOpen(false)
            setPrefill(null)
          }}
        />
      )}
    </main>
  )
}
