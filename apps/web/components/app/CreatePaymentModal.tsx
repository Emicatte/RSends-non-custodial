'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { isAddress } from 'viem'
import { Link } from '@/i18n/navigation'
import { BPS_TOTAL, bpsToPercent, payoutAmount, percentToBps, remainderBps } from '@/lib/splitShares'
import type { CreateInvoiceInput, CreatedInvoice } from '@/hooks/useOrgPayments'

// Phase D — create-payment-request (invoice) modal for /app/payments. Lives in a
// component file (not page.tsx) so it can carry a named export + be unit-tested
// with props; Next.js route modules may only export the reserved page symbols.

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  subtle: '#9a9a9a',
  paper: '#f7f6f3',
  white: '#ffffff',
  border: '#e5e4e0',
  accent: '#C45A3C',
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.08)',
}

// The create flow is hard-locked to test: Base Sepolia is the only settleable
// testnet (USDC + ETH are the enabled tokens there). No chain picker, no live.
const CREATE_CHAIN = 'base_sepolia'
const CREATE_TOKENS = ['USDC', 'ETH'] as const
const EXPIRY_OPTIONS = [
  { minutes: 30, key: 'expiry30m' },
  { minutes: 60, key: 'expiry1h' },
  { minutes: 1440, key: 'expiry24h' },
] as const

function truncAddr(addr: string): string {
  return addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr
}

const btnStyle: React.CSSProperties = {
  padding: '8px 14px',
  borderRadius: 8,
  border: 'none',
  fontSize: 13,
  fontWeight: 600,
  cursor: 'pointer',
}

// ── Split (non-custodial, BPS-exact) ─────────────────────────────
// Client mirror of the server gate: 2..20 legs, valid unique addresses,
// integer bps summing to EXACTLY 10000. The server 422 stays authoritative.
// The LAST row is the balance row — its share is always 10000 − sum of the
// manual rows above it, so a valid form sums to 10000 by construction.
const SPLIT_MIN = 2
const SPLIT_MAX = 20
const SPLIT_LEG_COLORS = ['#C45A3C', '#3B82F6', '#00B27A', '#D99A2B'] as const
// Same convention as the payments list (AMOUNT_FMT in payments/page.tsx).
const AMOUNT_FMT = new Intl.NumberFormat(undefined, { maximumFractionDigits: 6 })

interface SplitLegDraft {
  address: string
  percent: string
}

