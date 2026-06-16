'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useTranslations, useLocale } from 'next-intl'
import { useMerchantInvoices } from '@/hooks/useMerchantInvoices'
import { generatePdfInvoice } from '@/lib/usePdfInvoice'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'
const DANGER = '#C0392B'

const KNOWN_ERRORS = ['no_primary_wallet', 'invoice_exists', 'client_incomplete', 'session_not_ready', 'session_expired', 'insufficient_role']

// Default: mese precedente completo (UTC).
function defaultMonth(): string {
  const now = new Date()
  const y = now.getUTCFullYear()
  const m = now.getUTCMonth() // 0-based; mese corrente
  const prev = m === 0 ? 12 : m
  const py = m === 0 ? y - 1 : y
  return `${py}-${String(prev).padStart(2, '0')}`
}

function monthBounds(ym: string): { start: string; end: string } {
  const [y, m] = ym.split('-').map(Number)
  const start = new Date(Date.UTC(y, m - 1, 1, 0, 0, 0))
  const end = new Date(Date.UTC(y, m, 0, 23, 59, 59)) // giorno 0 del mese dopo = ultimo del mese
  return { start: start.toISOString(), end: end.toISOString() }
}

const fmtEur = (v?: string | null) =>
  (parseFloat(v || '0')).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const fmtDate = (v?: string | null) => {
  if (!v) return '—'
  try { return new Date(v).toLocaleDateString('it-IT') } catch { return v }
}

export function InvoicesSettings() {
  const t = useTranslations('settings.invoices')
  const locale = useLocale()
  const {
    invoices, loading, saving, error, noPrimaryWallet,
    isAuthed, currentUserRole, create, issue, clearError,
  } = useMerchantInvoices()

  const [month, setMonth] = useState<string>(defaultMonth())
  const canWrite = currentUserRole === 'admin' || currentUserRole === 'operator'

  if (!isAuthed) return <div style={{ color: MUTED }}>{t('loading')}</div>

  const header = (
    <header>
      <h1 className="text-2xl font-semibold" style={{ color: INK }}>{t('title')}</h1>
      <p className="text-sm mt-2" style={{ color: MUTED }}>{t('description')}</p>
    </header>
  )

  if (noPrimaryWallet) {
    return (
      <div className="flex flex-col gap-6 max-w-3xl">
        {header}
        <div style={{ background: 'rgba(200,81,44,0.06)', border: `1px solid ${ORANGE}`, borderRadius: 8, padding: 16, color: INK }}>
          <p className="text-sm font-medium mb-1">{t('noWallet.title')}</p>
          <p className="text-sm mb-3" style={{ color: MUTED }}>{t('noWallet.body')}</p>
          <Link href={`/${locale}/settings/wallets`} className="inline-block text-sm font-medium" style={{ color: ORANGE, textDecoration: 'none' }}>
            {t('noWallet.cta')} →
          </Link>
        </div>
      </div>
    )
  }

  const onGenerate = async () => {
    const { start, end } = monthBounds(month)
    await create(start, end)
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      {header}

      <div style={{ background: 'rgba(44,44,42,0.04)', border: '1px solid rgba(44,44,42,0.10)', borderRadius: 8, padding: 12, color: INK }}>
        <p className="text-sm">{t('infoBanner')}</p>
      </div>

      {error && (
        <div style={{ background: 'rgba(192,57,43,0.06)', border: `1px solid ${DANGER}`, borderRadius: 8, padding: 12, color: INK, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="text-sm">{t(`errors.${KNOWN_ERRORS.includes(error) ? error : 'generic'}`)}</span>
          <button onClick={clearError} aria-label="dismiss" style={{ color: MUTED }}>×</button>
        </div>
      )}

      {/* Generatore */}
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium" style={{ color: INK }}>{t('periodLabel')}</span>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            disabled={!canWrite || saving}
            className="px-3 py-2 rounded-lg text-sm"
            style={{ border: '1px solid rgba(44,44,42,0.18)', background: '#FFFFFF', color: INK }}
          />
        </label>
        <button
          onClick={onGenerate}
          disabled={!canWrite || saving}
          style={{ background: ORANGE, color: '#FFFFFF', border: 'none', borderRadius: 8, padding: '8px 18px', cursor: !canWrite || saving ? 'not-allowed' : 'pointer', opacity: !canWrite || saving ? 0.5 : 1, fontWeight: 600 }}
        >
          {saving ? t('generating') : t('generate')}
        </button>
      </div>
      {!canWrite && <p className="text-sm" style={{ color: MUTED }}>{t('readOnly')}</p>}

      {/* Lista fatture */}
      {loading ? (
        <div style={{ color: MUTED }}>{t('loading')}</div>
      ) : invoices.length === 0 ? (
        <div style={{ color: MUTED }} className="text-sm">{t('empty')}</div>
      ) : (
        <div className="flex flex-col gap-2">
          {invoices.map((inv) => (
            <div key={inv.id} className="flex items-center justify-between gap-3 p-3 rounded-lg" style={{ border: '1px solid rgba(44,44,42,0.12)', background: '#FFFFFF' }}>
              <div className="min-w-0">
                <div className="text-sm font-medium" style={{ color: INK }}>
                  {inv.invoice_number}
                  <span className="ml-2 text-[10px] uppercase tracking-wider px-2 py-0.5 rounded" style={{ color: inv.status === 'issued' ? ORANGE : MUTED, background: inv.status === 'issued' ? 'rgba(200,81,44,0.10)' : 'rgba(44,44,42,0.06)' }}>
                    {inv.status === 'issued' ? t('status.issued') : t('status.draft')}
                  </span>
                </div>
                <div className="text-xs mt-0.5" style={{ color: MUTED }}>
                  {fmtDate(inv.period_start)} – {fmtDate(inv.period_end)} · {inv.tx_count} tx · € {fmtEur(inv.total_eur)}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {canWrite && inv.status !== 'issued' && (
                  <button
                    onClick={() => issue(inv.id)}
                    disabled={saving}
                    className="text-sm"
                    style={{ color: ORANGE, background: 'transparent', border: `1px solid ${ORANGE}`, borderRadius: 8, padding: '6px 12px', cursor: saving ? 'not-allowed' : 'pointer' }}
                  >
                    {t('issue')}
                  </button>
                )}
                <button
                  onClick={() => generatePdfInvoice(inv)}
                  className="text-sm"
                  style={{ color: '#FFFFFF', background: INK, border: 'none', borderRadius: 8, padding: '6px 12px', cursor: 'pointer' }}
                >
                  {t('downloadPdf')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
