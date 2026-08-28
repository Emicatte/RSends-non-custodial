'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { isAddress } from 'viem'
import { Link } from '@/i18n/navigation'
import {
  amountsToSharesBps,
  amountToBase,
  formatBase,
  onchainAmounts,
  remainderBase,
} from '@/lib/splitShares'
import {
  CREATE_CHAIN,
  CREATE_TOKENS,
  CREATE_TOKEN_DECIMALS,
  type CreatePrefill,
} from '@/lib/repeatPrefill'
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

// CREATE_CHAIN / CREATE_TOKENS / CREATE_TOKEN_DECIMALS now live in
// lib/repeatPrefill.ts (imported above) so the repeat-prefill gate and this form
// read ONE registry: a row is offered for repeat on exactly the terms this form
// can honour.
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

// ── Split (non-custodial, amounts in / BPS out) ──────────────────
// The merchant enters AMOUNTS per recipient, never percentages. Rows above
// the LAST one are manual; the last row balances to `total − sum(manual)`,
// so the amounts sum to the Amount field by construction. Contract bps are
// derived from the amount ratios (sum EXACTLY 10000, drift absorbed on
// recipient 0 — the leg the contract's remainder rule favors). The server
// 422 stays authoritative.
const SPLIT_MIN = 2
const SPLIT_MAX = 20
const SPLIT_LEG_COLORS = ['#C45A3C', '#3B82F6', '#00B27A', '#D99A2B'] as const

interface SplitLegDraft {
  address: string
  amount: string
}

