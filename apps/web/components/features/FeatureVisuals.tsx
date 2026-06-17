// components/features/FeatureVisuals.tsx
//
// Pure, presentational, brand-styled mock visuals — one per feature page.
// No real data, no hooks, no wallet/network deps. Styling mirrors the app's
// existing visual language (status pills, chain dots, terracotta tints) using
// the shared design tokens in app/designTokens.ts.

import type { ReactElement, ReactNode } from 'react'
import { C } from '@/app/designTokens'
import type { FeatureKey } from '@/lib/features'

// ── Shared bits ────────────────────────────────────────────────────────────

const CHAIN_COLOR: Record<string, string> = {
  Base: '#0052FF',
  Arbitrum: '#12AAFF',
  Ethereum: '#627EEA',
  Tron: '#E24B4A',
  Solana: '#7F77DD',
}

function VisualFrame({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      style={{
        background: C.surface,
        border: '1px solid rgba(200,81,44,0.15)',
        borderRadius: 16,
        padding: 20,
        width: '100%',
        boxShadow: '0 1px 2px rgba(10,10,10,0.03)',
      }}
    >
      <div
        style={{
          fontFamily: C.M,
          fontSize: 10,
          letterSpacing: '0.14em',
          color: C.purple,
          fontWeight: 600,
          marginBottom: 16,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  )
}

function ChainBadge({ chain }: { chain: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: CHAIN_COLOR[chain] ?? C.purple,
          display: 'inline-block',
          flexShrink: 0,
        }}
      />
      <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 500, color: C.text }}>{chain}</span>
    </span>
  )
}

type StatusKey = 'confirmed' | 'pending' | 'failed'
const STATUS: Record<StatusKey, { bg: string; fg: string; label: string }> = {
  confirmed: { bg: 'rgba(45,134,89,0.10)', fg: '#2D8659', label: 'Confirmed' },
  pending: { bg: 'rgba(217,122,46,0.10)', fg: '#D97A2E', label: 'Pending' },
  failed: { bg: 'rgba(192,58,58,0.10)', fg: '#C03A3A', label: 'Failed' },
}

function StatusPill({ status }: { status: StatusKey }) {
  const s = STATUS[status]
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 8px',
        borderRadius: 6,
        background: s.bg,
        color: s.fg,
        fontFamily: C.D,
        fontSize: 11,
        fontWeight: 700,
      }}
    >
      {s.label}
    </span>
  )
}

type Tone = 'terracotta' | 'amber' | 'blue' | 'neutral'
const TONES: Record<Tone, { bg: string; fg: string; bd: string }> = {
  terracotta: { bg: 'rgba(200,81,44,0.10)', fg: C.purple, bd: 'rgba(200,81,44,0.22)' },
  amber: { bg: 'rgba(255,181,71,0.12)', fg: '#B47A1E', bd: 'rgba(255,181,71,0.30)' },
  blue: { bg: 'rgba(59,130,246,0.10)', fg: '#2563EB', bd: 'rgba(59,130,246,0.22)' },
  neutral: { bg: 'rgba(10,10,10,0.05)', fg: 'rgba(10,10,10,0.55)', bd: 'rgba(10,10,10,0.10)' },
}

function Tag({ children, tone = 'terracotta' }: { children: ReactNode; tone?: Tone }) {
  const t = TONES[tone]
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 999,
        background: t.bg,
        border: `1px solid ${t.bd}`,
        color: t.fg,
        fontFamily: C.D,
        fontSize: 11,
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

function Arrow() {
  return (
    <span aria-hidden style={{ color: 'rgba(10,10,10,0.3)', fontSize: 14, lineHeight: 1 }}>
      →
    </span>
  )
}

// ── 1) Saved routes — a reusable cross-chain route ──────────────────────────

function RouteNode({ chain, token }: { chain: string; token: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        padding: '8px 12px',
        borderRadius: 10,
        background: C.bg,
        border: '1px solid rgba(10,10,10,0.08)',
      }}
    >
      <ChainBadge chain={chain} />
      <span style={{ color: 'rgba(10,10,10,0.3)' }}>·</span>
      <span style={{ fontFamily: C.M, fontSize: 12, fontWeight: 600, color: C.text }}>{token}</span>
    </span>
  )
}

function SwapNode() {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 12px',
        borderRadius: 10,
        background: 'rgba(200,81,44,0.06)',
        border: '1px solid rgba(200,81,44,0.18)',
      }}
    >
      <span aria-hidden style={{ color: C.purple, fontSize: 13, lineHeight: 1 }}>
        ⇄
      </span>
      <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.purple }}>Swap</span>
    </span>
  )
}

function SavedRoutesVisual(): ReactElement {
  return (
    <VisualFrame label="SAVED ROUTE · PAYROLL">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <RouteNode chain="Base" token="USDC" />
        <Arrow />
        <SwapNode />
        <Arrow />
        <RouteNode chain="Arbitrum" token="USDC" />
      </div>
      <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag tone="terracotta">Split ×6</Tag>
        <span style={{ fontFamily: C.D, fontSize: 12, color: C.sub }}>6 recipients · reusable</span>
      </div>
    </VisualFrame>
  )
}

