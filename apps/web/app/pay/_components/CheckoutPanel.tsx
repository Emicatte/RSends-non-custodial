'use client'

/**
 * app/pay/_components/CheckoutPanel.tsx — params-driven non-custodial checkout.
 *
 * Renders the payment request (token, principal, on-chain fee, total, merchant)
 * and drives the wallet flow via usePayFlow. On success it parses the receipt's
 * PaymentMade + Transfer logs to prove principal→merchant and fee→feeCollector,
 * with a BaseScan link.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { formatUnits } from 'viem'
import { C } from '@/app/designTokens'
import { usePayFlow } from '@/lib/web3/usePayFlow'
import type { PaymentRequest } from '@/lib/web3/payParams'
import {
  Card, Mono, AddressChip, PrimaryButton, Spinner, NonCustodialNote, ErrorText,
  Eyebrow, TestnetBadge, txLink, truncate,
} from './payUi'

/** EUR/USD from the decoupled /api/prices route (display only). */
function useEurUsd(): number | null {
  const [rate, setRate] = useState<number | null>(null)
  useEffect(() => {
    let active = true
    fetch('/api/prices')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (active && d?.rates?.USD && Number.isFinite(d.rates.USD)) setRate(d.rates.USD)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])
  return rate
}

export default function CheckoutPanel({ request }: { request: PaymentRequest }) {
  const { token, merchant, ref } = request
  const flow = usePayFlow(request)
  const eurUsd = useEurUsd()

  const fmt = (v: bigint) => formatUnits(v, token.decimals)
  // EUR estimate: USDC ≈ USD → divide by EUR/USD. EUR-pegged tokens are 1:1.
  const toEur = (v: bigint): string | null => {
    const amt = Number(formatUnits(v, token.decimals))
    if (!Number.isFinite(amt)) return null
    const eur = token.symbol === 'EURC' ? amt : eurUsd ? amt / eurUsd : null
    return eur == null ? null : `≈ €${eur.toFixed(2)}`
  }

  return (
    <Card>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Eyebrow>Pay with RSends</Eyebrow>
          {/* Single figure shown to the payer: the total the wallet will
              charge (on-chain quote). Ellipsis while quoting — the bare
              principal is never presented as the charge. */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <Mono style={{ fontSize: 34, fontWeight: 500, color: C.text }}>
              {flow.total != null ? fmt(flow.total) : '…'}
            </Mono>
            <span style={{ fontFamily: C.D, fontSize: 18, color: C.sub }}>{token.symbol}</span>
            {flow.total != null && toEur(flow.total) && (
              <span style={{ fontFamily: C.M, fontSize: 13, color: C.sub }}>{toEur(flow.total)}</span>
            )}
          </div>
        </div>

        {/* Merchant + ref */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Row label="To merchant" value={<AddressChip address={merchant} />} />
          {ref && <Row label="Reference" value={<Mono style={{ fontSize: 13, color: C.text }}>{ref}</Mono>} />}
        </div>

        {flow.phase === 'confirmed' ? (
          <ConfirmedView flow={flow} symbol={token.symbol} fmt={fmt} />
        ) : (
          <ActionArea flow={flow} symbol={token.symbol} fmt={fmt} />
        )}

        <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
          <NonCustodialNote />
        </div>
      </div>
    </Card>
  )
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>{label}</span>
      <span style={{ display: 'inline-flex', alignItems: 'center' }}>{value}</span>
    </div>
  )
}

function ActionArea({
  flow, symbol, fmt,
}: {
  flow: ReturnType<typeof usePayFlow>
  symbol: string
  fmt: (v: bigint) => string
}) {
  const payLabel = flow.total != null ? `Pay ${fmt(flow.total)} ${symbol}` : 'Pay'

  let action: ReactNode
  switch (flow.phase) {
    case 'connect':
      action = (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
          <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.sub, textAlign: 'center' }}>
            Connect your wallet to pay the merchant directly.
          </p>
          <ConnectButton chainStatus="none" showBalance={false} label="Connect wallet" />
        </div>
      )
      break
    case 'wrongNetwork':
      action = (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PrimaryButton onClick={flow.switchToChain} disabled={flow.busy}>
            {flow.busy ? 'Switching…' : 'Switch to Base Sepolia'}
          </PrimaryButton>
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <ConnectButton chainStatus="icon" showBalance={false} accountStatus="address" />
          </div>
        </div>
      )
      break
    case 'quoting':
      action = <BusyButton label="Preparing payment…" />
      break
    case 'needsApprove':
      action = (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <PrimaryButton onClick={flow.approve} disabled={flow.busy}>
            Approve {symbol}
          </PrimaryButton>
          <p style={{ margin: 0, fontFamily: C.D, fontSize: 11.5, color: C.sub, textAlign: 'center' }}>
            Step 1 of 2 — approve exactly {flow.total != null ? fmt(flow.total) : ''} {symbol}, then pay.
          </p>
        </div>
      )
      break
    case 'approving':
      action = (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <BusyButton label="Approving…" />
          {flow.approveHash && <TxInlineLink hash={flow.approveHash} label="Approval tx" />}
        </div>
      )
      break
    case 'paying':
      action = (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
          <BusyButton label="Confirming payment…" />
          {flow.payHash && <TxInlineLink hash={flow.payHash} label="Payment tx" />}
        </div>
      )
      break
    case 'ready':
    default:
      action = (
        <PrimaryButton onClick={flow.pay} disabled={flow.busy || flow.total == null}>
          {payLabel}
        </PrimaryButton>
      )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {action}
      {flow.error && <ErrorText>{flow.error}</ErrorText>}
    </div>
  )
}

function BusyButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      disabled
      style={{
        width: '100%',
        borderRadius: 12,
        padding: '13px 18px',
        fontFamily: C.D,
        fontSize: 15,
        fontWeight: 600,
        color: C.text,
        background: 'transparent',
        border: `1px solid ${C.border}`,
        opacity: 0.85,
        cursor: 'wait',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
      }}
    >
      <Spinner /> {label}
    </button>
  )
}

function TxInlineLink({ hash, label }: { hash: string; label: string }) {
  return (
    <a
      href={txLink(hash)}
      target="_blank"
      rel="noopener noreferrer"
      style={{ display: 'inline-flex', gap: 6, alignItems: 'center', justifyContent: 'center', fontFamily: C.M, fontSize: 12, color: C.purple, textDecoration: 'none' }}
    >
      {label}: {truncate(hash, 10, 8)} ↗
    </a>
  )
}

function ConfirmedView({
  flow, symbol, fmt,
}: {
  flow: ReturnType<typeof usePayFlow>
  symbol: string
  fmt: (v: bigint) => string
}) {
  const p = flow.parsed
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center', animation: 'fadeIn 0.3s ease-out' }}>
      <div
        style={{
          width: 52, height: 52, borderRadius: '50%',
          background: 'rgba(0,214,143,0.12)', color: C.green,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 26, fontWeight: 700,
        }}
      >
        ✓
      </div>
      <h2 style={{ margin: 0, fontFamily: C.D, fontSize: 20, fontWeight: 600, color: C.text }}>Payment confirmed</h2>

      {p && (
        <div
          style={{
            width: '100%', border: `1px solid ${C.border}`, borderRadius: 12,
            padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 9, background: C.bg,
          }}
        >
          <SettledRow
            label="Total paid"
            value={`${fmt(p.paymentMade.amount + p.paymentMade.fee)} ${symbol}`}
            to={p.principalTransfer?.to ?? p.paymentMade.merchant}
          />
        </div>
      )}

      {flow.payHash && (
        <a
          href={txLink(flow.payHash)}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontFamily: C.M, fontSize: 12.5, color: C.purple, textDecoration: 'none' }}
        >
          View on BaseScan: {truncate(flow.payHash, 10, 8)} ↗
        </a>
      )}
    </div>
  )
}

function SettledRow({ label, value, to }: { label: string; value: string; to?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>{label}</span>
        {to && <span style={{ fontFamily: C.M, fontSize: 11, color: C.sub }}>{truncate(to)}</span>}
      </div>
      <Mono style={{ fontSize: 13, color: C.text }}>{value}</Mono>
    </div>
  )
}