export function CreatePaymentModal({
  settlementWallet,
  initialValues,
  onCreate,
  onClose,
}: {
  settlementWallet: string | null
  /** Seed values for a "repeat" of an existing request. Already validated
   * fail-closed by `resolveRepeatPrefill` — the modal simply starts from them,
   * re-derives everything as usual, and leaves every field editable. Expiry is
   * deliberately NOT seedable: a repeat always gets a fresh default window. */
  initialValues?: CreatePrefill
  onCreate: (input: CreateInvoiceInput) => Promise<CreatedInvoice>
  onClose: () => void
}) {
  const t = useTranslations('app.payments')
  const [amount, setAmount] = useState(initialValues?.amount ?? '')
  const [token, setToken] = useState<string>(initialValues?.token ?? 'USDC')
  const [expiry, setExpiry] = useState<number>(30)
  const [recipient, setRecipient] = useState(initialValues?.recipient ?? '')
  const [splitOn, setSplitOn] = useState(Boolean(initialValues?.splitLegs))
  // In single mode the recipient is IMPLICIT — the org settlement wallet,
  // resolved server-side, never typed. A split sets `recipient` to NULL and the
  // legs become the COMPLETE recipient set, so the settlement wallet receives
  // nothing unless it is explicitly one of them. Seed row one with it so the
  // common case is right by default; it stays removable like any other row,
  // because a pass-through platform taking nothing is legitimate and silently
  // inserting the merchant would be the opposite error. Only the ADDRESS is
  // seeded — prefilling never rewrites a share the merchant already entered.
  //
  // A lazy initializer, not an effect: /app/payments gates the "New payment"
  // button on a role that comes from the same `activeOrg`, so the modal cannot
  // mount before the org resolves — there is nothing to wait for, and nothing
  // that could re-add a row the merchant removed.
  //
  // A repeat seeds the legs from the source intent instead. Its amounts are the
  // contract-mirror figures for the stored shares, so the last row's balance
  // lands back on the source's last leg and the derived bps below come out
  // bit-identical to what was stored.
  const [legs, setLegs] = useState<SplitLegDraft[]>(
    () =>
      initialValues?.splitLegs?.map((leg) => ({
        address: leg.address,
        amount: leg.amount,
      })) ?? [
        { address: settlementWallet ?? '', amount: '' },
        { address: '', amount: '' },
      ],
  )
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

  // Split validity — amounts in, bps derived. A valid split set IS the
  // recipient set: no settlement wallet needed. Manual rows are everything
  // above the last; the last row balances to the total in currency, so
  // sum(amounts) === total is an exact base-unit identity by construction.
  const decimals = CREATE_TOKEN_DECIMALS[token] ?? 18
  const totalBase = amountToBase(amount, decimals)
  const manualBase = legs.slice(0, -1).map((leg) => amountToBase(leg.amount, decimals))
  const balanceBase = totalBase != null ? remainderBase(totalBase, manualBase) : null
  const legAddrs = legs.map((leg) => leg.address.trim())
  // Which legs are the merchant's own wallet. DERIVED, never a "this row was
  // prefilled" flag: it survives add/remove/overwrite and also marks the wallet
  // when the merchant types it in by hand. Case-insensitive — the wallet is
  // stored lowercase but merchants paste the checksummed form out of a wallet
  // UI, and a raw compare would accuse someone who DID include themselves.
  const ownWallet = settlementWallet ? settlementWallet.toLowerCase() : null
  const legIsOwn = legAddrs.map(
    (a) => ownWallet !== null && a.toLowerCase() === ownWallet,
  )
  const addrsValid = legAddrs.every((a) => isAddress(a))
  const addrsUnique =
    new Set(legAddrs.map((a) => a.toLowerCase())).size === legAddrs.length
  const amountsParsed = manualBase.every((b) => b != null)
  const balanceOk = balanceBase != null && balanceBase > 0n
  const sharesBps =
    totalBase != null && balanceOk && amountsParsed
      ? amountsToSharesBps([...(manualBase as bigint[]), balanceBase], totalBase)
      : null
  const splitValid =
    legs.length >= SPLIT_MIN &&
    legs.length <= SPLIT_MAX &&
    addrsValid &&
    addrsUnique &&
    sharesBps != null
  // The contract mirror: what each leg actually receives on-chain. A row
  // shows its ≈ figure ONLY when the typed amount is not a clean bps
  // fraction of the total (exact rows show nothing extra).
  const onchain =
    sharesBps != null && totalBase != null ? onchainAmounts(totalBase, sharesBps) : null
  const legPreview = legs.map((_, i) => {
    if (onchain == null) return null
    const typed = i < legs.length - 1 ? manualBase[i] : balanceBase
    if (typed == null || onchain[i] === typed) return null
    return `≈ ${formatBase(onchain[i], decimals)} ${token}`
  })
  // Bar widths: derived bps when valid; else raw amount/total proportions so
  // an over-allocated bar still clips full red instead of emptying out.
  const legWidthPct = legs.map((_, i) => {
    if (sharesBps != null) return sharesBps[i] / 100
    if (totalBase == null || totalBase <= 0n) return 0
    const base = i < legs.length - 1 ? manualBase[i] : balanceBase
    if (base == null || base <= 0n) return 0
    return Number((base * 10000n) / totalBase) / 100
  })
  // Currency total line: the assigned sum, red unless it equals the total.
  const assignedBase =
    totalBase != null && balanceOk && amountsParsed
      ? totalBase
      : manualBase.reduce<bigint>((acc, b) => acc + (b ?? 0n), 0n)
  const assignedMatches = totalBase != null && assignedBase === totalBase && balanceOk
  // One failure names itself — never blame the sum for an address problem.
  const splitError = !addrsValid
    ? 'splitErrorAddress'
    : !addrsUnique
      ? 'splitErrorDuplicate'
      : amountValid && totalBase == null
        ? 'splitErrorTotal'
        : !amountsParsed
          ? 'splitErrorAmount'
          : balanceBase != null && balanceBase <= 0n
            ? 'splitErrorExceeds'
            : totalBase != null && balanceOk && sharesBps == null
              ? 'splitErrorTiny'
              : null

  // `totalBase` is what enforces the token's decimal scale (amountToBase rejects
  // excess digits rather than rounding). Split mode already required it via
  // splitValid; single mode did not, so the backend's AMOUNT_PRECISION_EXCEEDED
  // was the first thing that noticed. Both modes now block on the same value.
  const canSubmit =
    amountValid &&
    totalBase != null &&
    !submitting &&
    (splitOn ? splitValid : overrideValid && hasRecipient)

  // About to pay everyone but yourself. This WARNS and never blocks — it is not
  // a mistake, only usually one. Gated on an otherwise-submittable split so it
  // lands at the moment of confirmation instead of shouting through every
  // keystroke. A null wallet (unknown, or none set) makes NO claim: absence of
  // data is not evidence of exclusion.
  const selfExcluded =
    splitOn &&
    amountValid &&
    splitValid &&
    ownWallet !== null &&
    !legIsOwn.some(Boolean)

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
                share_bps: (sharesBps as number[])[i],
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
            {/* Where the money lands. "Settles to" is SINGLE-mode only — under
                a split the legs are the recipient set and the claim would be
                false. The set-a-wallet prompt survives BOTH modes: a merchant
                with no settlement wallet is the likeliest accidental
                self-excluder, and hiding it under the split toggle left them
                with no recipient information at all. */}
            {settlementWallet ? (
              splitOn ? null : (
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
              )
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
              {/* Split mode says this under its own recipient list; single mode
                  had nowhere to say it, so an over-precision amount reached the
                  server and came back a bare 400. Same message, same treatment. */}
              {!splitOn && amountValid && totalBase == null && (
                <p style={{ fontSize: 11, color: COLORS.red, margin: '6px 0 0' }}>
                  {t('create.splitErrorTotal')}
                </p>
              )}
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
                {/* Preview bar — absolute widths from the derived bps:
                    under-allocation leaves empty track, overflow tints it red */}
                <div
                  aria-hidden
                  style={{
                    display: 'flex',
                    height: 6,
                    borderRadius: 3,
                    overflow: 'hidden',
                    background:
                      balanceBase != null && balanceBase <= 0n
                        ? COLORS.redLight
                        : COLORS.border,
                    marginBottom: 10,
                  }}
                >
                  {legs.map((_, i) => (
                    <span
                      key={i}
                      style={{
                        width: `${legWidthPct[i]}%`,
                        // No shrink: an over-allocated bar must NOT be
                        // normalized back to a full clean bar — it clips
                        // and goes red instead.
                        flexShrink: 0,
                        background:
                          balanceBase != null && balanceBase <= 0n
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
                    {/* Address + its marker share one flex slot so the marker
                        is unambiguously attached to THIS address, including
                        when the row wraps on a narrow screen. An address alone
                        is not recognisable — merchants do not read hex. */}
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 2,
                        flex: '3 1 140px',
                      }}
                    >
                      <input
                        type="text"
                        placeholder="0x…"
                        aria-label={t('create.recipient')}
                        value={leg.address}
                        onChange={(e) => setLeg(i, { address: e.target.value })}
                        style={field}
                      />
                      {legIsOwn[i] && (
                        <span
                          style={{ fontSize: 11, fontWeight: 600, color: COLORS.accent }}
                        >
                          {t('create.splitOwnWallet')}
                        </span>
                      )}
                    </div>
                    {i < legs.length - 1 ? (
                      <input
                        type="text"
                        inputMode="decimal"
                        aria-label={t('create.splitAmount')}
                        value={leg.amount}
                        onChange={(e) => setLeg(i, { amount: e.target.value })}
                        style={{ ...field, flex: 1, minWidth: 74 }}
                      />
                    ) : (
                      <input
                        type="text"
                        readOnly
                        tabIndex={-1}
                        aria-label={t('create.splitAmountAuto')}
                        value={balanceOk ? formatBase(balanceBase, decimals) : ''}
                        style={{
                          ...field,
                          flex: 1,
                          minWidth: 74,
                          background: COLORS.paper,
                          color: COLORS.muted,
                        }}
                      />
                    )}
                    {legPreview[i] != null && (
                      <span
                        style={{
                          fontSize: 11,
                          color: COLORS.muted,
                          alignSelf: 'center',
                          whiteSpace: 'nowrap',
                          minWidth: 64,
                          textAlign: 'right',
                          // On narrow widths the row wraps: preview + Remove
                          // drop to a right-aligned second line instead of
                          // crushing the address input.
                          marginLeft: 'auto',
                          fontFamily: 'var(--font-mono, monospace)',
                        }}
                      >
                        {legPreview[i]}
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
                              { address: '', amount: '' },
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
                      color: assignedMatches ? COLORS.ink : COLORS.red,
                    }}
                  >
                    {t('create.splitTotal')}: {formatBase(assignedBase, decimals)} {token}
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

            {/* Immediately above the confirm buttons — where the eye already is
                when confirming. Never a tooltip, never below the fold: this
                screen writes instructions for an irreversible transfer. */}
            {selfExcluded && (
              <div
                role="alert"
                style={{
                  fontSize: 12,
                  color: COLORS.red,
                  background: COLORS.redLight,
                  borderRadius: 8,
                  padding: '8px 10px',
                  marginTop: 12,
                }}
              >
                {t('create.splitSelfExcluded')}
              </div>
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
