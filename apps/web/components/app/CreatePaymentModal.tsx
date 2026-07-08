'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { isAddress } from 'viem'
import { Link } from '@/i18n/navigation'
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
  const canSubmit = amountValid && overrideValid && hasRecipient && !submitting

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
        ...(override ? { recipient: override } : {}),
      })
      const origin = typeof window !== 'undefined' ? window.location.origin : ''
      setPayLink(`${origin}/pay/${created.intent_id}`)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      // The session create's only 422 is the recipient gate; apiCall surfaces it
      // as "HTTP 422" (the detail uses `error`, not `code`).
      setErr(code === 'HTTP 422' ? t('create.errors.gate') : t('create.errors.generic'))
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
            {/* Org-default (recipient gate) banner */}
            {settlementWallet ? (
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
