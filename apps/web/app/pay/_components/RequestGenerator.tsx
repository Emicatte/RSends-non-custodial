'use client'

/**
 * app/pay/_components/RequestGenerator.tsx — shareable payment-request builder.
 *
 * Shown when /pay has no params. Merchant picks a token (enabled only; EURC is
 * shown disabled "coming soon"), amount, receiving address and optional ref →
 * produces a copyable /pay?… link. Pure client-side; no backend.
 */
import { useMemo, useState, type CSSProperties } from 'react'
import { isAddress } from 'viem'
import { C } from '@/app/designTokens'
import { getEnabledPayTokens, PAY_TOKENS } from '@/lib/web3/payTokens'
import { buildPayUrl } from '@/lib/web3/payParams'
import { Card, Eyebrow, PrimaryButton, CopyButton, Mono } from './payUi'

export default function RequestGenerator() {
  const enabled = getEnabledPayTokens()
  const comingSoon = PAY_TOKENS.filter((t) => t.comingSoon)
  const [token, setToken] = useState(enabled[0]?.symbol ?? 'USDC')
  const [amount, setAmount] = useState('')
  const [to, setTo] = useState('')
  const [ref, setRef] = useState('')

  const amountValid = /^\d+(\.\d+)?$/.test(amount.trim()) && Number(amount) > 0
  const toValid = isAddress(to.trim())
  const valid = amountValid && toValid

  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const link = useMemo(
    () => (valid ? buildPayUrl({ token, amount: amount.trim(), to: to.trim(), ref: ref.trim() }, origin) : ''),
    [valid, token, amount, to, ref, origin],
  )

  return (
    <Card>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Eyebrow>Payment request</Eyebrow>
          <h1 style={{ margin: 0, fontFamily: C.D, fontSize: 24, fontWeight: 600, color: C.text }}>
            Create a payment link
          </h1>
          <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.sub, lineHeight: 1.5 }}>
            Share a link your customer opens to pay you directly on-chain. RSends never holds the funds.
          </p>
        </div>

        <Field label="Token">
          <select value={token} onChange={(e) => setToken(e.target.value)} style={inputStyle}>
            {enabled.map((t) => (
              <option key={t.symbol} value={t.symbol}>{t.symbol} — {t.name}</option>
            ))}
            {comingSoon.map((t) => (
              <option key={t.symbol} value={t.symbol} disabled>{t.symbol} — coming soon</option>
            ))}
          </select>
        </Field>

        <Field label="Amount" hint={amount && !amountValid ? 'Enter a positive number' : undefined}>
          <input
            inputMode="decimal"
            placeholder="100"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            style={{ ...inputStyle, fontFamily: C.M }}
          />
        </Field>

        <Field label="Merchant address" hint={to && !toValid ? 'Enter a valid 0x address' : undefined}>
          <input
            placeholder="0x…"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            style={{ ...inputStyle, fontFamily: C.M }}
          />
        </Field>

        <Field label="Reference (optional)">
          <input
            placeholder="INV-001"
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            style={{ ...inputStyle, fontFamily: C.M }}
          />
        </Field>

        {valid ? (
          <div
            style={{
              border: `1px solid ${C.border}`, borderRadius: 12, padding: '12px 14px',
              display: 'flex', flexDirection: 'column', gap: 8, background: C.bg,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontFamily: C.D, fontSize: 12, color: C.sub }}>Shareable link</span>
              <CopyButton value={link} label="Copy link" />
            </div>
            <Mono style={{ fontSize: 12, color: C.text, wordBreak: 'break-all', lineHeight: 1.5 }}>{link}</Mono>
            <a
              href={link}
              style={{ fontFamily: C.M, fontSize: 12, color: C.purple, textDecoration: 'none' }}
            >
              Open checkout ↗
            </a>
          </div>
        ) : (
          <PrimaryButton disabled>Enter amount and merchant address</PrimaryButton>
        )}
      </div>
    </Card>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ fontFamily: C.D, fontSize: 12.5, fontWeight: 500, color: C.text }}>{label}</span>
      {children}
      {hint && <span style={{ fontFamily: C.D, fontSize: 11.5, color: C.red }}>{hint}</span>}
    </label>
  )
}

const inputStyle: CSSProperties = {
  width: '100%',
  borderRadius: 10,
  border: `1px solid ${C.border}`,
  background: C.surface,
  color: C.text,
  fontSize: 14,
  padding: '11px 13px',
  outline: 'none',
}
