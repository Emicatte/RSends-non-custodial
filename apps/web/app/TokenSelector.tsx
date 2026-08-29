'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { formatUnits } from 'viem'
import { getTokensForChain, type TokenInfo } from './tokens/tokenRegistry'
import { useTokenBalance } from './hooks/useTokenBalance'
import { C, EASE } from '@/app/designTokens'

// ── Color map per token icon fallback ────────────────────────────────────
const TOKEN_COLORS: Record<string, string> = {
  ETH:   '#627EEA',
  USDC:  '#2775CA',
  USDT:  '#26A17B',
  DAI:   '#F5AC37',
  WETH:  '#627EEA',
  cbBTC: '#F7931A',
  ARB:   '#28A0F0',
}

// ── Token icon with SVG fallback ─────────────────────────────────────────
function TokenIcon({ token, size = 28 }: { token: TokenInfo; size?: number }) {
  const [imgErr, setImgErr] = useState(false)
  const color = TOKEN_COLORS[token.symbol] ?? '#4a4a6a'

  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      overflow: 'hidden', flexShrink: 0,
      background: imgErr ? color : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: '1.5px solid rgba(10,10,10,0.08)',
    }}>
      {!imgErr ? (
        <img
          src={token.logoUrl}
          alt={token.symbol}
          width={size}
          height={size}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <span style={{
          fontSize: size * 0.36, fontWeight: 800,
          color: '#fff', fontFamily: C.D,
        }}>
          {token.symbol.slice(0, 2)}
        </span>
      )}
    </div>
  )
}

// ── Single row: fetches its own balance ──────────────────────────────────
function TokenRow({
  token,
  isSelected,
  walletAddress,
  onSelect,
}: {
  token: TokenInfo
  isSelected: boolean
  walletAddress?: `0x${string}`
  onSelect: (token: TokenInfo) => void
}) {
  const { formatted, isLoading } = useTokenBalance(token, walletAddress)
  const [hovered, setHovered] = useState(false)

  const balNum = parseFloat(formatted)
  const displayBal = ['USDC', 'USDT', 'DAI'].includes(token.symbol)
    ? balNum.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : token.symbol === 'cbBTC'
      ? balNum.toFixed(6)
      : balNum.toFixed(4)

  return (
    <button
      type="button"
      onClick={() => onSelect(token)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: '100%',
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 16px',
        background: isSelected
          ? 'rgba(59,130,246,0.08)'
          : hovered
            ? 'rgba(10,10,10,0.04)'
            : 'transparent',
        border: 'none',
        borderBottom: '1px solid rgba(10,10,10,0.04)',
        cursor: 'pointer',
        transition: 'background 0.12s ease',
        textAlign: 'left' as const,
      }}
    >
      <TokenIcon token={token} size={34} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            fontFamily: C.D, fontSize: 14, fontWeight: 700,
            color: isSelected ? C.blue : C.text,
          }}>
            {token.symbol}
          </span>
          {isSelected && (
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: C.blue, boxShadow: `0 0 6px ${C.blue}60`,
            }} />
          )}
        </div>
        <div style={{
          fontFamily: C.M, fontSize: 10, color: C.dim, marginTop: 1,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {token.name}
        </div>
      </div>

      <div style={{ textAlign: 'right' as const, flexShrink: 0 }}>
        {isLoading ? (
          <div style={{
            width: 40, height: 14, borderRadius: 4,
            background: 'rgba(10,10,10,0.08)',
            animation: 'rsPulse 1.5s ease infinite',
          }} />
        ) : (
          <>
            <div style={{
              fontFamily: C.M, fontSize: 13, fontWeight: 600,
              color: balNum > 0 ? C.text : C.dim,
            }}>
              {displayBal}
            </div>
            <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 1 }}>
              {token.symbol}
            </div>
          </>
        )}
      </div>
    </button>
  )
}

