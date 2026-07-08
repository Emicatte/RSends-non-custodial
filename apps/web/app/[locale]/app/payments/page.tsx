'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'
import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'
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

const DATE_FMT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})
function fmtDate(iso: string): string {
  const ts = new Date(iso).getTime()
  return Number.isFinite(ts) ? DATE_FMT.format(ts) : iso
}

const AMOUNT_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 })

const btnStyle: React.CSSProperties = {
  padding: '8px 14px',
  borderRadius: 8,
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
      style={{ ...btnStyle, background: 'transparent', color: COLORS.accent, padding: '4px 8px', fontSize: 12 }}
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
  const canManage = role === 'operator' || role === 'admin'
  const settlementWallet = activeOrg?.settlement_wallet ?? null

  async function onCancel(intentId: string) {
    if (typeof window !== 'undefined' && !window.confirm(t('row.cancelConfirm'))) return
    try {
      await cancelIntent(intentId)
    } catch (e) {
      console.error('[payments] cancel failed', e)
    }
  }

  const cellStyle: React.CSSProperties = {
    padding: '12px 14px',
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
    <main className="rp-app-page">
      <div style={{ marginBottom: 20 }}>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22,
            fontWeight: 700,
            color: COLORS.ink,
            margin: 0,
          }}
        >
          {t('title')}
        </h1>
        <p style={{ fontSize: 13, color: COLORS.muted, margin: '4px 0 0' }}>
          {t('subtitle')}
        </p>
      </div>

      {/* Toolbar: status filter + create */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 14,
        }}
      >
        <select
          aria-label={t('columns.status')}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            padding: '8px 11px',
            borderRadius: 8,
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
            onClick={() => setModalOpen(true)}
            style={{ ...btnStyle, background: COLORS.accent, color: COLORS.white }}
          >
            {t('newButton')}
          </button>
        )}
      </div>

      <div
        style={{
          background: COLORS.white,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: COLORS.paper }}>
                <th style={headStyle}>{t('columns.date')}</th>
                <th style={headStyle}>{t('columns.amount')}</th>
                <th style={headStyle}>{t('columns.network')}</th>
                <th style={headStyle}>{t('columns.status')}</th>
                <th style={headStyle}>{t('columns.recipient')}</th>
                <th style={headStyle}>{t('columns.tx')}</th>
                <th style={headStyle}>{t('columns.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r: OrgPaymentRecord) => {
                const tone = STATUS_TONE[r.status] ?? {
                  bg: 'rgba(26,26,26,0.06)',
                  text: COLORS.muted,
                }
                const statusLabel = KNOWN_STATUS.has(r.status)
                  ? t(`status.${r.status}`)
                  : r.status
                const txHash = r.matched_tx_hash || r.tx_hash
                const txUrl = txHash ? explorerTxUrl(r.chain, txHash) : null
                return (
                  <tr key={r.intent_id}>
                    <td style={{ ...cellStyle, color: COLORS.muted }}>
                      {fmtDate(r.created_at)}
                    </td>
                    <td style={{ ...cellStyle, fontWeight: 600 }}>
                      {AMOUNT_FMT.format(r.amount)} {r.currency}
                    </td>
                    <td style={cellStyle}>
                      {CHAIN_LABEL[r.chain?.toLowerCase()] ?? r.chain}
                    </td>
                    <td style={cellStyle}>
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '3px 9px',
                          borderRadius: 999,
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
                      style={{
                        ...cellStyle,
                        fontFamily: 'var(--font-mono, monospace)',
                        color: COLORS.subtle,
                      }}
                    >
                      {r.recipient ? truncAddr(r.recipient) : '—'}
                    </td>
                    <td style={cellStyle}>
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
                    <td style={cellStyle}>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <CopyLinkButton intentId={r.intent_id} />
                        {canManage && r.status === 'pending' && (
                          <button
                            type="button"
                            onClick={() => onCancel(r.intent_id)}
                            style={{ ...btnStyle, background: 'transparent', color: COLORS.red, padding: '4px 8px', fontSize: 12 }}
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
          <div style={{ padding: '28px 16px', textAlign: 'center', fontSize: 13, color: COLORS.muted }}>
            {t('loading')}
          </div>
        )}
        {error && !loading && (
          <div style={{ padding: '28px 16px', textAlign: 'center', fontSize: 13, color: COLORS.red }}>
            {t('errorLoading')}
          </div>
        )}
        {!loading && !error && records.length === 0 && (
          <div style={{ padding: '40px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: COLORS.ink }}>
              {t('empty.title')}
            </div>
            <div style={{ fontSize: 13, color: COLORS.muted, marginTop: 4 }}>
              {t('empty.hint')}
            </div>
          </div>
        )}
      </div>

      {/* Pagination */}
      {(hasPrev || hasNext) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginTop: 16,
          }}
        >
          <span style={{ fontSize: 12, color: COLORS.muted }}>
            {t('pagination.page')} {page} · {total} {t('pagination.results')}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={!hasPrev}
              className="rp-page-btn"
              style={{
                padding: '6px 14px',
                borderRadius: 8,
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
              className="rp-page-btn"
              style={{
                padding: '6px 14px',
                borderRadius: 8,
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
          settlementWallet={settlementWallet}
          onCreate={createIntent}
          onClose={() => setModalOpen(false)}
        />
      )}
    </main>
  )
}
