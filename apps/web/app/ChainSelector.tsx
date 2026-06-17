'use client'

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useSwitchChain, useChainId } from 'wagmi'
import { SUPPORTED_CHAINS, type ChainId } from './tokens/tokenRegistry'
import { C, EASE } from '@/app/designTokens'

// ── Chain color map ──────────────────────────────────────────────────────
const CHAIN_COLORS: Record<number, string> = {
  8453:  '#0052FF',  // Base
  84532: '#ffb800',  // Base Sepolia
  1:     '#627EEA',  // Ethereum
  42161: '#28A0F0',  // Arbitrum
}

// ── Chain icon with SVG fallback ─────────────────────────────────────────
function ChainIcon({ chainId, size = 18 }: { chainId: number; size?: number }) {
  const [imgErr, setImgErr] = useState(false)
  const chain = SUPPORTED_CHAINS[chainId as ChainId]
  const color = CHAIN_COLORS[chainId] ?? '#4a4a6a'

  if (!chain) return null

  return (
    <div style={{
      width: size, height: size, borderRadius: 6,
      overflow: 'hidden', flexShrink: 0,
      background: imgErr ? color : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {!imgErr ? (
        <img
          src={chain.iconUrl}
          alt={chain.name}
          width={size}
          height={size}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.5, fontWeight: 800, color: '#fff' }}>
          {chain.name.charAt(0)}
        </span>
      )}
    </div>
  )
}

// ── Main ChainSelector Dropdown ──────────────────────────────────────────
export default function ChainSelector({
  selectedChainId,
  onSelect,
}: {
  selectedChainId: number
  onSelect: (chainId: number) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const walletChainId = useChainId()
  const { switchChain } = useSwitchChain()

  const selectedChain = SUPPORTED_CHAINS[selectedChainId as ChainId]
  const chainIds = Object.keys(SUPPORTED_CHAINS).map(Number)
  const needsSwitch = walletChainId !== selectedChainId

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

  const handleSelect = (chainId: number) => {
    onSelect(chainId)
    // Trigger wallet chain switch if needed
    if (walletChainId !== chainId) {
      switchChain({ chainId: chainId as 8453 | 84532 | 1 | 11155111 })
    }
    setOpen(false)
  }

  return (
    <div ref={ref} style={{ position: 'relative', flexShrink: 0 }}>
      {/* ── Trigger Button ─────────────────────────────────── */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '8px 10px',
          background: open ? 'rgba(10,10,10,0.08)' : 'rgba(10,10,10,0.03)',
          border: `1px solid ${open ? 'rgba(10,10,10,0.12)' : C.border}`,
          borderRadius: 12,
          cursor: 'pointer',
          transition: 'all 0.15s ease',
        }}
      >
        <ChainIcon chainId={selectedChainId} size={18} />
        <span style={{
          fontFamily: C.D, fontSize: 12, fontWeight: 600,
          color: C.text,
        }}>
          {selectedChain?.name ?? 'Chain'}
        </span>
        {selectedChainId === 84532 && (
          <span style={{
            fontFamily: C.M, fontSize: 7, fontWeight: 700,
            color: '#ffb800', background: 'rgba(255,184,0,0.1)',
            padding: '1px 4px', borderRadius: 3,
          }}>
            TEST
          </span>
        )}
        <span style={{ color: C.dim, fontSize: 8, marginLeft: -2 }}>&#x25BE;</span>
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
              left: 0,
              zIndex: 200,
              minWidth: 180,
              background: '#FFFFFF',
              border: '1px solid rgba(10,10,10,0.10)',
              borderRadius: 14,
              overflow: 'hidden',
              boxShadow: '0 20px 60px rgba(0,0,0,0.7), 0 0 0 1px rgba(10,10,10,0.03)',
              transformOrigin: 'top left',
            }}
          >
            {/* Header */}
            <div style={{
              padding: '10px 14px 8px',
              borderBottom: '1px solid rgba(10,10,10,0.05)',
            }}>
              <span style={{
                fontFamily: C.D, fontSize: 10, fontWeight: 700,
                color: C.dim, textTransform: 'uppercase' as const,
                letterSpacing: '0.08em',
              }}>
                Network
              </span>
            </div>

            {/* Chain list */}
            {chainIds.map(cid => {
              const chain = SUPPORTED_CHAINS[cid as ChainId]
              const active = selectedChainId === cid
              const isTestnet = cid === 84532
              const color = CHAIN_COLORS[cid] ?? '#4a4a6a'

              return (
                <button
                  key={cid}
                  type="button"
                  onClick={() => handleSelect(cid)}
                  style={{
                    width: '100%',
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px',
                    background: active ? 'rgba(10,10,10,0.04)' : 'transparent',
                    border: 'none',
                    borderBottom: '1px solid rgba(10,10,10,0.04)',
                    cursor: 'pointer',
                    transition: 'background 0.12s ease',
                    textAlign: 'left' as const,
                  }}
                  onMouseEnter={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'rgba(10,10,10,0.03)' }}
                  onMouseLeave={e => { if (!active) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                >
                  <div style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: color, boxShadow: `0 0 6px ${color}40`,
                  }} />
                  <div style={{ flex: 1 }}>
                    <span style={{
                      fontFamily: C.D, fontSize: 12, fontWeight: 600,
                      color: active ? C.text : C.sub,
                    }}>
                      {chain.name}
                    </span>
                    {isTestnet && (
                      <span style={{
                        fontFamily: C.M, fontSize: 8,
                        color: '#ffb800', marginLeft: 6,
                      }}>
                        testnet
                      </span>
                    )}
                  </div>
                  {active && (
                    <div style={{
                      width: 5, height: 5, borderRadius: '50%',
                      background: C.green,
                    }} />
                  )}
                </button>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Switch prompt (if wallet on different chain) ──── */}
      {needsSwitch && !open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          left: 0,
          fontFamily: C.M, fontSize: 9,
          color: '#ffb700ff',
          whiteSpace: 'nowrap',
        }}>
          Switch to {selectedChain?.name}
        </div>
      )}
    </div>
  )
}

export { ChainIcon }