// ── Main TokenSelector Dropdown ──────────────────────────────────────────
export default function TokenSelector({
  chainId,
  selectedToken,
  onSelect,
  walletAddress,
}: {
  chainId: number
  selectedToken: TokenInfo | null
  onSelect: (token: TokenInfo) => void
  walletAddress?: `0x${string}`
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const tokens = getTokensForChain(chainId)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const timer = setTimeout(() => document.addEventListener('mousedown', handler), 30)
    return () => { clearTimeout(timer); document.removeEventListener('mousedown', handler) }
  }, [open])

  // Close on ESC
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  // Current selected balance (for trigger display)
  const { formatted: selectedBal, isLoading: selectedBalLoading } = useTokenBalance(
    selectedToken,
    walletAddress,
  )
  const selectedBalDisplay = selectedToken
    ? ['USDC', 'USDT', 'DAI'].includes(selectedToken.symbol)
      ? parseFloat(selectedBal).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : parseFloat(selectedBal).toFixed(4)
    : '0'

  return (
    <div ref={ref} style={{ position: 'relative', flex: 1 }}>
      {/* ── Trigger Button ─────────────────────────────────── */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%',
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px',
          background: open ? 'rgba(10,10,10,0.08)' : 'rgba(10,10,10,0.03)',
          border: `1px solid ${open ? 'rgba(10,10,10,0.12)' : C.border}`,
          borderRadius: 12,
          cursor: 'pointer',
          transition: 'all 0.15s ease',
        }}
      >
        {selectedToken && <TokenIcon token={selectedToken} size={22} />}
        <span style={{
          fontFamily: C.D, fontSize: 13, fontWeight: 700,
          color: C.text, letterSpacing: '-0.01em',
        }}>
          {selectedToken?.symbol ?? 'Select'}
        </span>
        <span style={{ color: C.dim, fontSize: 8, marginLeft: -2 }}>&#x25BE;</span>
        <div style={{ flex: 1 }} />
        <span style={{
          fontFamily: C.M, fontSize: 11, color: C.sub,
        }}>
          {selectedBalLoading ? '...' : selectedBalDisplay}
        </span>
      </button>

      {/* ── Dropdown ───────────────────────────────────────── */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, scaleY: 0.92, y: -4 }}
            animate={{ opacity: 1, scaleY: 1, y: 0 }}
            exit={{ opacity: 0, scaleY: 0.92, y: -4 }}
            transition={{ duration: 0.18, ease: EASE }}
            style={{
              position: 'absolute',
              top: 'calc(100% + 6px)',
              left: 0, right: 0,
              zIndex: 200,
              background: '#FFFFFF',
              border: '1px solid rgba(10,10,10,0.10)',
              borderRadius: 14,
              overflow: 'hidden',
              boxShadow: '0 20px 60px rgba(0,0,0,0.7), 0 0 0 1px rgba(10,10,10,0.03)',
              transformOrigin: 'top center',
            }}
          >
            {/* Header */}
            <div style={{
              padding: '10px 16px 8px',
              borderBottom: '1px solid rgba(10,10,10,0.05)',
            }}>
              <span style={{
                fontFamily: C.D, fontSize: 10, fontWeight: 700,
                color: C.dim, textTransform: 'uppercase' as const,
                letterSpacing: '0.08em',
              }}>
                Select Token
              </span>
            </div>

            {/* Token list */}
            <div style={{ maxHeight: 320, overflowY: 'auto' }}>
              {tokens.map(token => (
                <TokenRow
                  key={`${token.chainId}-${token.symbol}`}
                  token={token}
                  isSelected={
                    selectedToken?.symbol === token.symbol &&
                    selectedToken?.chainId === token.chainId
                  }
                  walletAddress={walletAddress}
                  onSelect={(t) => { onSelect(t); setOpen(false) }}
                />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// Re-export TokenIcon for use in other components
export { TokenIcon, TokenRow }