// ── 2) Cross-device history — a mini transactions table ─────────────────────

interface Row {
  token: string
  chain: string
  status: StatusKey
  amount: string
  date: string
}
const HISTORY: Row[] = [
  { token: 'USDC', chain: 'Arbitrum', status: 'confirmed', amount: '5,000', date: 'Apr 2' },
  { token: 'USDT', chain: 'Tron', status: 'confirmed', amount: '1,200', date: 'Apr 1' },
  { token: 'DAI', chain: 'Base', status: 'failed', amount: '800', date: 'Mar 30' },
  { token: 'USDC', chain: 'Ethereum', status: 'pending', amount: '2,400', date: 'Mar 29' },
]

function CrossDeviceHistoryVisual(): ReactElement {
  const th: React.CSSProperties = {
    textAlign: 'left',
    padding: '8px 10px',
    borderBottom: '1px solid #e5e4e0',
    fontFamily: C.D,
    fontSize: 10,
    fontWeight: 700,
    color: 'rgba(10,10,10,0.5)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    whiteSpace: 'nowrap',
  }
  const td: React.CSSProperties = {
    padding: '9px 10px',
    borderBottom: '1px solid #f0efec',
    fontFamily: C.D,
    fontSize: 12,
    color: C.text,
    whiteSpace: 'nowrap',
  }
  return (
    <VisualFrame label="TRANSACTION HISTORY">
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={th}>Token</th>
              <th style={th}>Chain</th>
              <th style={th}>Status</th>
              <th style={{ ...th, textAlign: 'right' }}>Amount</th>
              <th style={{ ...th, textAlign: 'right' }}>Date</th>
            </tr>
          </thead>
          <tbody>
            {HISTORY.map((r, i) => (
              <tr key={i}>
                <td style={{ ...td, fontFamily: C.M, fontWeight: 600 }}>{r.token}</td>
                <td style={td}>
                  <ChainBadge chain={r.chain} />
                </td>
                <td style={td}>
                  <StatusPill status={r.status} />
                </td>
                <td style={{ ...td, textAlign: 'right', fontFamily: C.M }}>{r.amount}</td>
                <td style={{ ...td, textAlign: 'right', color: C.sub }}>{r.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </VisualFrame>
  )
}

// ── 3) Encrypted contacts — an address-book row with a safety warning ───────

function EncryptedContactsVisual(): ReactElement {
  return (
    <VisualFrame label="ADDRESS BOOK">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span
          style={{
            width: 36,
            height: 36,
            borderRadius: '50%',
            background: 'rgba(200,81,44,0.10)',
            color: C.purple,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: C.D,
            fontSize: 15,
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          A
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text }}>
            Acme Treasury
          </span>
          <span style={{ fontFamily: C.M, fontSize: 12, color: C.sub }}>TXk9…b2Fa</span>
        </div>
        <span style={{ marginLeft: 'auto' }}>
          <ChainBadge chain="Tron" />
        </span>
      </div>
      <div style={{ marginTop: 14 }}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 10px',
            borderRadius: 8,
            background: 'rgba(255,181,71,0.10)',
            border: '1px solid rgba(255,181,71,0.30)',
            fontFamily: C.D,
            fontSize: 11,
            fontWeight: 600,
            color: '#B47A1E',
          }}
        >
          <span aria-hidden>⚠️</span> Chain mismatch — sending USDC on Arbitrum
        </span>
      </div>
    </VisualFrame>
  )
}

// ── 4) Smart notifications — a delivered alert ──────────────────────────────

function SmartNotificationsVisual(): ReactElement {
  return (
    <VisualFrame label="NOTIFICATION">
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <span
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: 'rgba(45,134,89,0.12)',
            color: '#2D8659',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 15,
            flexShrink: 0,
          }}
          aria-hidden
        >
          ✓
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
          <span style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text }}>
            Payment confirmed
          </span>
          <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>
            5,000 USDC on Arbitrum
          </span>
        </div>
        <span style={{ marginLeft: 'auto', fontFamily: C.M, fontSize: 11, color: C.sub, whiteSpace: 'nowrap' }}>
          2:14 PM
        </span>
      </div>
      <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag tone="blue">✈ Telegram</Tag>
        <span style={{ fontFamily: C.D, fontSize: 12, color: C.sub }}>delivered</span>
      </div>
    </VisualFrame>
  )
}

// ── Map ─────────────────────────────────────────────────────────────────────

export const VISUALS: Record<FeatureKey, () => ReactElement> = {
  savedRoutes: SavedRoutesVisual,
  crossDeviceHistory: CrossDeviceHistoryVisual,
  encryptedContacts: EncryptedContactsVisual,
  smartNotifications: SmartNotificationsVisual,
}