export function CreatePaymentModal({
  settlementWallet,
  onCreate,
  onClose,
}: {
  settlementWallet: string | null
  onCreate: (input: CreateInvoiceInput) => Promise<CreatedInvoice>
  onClose: () => void
}) {
  const t = useTranslations('app.payments')
  const [amount, setAmount] = useState('')
  const [token, setToken] = useState<string>('USDC')
  const [expiry, setExpiry] = useState<number>(30)
  const [recipient, setRecipient] = useState('')
  const [splitOn, setSplitOn] = useState(false)
  const [legs, setLegs] = useState<SplitLegDraft[]>([
    { address: '', percent: '' },
    { address: '', percent: '' },
  ])
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [payLink, setPayLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const amountNum = Number(amount)
  const amountValid = Number.isFinite(amountNum) && amountNum > 0
  const override = recipient.trim()
  const overrideValid = override === '' || isAddress(override)
  const overrideResolves = override !== '' && isAddress(override)
  // The recipient gate (server-enforced) needs EITHER an org settlement wallet
  // OR a valid per-intent override; block the submit otherwise (no blind 422).
  const hasRecipient = Boolean(settlementWallet) || overrideResolves

  // Split validity — the client mirror of the server BPS gate. A valid split
  // set IS the recipient set: no settlement wallet needed. Manual rows are
  // everything above the last; the last row balances to 10000 bps.
  const manualBps = legs.slice(0, -1).map((leg) => percentToBps(leg.percent))
  const balanceBps = remainderBps(manualBps)
  const legAddrs = legs.map((leg) => leg.address.trim())
  const addrsValid = legAddrs.every((a) => isAddress(a))
  const addrsUnique =
    new Set(legAddrs.map((a) => a.toLowerCase())).size === legAddrs.length
  const sharesParsed = manualBps.every((b) => b != null)
  const balanceOk = balanceBps != null && balanceBps >= 1
  const splitValid =
    legs.length >= SPLIT_MIN &&
    legs.length <= SPLIT_MAX &&
    addrsValid &&
    addrsUnique &&
    sharesParsed &&
    balanceOk
  // Per-leg bps for display/payload: manual rows + the derived balance.
  const legBps = legs.map((_, i) =>
    i < legs.length - 1 ? manualBps[i] : balanceOk ? balanceBps : null,
  )
  const bpsSum = balanceOk
    ? BPS_TOTAL
    : manualBps.reduce<number>((acc, b) => acc + (b ?? 0), 0)
  // One failure names itself — never blame the sum for an address problem.
  const splitError = !addrsValid
    ? 'splitErrorAddress'
    : !addrsUnique
      ? 'splitErrorDuplicate'
      : !sharesParsed
        ? 'splitErrorShare'
        : balanceBps != null && balanceBps < 1
          ? 'splitErrorExceeds'
          : null

  const canSubmit =
    amountValid &&
    !submitting &&
    (splitOn ? splitValid : overrideValid && hasRecipient)

  function setLeg(index: number, patch: Partial<SplitLegDraft>) {
    setLegs((prev) => prev.map((leg, i) => (i === index ? { ...leg, ...patch } : leg)))
  }

  async function submit() {
    if (!canSubmit) return
    setSubmitting(true)
    setErr(null)
    try {
      const created = await onCreate({
        amount: amountNum,
        currency: token,
        chain: CREATE_CHAIN,
        expires_in_minutes: expiry,
        ...(splitOn
          ? {
              split: legs.map((leg, i) => ({
                address: leg.address.trim(),
                share_bps: legBps[i] as number,
              })),
            }
          : override
            ? { recipient: override }
            : {}),
      })
      const origin = typeof window !== 'undefined' ? window.location.origin : ''
      setPayLink(`${origin}/pay/${created.intent_id}`)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      // apiCall surfaces 422s as "HTTP 422" (no detail). Split mode's only
      // 422 (the client pre-validates the vectors) is SPLIT_UNAVAILABLE;
      // single mode's only 422 is the recipient gate.
      setErr(
        code === 'HTTP 422'
          ? splitOn
            ? t('create.errors.splitUnavailable')
            : t('create.errors.gate')
          : t('create.errors.generic'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  function copyLink() {
    if (!payLink || typeof navigator === 'undefined' || !navigator.clipboard) return
    navigator.clipboard.writeText(payLink).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {},
    )
  }

  const label: React.CSSProperties = {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: COLORS.muted,
    marginBottom: 6,
  }
  const field: React.CSSProperties = {
    width: '100%',
    padding: '9px 11px',
    borderRadius: 8,
    border: `1px solid ${COLORS.border}`,
    fontSize: 14,
    background: COLORS.white,
    color: COLORS.ink,
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(26,26,26,0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        zIndex: 1100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: COLORS.white,
          borderRadius: 14,
          border: `1px solid ${COLORS.border}`,
          width: '100%',
          maxWidth: 440,
          padding: 24,
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 18,
            fontWeight: 700,
            color: COLORS.ink,
            margin: '0 0 16px',
          }}
        >
          {payLink ? t('create.successTitle') : t('create.title')}
        </h2>

        {payLink ? (
          <div>
            <p style={{ fontSize: 13, color: COLORS.muted, margin: '0 0 8px' }}>
              {t('create.linkLabel')}
            </p>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                background: COLORS.paper,
                border: `1px solid ${COLORS.border}`,
                borderRadius: 8,
                padding: '10px 12px',
              }}
            >
              <code style={{ flex: 1, fontSize: 12, color: COLORS.ink, wordBreak: 'break-all' }}>
                {payLink}
              </code>
              <button
                type="button"
                onClick={copyLink}
                style={{ ...btnStyle, background: COLORS.paper, color: COLORS.accent, padding: '4px 8px' }}
              >
                {copied ? t('create.copied') : t('create.copy')}
              </button>
            </div>
            <button
              type="button"
              onClick={onClose}
              style={{ ...btnStyle, background: COLORS.ink, color: COLORS.white, width: '100%', marginTop: 16 }}
            >
              {t('create.done')}
            </button>
          </div>
        ) : (
          <div>
            {/* Org-default (recipient gate) banner — a split defines its own
                recipient set, so the banner only applies to single mode. */}
            {splitOn ? null : settlementWallet ? (
              <div
                style={{
                  fontSize: 12,
                  color: COLORS.muted,
                  background: COLORS.paper,
                  borderRadius: 8,
                  padding: '8px 10px',
                  marginBottom: 16,
                }}
              >
                {t('create.settlesTo')}{' '}
                <code style={{ color: COLORS.ink }}>{truncAddr(settlementWallet)}</code>
              </div>
            ) : (
              <div
                role="alert"
                style={{
                  fontSize: 12,
                  color: COLORS.red,
                  background: COLORS.redLight,
                  borderRadius: 8,
                  padding: '8px 10px',
                  marginBottom: 16,
                }}
              >
                {t('create.noWallet')}{' '}
                <Link href="/settings" style={{ color: COLORS.accent, fontWeight: 600 }}>
                  {t('create.setWalletCta')}
                </Link>
              </div>
            )}

            <div style={{ marginBottom: 14 }}>
              <label style={label} htmlFor="rp-amount">{t('create.amount')}</label>
              <input
                id="rp-amount"
                type="number"
                min="0"
                step="any"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                style={field}
              />
            </div>

            <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
              <div style={{ flex: 1 }}>
                <label style={label} htmlFor="rp-token">{t('create.token')}</label>
                <select id="rp-token" value={token} onChange={(e) => setToken(e.target.value)} style={field}>
                  {CREATE_TOKENS.map((tok) => (
                    <option key={tok} value={tok}>{tok}</option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={label}>{t('create.network')}</label>
                <div style={{ ...field, color: COLORS.muted }}>Base Sepolia</div>
              </div>
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={label} htmlFor="rp-expiry">{t('create.expiry')}</label>
              <select
                id="rp-expiry"
                value={expiry}
                onChange={(e) => setExpiry(Number(e.target.value))}
                style={field}
              >
                {EXPIRY_OPTIONS.map((o) => (
                  <option key={o.minutes} value={o.minutes}>{t(`create.${o.key}`)}</option>
                ))}
              </select>
            </div>

            {/* Split toggle — mutually exclusive with the single override */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <input
                id="rp-split-toggle"
                type="checkbox"
                checked={splitOn}
                onChange={(e) => setSplitOn(e.target.checked)}
                style={{ accentColor: COLORS.accent, width: 15, height: 15 }}
              />
              <label
                htmlFor="rp-split-toggle"
                style={{ fontSize: 13, fontWeight: 600, color: COLORS.ink, cursor: 'pointer' }}
              >
                {t('create.splitToggle')}
              </label>
            </div>

            {splitOn ? (
              <div style={{ marginBottom: 8 }}>
                {/* Preview bar — absolute widths against the 10000-bps track:
                    under-allocation leaves empty track, overflow tints it red */}
                <div
                  aria-hidden
                  style={{
                    display: 'flex',
                    height: 6,
                    borderRadius: 3,
                    overflow: 'hidden',
                    background:
                      balanceBps != null && balanceBps < 1
                        ? COLORS.redLight
                        : COLORS.border,
                    marginBottom: 10,
                  }}
                >
                  {legs.map((_, i) => (
                    <span
                      key={i}
                      style={{
                        width: `${(legBps[i] ?? 0) / 100}%`,
                        // No shrink: an over-allocated bar must NOT be
                        // normalized back to a full clean bar — it clips
                        // and goes red instead.
                        flexShrink: 0,
                        background:
                          balanceBps != null && balanceBps < 1
                            ? COLORS.red
                            : SPLIT_LEG_COLORS[i % SPLIT_LEG_COLORS.length],
                      }}
                    />
                  ))}
                </div>

                {legs.map((leg, i) => (
                  <div
                    key={i}
                    style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}
                  >
                    <input
                      type="text"
                      placeholder="0x…"
                      aria-label={t('create.recipient')}
                      value={leg.address}
                      onChange={(e) => setLeg(i, { address: e.target.value })}
                      style={{ ...field, flex: '3 1 140px' }}
                    />
                    {i < legs.length - 1 ? (
                      <input
                        type="text"
                        inputMode="decimal"
                        aria-label={t('create.splitShare')}
                        value={leg.percent}
                        onChange={(e) => setLeg(i, { percent: e.target.value })}
                        style={{ ...field, flex: 1, minWidth: 74 }}
                      />
                    ) : (
                      <input
                        type="text"
                        readOnly
                        tabIndex={-1}
                        aria-label={t('create.splitShareAuto')}
                        value={balanceOk ? bpsToPercent(balanceBps) : ''}
                        style={{
                          ...field,
                          flex: 1,
                          minWidth: 74,
                          background: COLORS.paper,
                          color: COLORS.muted,
                        }}
                      />
                    )}
                    {amountValid && legBps[i] != null && (
                      <span
                        style={{
                          fontSize: 11,
                          color: COLORS.muted,
                          alignSelf: 'center',
                          whiteSpace: 'nowrap',
                          minWidth: 64,
                          textAlign: 'right',
                          // On narrow widths the row wraps: payout + Remove
                          // drop to a right-aligned second line instead of
                          // crushing the address input.
                          marginLeft: 'auto',
                          fontFamily: 'var(--font-mono, monospace)',
                        }}
                      >
                        ≈ {AMOUNT_FMT.format(payoutAmount(amountNum, legBps[i] as number))}{' '}
                        {token}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        setLegs((prev) =>
                          prev.length > SPLIT_MIN ? prev.filter((_, j) => j !== i) : prev,
                        )
                      }
                      disabled={legs.length <= SPLIT_MIN}
                      style={{
                        ...btnStyle,
                        background: 'transparent',
                        color: legs.length > SPLIT_MIN ? COLORS.red : COLORS.subtle,
                        padding: '4px 6px',
                        fontSize: 12,
                        cursor: legs.length > SPLIT_MIN ? 'pointer' : 'not-allowed',
                      }}
                    >
                      {t('create.splitRemove')}
                    </button>
                  </div>
                ))}

                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: 4,
                  }}
                >
                  <button
                    type="button"
                    onClick={() =>
                      // New rows are manual: insert ABOVE the balance row so
                      // the last row keeps auto-balancing.
                      setLegs((prev) =>
                        prev.length < SPLIT_MAX
                          ? [
                              ...prev.slice(0, -1),
                              { address: '', percent: '' },
                              prev[prev.length - 1],
                            ]
                          : prev,
                      )
                    }
                    disabled={legs.length >= SPLIT_MAX}
                    style={{
                      ...btnStyle,
                      background: COLORS.paper,
                      color: COLORS.accent,
                      padding: '5px 10px',
                      fontSize: 12,
                    }}
                  >
                    {t('create.splitAdd')}
                  </button>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono, monospace)',
                      color: bpsSum === BPS_TOTAL ? COLORS.ink : COLORS.red,
                    }}
                  >
                    {t('create.splitTotal')}: {bpsToPercent(bpsSum)}%
                  </span>
                </div>
                <p
                  style={{
                    fontSize: 11,
                    color: splitError ? COLORS.red : COLORS.subtle,
                    margin: '6px 0 0',
                  }}
                >
                  {t(`create.${splitError ?? 'splitHelp'}`)}
                </p>
              </div>
            ) : (
              <div style={{ marginBottom: 8 }}>
                <label style={label} htmlFor="rp-recipient">{t('create.recipient')}</label>
                <input
                  id="rp-recipient"
                  type="text"
                  placeholder="0x…"
                  value={recipient}
                  onChange={(e) => setRecipient(e.target.value)}
                  style={field}
                />
                <p style={{ fontSize: 11, color: COLORS.subtle, margin: '6px 0 0' }}>
                  {t('create.recipientHelp')}
                </p>
                {!overrideValid && (
                  <p style={{ fontSize: 11, color: COLORS.red, margin: '4px 0 0' }}>
                    {t('create.invalidRecipient')}
                  </p>
                )}
              </div>
            )}

            {err && (
              <p role="alert" style={{ fontSize: 12, color: COLORS.red, margin: '8px 0 0' }}>{err}</p>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
              <button
                type="button"
                onClick={onClose}
                style={{ ...btnStyle, background: COLORS.paper, color: COLORS.ink, flex: 1 }}
              >
                {t('create.close')}
              </button>
              <button
                type="button"
                onClick={submit}
                disabled={!canSubmit}
                style={{
                  ...btnStyle,
                  background: canSubmit ? COLORS.accent : COLORS.border,
                  color: canSubmit ? COLORS.white : COLORS.subtle,
                  flex: 2,
                  cursor: canSubmit ? 'pointer' : 'not-allowed',
                }}
              >
                {submitting ? t('create.submitting') : t('create.submit')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
