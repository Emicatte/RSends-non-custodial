'use client'

/**
 * app/pay/_components/payUi.tsx — brand-styled atoms for the /pay route.
 *
 * Paper/ink/terracotta palette (C), General Sans for prose, DM Mono (C.M) for
 * EVERY numeric/technical value (amounts, addresses, hashes). No `transition: all`.
 */
import { useCallback, useState, type CSSProperties, type ReactNode } from 'react'
import { C } from '@/app/designTokens'
import { getRegistry } from '@/lib/contractRegistry'
import { CHAIN_ID, ETH_FAUCET_URL } from '@/lib/web3/payTokens'

const EXPLORER = (getRegistry(CHAIN_ID)?.blockExplorer ?? 'https://sepolia.basescan.org').replace(/\/$/, '')

export function txLink(hash: string): string {
  return `${EXPLORER}/tx/${hash}`
}
export function addressLink(addr: string): string {
  return `${EXPLORER}/address/${addr}`
}
export function truncate(value: string, lead = 6, tail = 4): string {
  if (value.length <= lead + tail + 2) return value
  return `${value.slice(0, lead)}…${value.slice(-tail)}`
}

// ── Mono — wraps any numeric/technical value in DM Mono ──────────────────────
export function Mono({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <span style={{ fontFamily: C.M, ...style }}>{children}</span>
}

// ── Copy-to-clipboard ────────────────────────────────────────────────────────
export function useCopy(): { copied: boolean; copy: (text: string) => void } {
  const [copied, setCopied] = useState(false)
  const copy = useCallback((text: string) => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text).then(
        () => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        },
        () => {},
      )
    }
  }, [])
  return { copied, copy }
}

export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const { copied, copy } = useCopy()
  return (
    <button
      type="button"
      onClick={() => copy(value)}
      style={{
        fontFamily: C.M,
        fontSize: 12,
        color: copied ? C.green : C.purple,
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        padding: '2px 4px',
        transition: 'color 150ms ease',
      }}
    >
      {copied ? 'Copied ✓' : label}
    </button>
  )
}

/** Truncated, copyable address in DM Mono. */
export function AddressChip({ address }: { address: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <a
        href={addressLink(address)}
        target="_blank"
        rel="noopener noreferrer"
        title={address}
        style={{ fontFamily: C.M, fontSize: 13, color: C.text, textDecoration: 'none' }}
      >
        {truncate(address)}
      </a>
      <CopyButton value={address} />
    </span>
  )
}

// ── Layout ───────────────────────────────────────────────────────────────────
export function Shell({ children }: { children: ReactNode }) {
  return (
    <main
      style={{
        minHeight: '100vh',
        background: C.bg,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 'clamp(20px, 5vw, 56px) 20px',
        gap: 20,
      }}
    >
      {children}
    </main>
  )
}

export function Card({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        width: '100%',
        maxWidth: 460,
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: 20,
        padding: 'clamp(22px, 5vw, 32px)',
        boxShadow: '0 18px 48px rgba(10,10,10,0.06)',
        animation: 'fadeIn 0.3s ease-out',
      }}
    >
      {children}
    </div>
  )
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontFamily: C.M,
        fontSize: 12,
        fontWeight: 500,
        letterSpacing: '0.18em',
        textTransform: 'uppercase',
        color: C.purple,
      }}
    >
      {children}
    </div>
  )
}

// ── Buttons ──────────────────────────────────────────────────────────────────
const buttonBase: CSSProperties = {
  width: '100%',
  borderRadius: 12,
  padding: '13px 18px',
  fontFamily: C.D,
  fontSize: 15,
  fontWeight: 600,
  cursor: 'pointer',
  transition: 'background-color 150ms ease, opacity 150ms ease, border-color 150ms ease',
}

export function PrimaryButton({
  onClick, disabled, children,
}: {
  onClick?: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...buttonBase,
        background: C.purple,
        color: '#FFFFFF',
        border: `1px solid ${C.purple}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export function GhostButton({
  onClick, disabled, children,
}: {
  onClick?: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        ...buttonBase,
        background: 'transparent',
        color: C.text,
        border: `1px solid ${C.border}`,
        opacity: disabled ? 0.5 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  )
}

// ── Spinner ──────────────────────────────────────────────────────────────────
export function Spinner({ size = 18 }: { size?: number }) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: `2px solid ${C.border}`,
        borderTopColor: C.purple,
        borderRadius: '50%',
        animation: 'rpSpin 0.7s linear infinite',
      }}
    />
  )
}

// ── Testnet badge + faucet hints ───────────────────────────────────────────────
export function TestnetBadge() {
  return (
    <div
      style={{
        display: 'inline-flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        padding: '7px 14px',
        borderRadius: 999,
        background: 'rgba(255,181,71,0.12)',
        border: '1px solid rgba(255,181,71,0.35)',
        fontFamily: C.D,
        fontSize: 12.5,
        color: C.text,
      }}
    >
      <span style={{ fontWeight: 600 }}>Base Sepolia testnet — no real funds</span>
      <span style={{ color: C.sub }}>·</span>
      <a href="https://faucet.circle.com" target="_blank" rel="noopener noreferrer"
        style={{ color: C.purple, fontFamily: C.M, fontSize: 12, textDecoration: 'none' }}>
        USDC faucet
      </a>
      <a href={ETH_FAUCET_URL} target="_blank" rel="noopener noreferrer"
        style={{ color: C.purple, fontFamily: C.M, fontSize: 12, textDecoration: 'none' }}>
        ETH faucet
      </a>
    </div>
  )
}

export function NonCustodialNote() {
  return (
    <p style={{ margin: 0, fontFamily: C.D, fontSize: 12.5, lineHeight: 1.5, color: C.sub }}>
      RSends never holds your funds — the router transfers the principal to the merchant and the
      fee to the fee collector in one transaction.
    </p>
  )
}

export function ErrorText({ children }: { children: ReactNode }) {
  return (
    <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.red, textAlign: 'center', wordBreak: 'break-word' }}>
      {children}
    </p>
  )
}
