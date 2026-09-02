'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useCurrentOrg } from '@/hooks/useCurrentOrg'
import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'
import { appPage } from '@/components/app/pageStyles'
// The table, its palette and its button chrome moved to components/app so the
// marketing landing page can render the SAME table the merchant sees. Values
// are unchanged; only the file they live in.
import { PaymentsTable, COLORS, btnStyle } from '@/components/app/PaymentsTable'
import {
  resolveRepeatPrefill,
  type CreatePrefill,
  type PrefillFailure,
} from '@/lib/repeatPrefill'
import { useOrgPayments, type OrgPaymentRecord } from '@/hooks/useOrgPayments'

// The status values offered in the filter dropdown (the operational set).
//
// KNOWN MISMATCH: this filter is applied SERVER-side against the stored column,
// while the chip and row action derive expiry client-side (lib/intentStatus.ts).
// So filtering "Expired" will not return an intent the Celery task has not
// flipped yet, and filtering "Pending" can return rows whose chip reads Expired.
// The fix is deriving expiry in the backend serializer — issue #80; do not paper
// over it here with a client-side re-filter, which would break pagination counts.
const FILTER_STATUSES = ['pending', 'paid', 'expired', 'cancelled'] as const

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
  // The TRON payout address is its own column, not derived from the EVM one.
  // The modal needs both because it shows the wallet for the SELECTED network.
  const settlementWalletTron = activeOrg?.settlement_wallet_tron ?? null

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
    // BOTH payout addresses, keyed by family: the source row's network decides
    // which one it settles to implicitly, and passing only the EVM column made
    // a TRON repeat resolve against an address it can never land on.
    const result = resolveRepeatPrefill(r, {
      evm: settlementWallet,
      tron: settlementWalletTron,
    })
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

      <PaymentsTable
        records={records}
        nowMs={nowMs}
        canManage={canManage}
        loading={loading}
        error={error}
        onRepeat={onRepeat}
        onCancel={onCancel}
      />

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
          settlementWalletTron={settlementWalletTron}
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
