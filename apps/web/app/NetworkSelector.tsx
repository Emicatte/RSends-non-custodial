'use client'



import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useTranslations } from 'next-intl'
import { useChainId, useSwitchChain, useAccount, useGasPrice } from 'wagmi'
import { formatUnits } from 'viem'
import {
  getRegistry, getSupportedChains,
} from '../lib/contractRegistry'

const ZERO = '0x0000000000000000000000000000000000000000'

const CHAIN_META: Record<number, { color: string; iconUrl: string; isTestnet: boolean }> = {
  // Mainnet
  1:        { color: '#627EEA', iconUrl: '/chains/ethereum.svg',                                    isTestnet: false },
  10:       { color: '#FF0420', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_optimism.jpg',   isTestnet: false },
  56:       { color: '#F3BA2F', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_bsc.jpg',        isTestnet: false },
  137:      { color: '#7B3FE4', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_polygon.jpg',    isTestnet: false },
  324:      { color: '#1E69FF', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_zksync_era.jpg', isTestnet: false },
  8453:     { color: '#0052FF', iconUrl: '/chains/base.svg',                                        isTestnet: false },
  42161:    { color: '#28A0F0', iconUrl: '/chains/arbitrum.svg',                                    isTestnet: false },
  42220:    { color: '#FCFF52', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_celo.jpg',       isTestnet: false },
  43114:    { color: '#E84142', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_avalanche.jpg',  isTestnet: false },
  81457:    { color: '#FCFC03', iconUrl: 'https://icons.llamao.fi/icons/chains/rsz_blast.jpg',      isTestnet: false },
  // Testnet — riusano il logo mainnet
  84532:    { color: '#0052FF', iconUrl: '/chains/base.svg',                                        isTestnet: true  },
  11155111: { color: '#627EEA', iconUrl: '/chains/ethereum.svg',                                    isTestnet: true  },
}

interface NetworkSelectorProps {
  onNetworkChange?: (chainId: number) => void
  compact?: boolean
}

export default function NetworkSelector({ onNetworkChange, compact = false }: NetworkSelectorProps) {
  const { isConnected }                     = useAccount()
  const walletChainId                       = useChainId()
  const { switchChain, isPending, error }   = useSwitchChain()
  const { data: gasPrice }                  = useGasPrice()
  const gwei                                = gasPrice ? Number(formatUnits(gasPrice, 9)) : null
  const t                                   = useTranslations('networkSelector')
  const [open, setOpen]                     = useState(false)
  const [pendingId, setPendingId]           = useState<number | null>(null)
  const [menuPos, setMenuPos]               = useState<{ top: number; right: number }>({ top: 0, right: 0 })
  const triggerRef                          = useRef<HTMLButtonElement>(null)

  // ── Lista reti dalla registry ──────────────────────────────────────────
  const networks = getSupportedChains()
    .map(id => {
      const reg  = getRegistry(id)
      const meta = CHAIN_META[id] ?? { color: 'rgba(10,10,10,0.55)', iconUrl: '', isTestnet: false }
      if (!reg) return null
      return {
        chainId:     id,
        name:        reg.chainName,
        shortName:   reg.chainName.replace(' Sepolia', '').replace(' Mainnet', ''),
        color:       meta.color,
        iconUrl:     meta.iconUrl,
        isTestnet:   meta.isTestnet,
        isL2:        reg.isL2,
        hasContract: reg.feeRouter !== ZERO,
      }
    })
    .filter(Boolean) as {
      chainId: number; name: string; shortName: string; color: string
      iconUrl: string; isTestnet: boolean; isL2: boolean; hasContract: boolean
    }[]

  // ── Calcola posizione del menu dal trigger button ──────────────────────
  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    setMenuPos({
      top:   rect.bottom + 8,
      right: window.innerWidth - rect.right,
    })
  }, [])

  useEffect(() => {
    if (open) {
      updatePosition()
      window.addEventListener('scroll', updatePosition, true)
      window.addEventListener('resize', updatePosition)
      return () => {
        window.removeEventListener('scroll', updatePosition, true)
        window.removeEventListener('resize', updatePosition)
      }
    }
  }, [open, updatePosition])

  // ── ESC per chiudere ───────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [open])

  // ── Quando il wallet conferma il cambio chain ──────────────────────────
  useEffect(() => {
    if (pendingId && walletChainId === pendingId) {
      setPendingId(null)
      setOpen(false)
      onNetworkChange?.(walletChainId)
    }
  }, [walletChainId, pendingId, onNetworkChange])

  useEffect(() => { if (error) setPendingId(null) }, [error])

  const handleSelect = useCallback((chainId: number) => {
    if (chainId === walletChainId) { setOpen(false); return }
    setPendingId(chainId)
    switchChain({ chainId: chainId as 1 | 10 | 56 | 137 | 324 | 8453 | 42161 | 42220 | 43114 | 81457 | 84532 | 11155111 })
  }, [walletChainId, switchChain])

  const currentNet  = networks.find(n => n.chainId === walletChainId)
  const currentMeta = CHAIN_META[walletChainId] ?? { color: 'rgba(10,10,10,0.55)', iconUrl: '', isTestnet: false }

  if (!isConnected) return null

  return (
    <>
      {/* ═══ Trigger Button ═══ */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => { if (!isPending) setOpen(p => !p) }}
        style={{
          display: 'flex', alignItems: 'center', gap: compact ? 6 : 8,
          padding: compact ? '5px 10px' : '7px 13px 7px 10px',
          borderRadius: 14,
          background: open ? 'rgba(10,10,10,0.10)' : 'rgba(10,10,10,0.04)',
          border: `1.5px solid ${open ? 'rgba(10,10,10,0.18)' : 'rgba(10,10,10,0.08)'}`,
          cursor: isPending ? 'wait' : 'pointer',
          transition: 'all 0.15s ease',
          outline: 'none',
        }}
        onMouseEnter={e => { if (!open && !isPending) e.currentTarget.style.background = 'rgba(10,10,10,0.08)' }}
        onMouseLeave={e => { if (!open) e.currentTarget.style.background = 'rgba(10,10,10,0.04)' }}
      >
        <div style={{
          width: 8, height: 8, borderRadius: '50%',
          background: currentMeta.color,
          boxShadow: `0 0 6px ${currentMeta.color}60`,
          flexShrink: 0,
        }} />

        {isPending ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div className="rp-spinner" style={{
              width: 11, height: 11,
              border: '2px solid rgba(0,255,163,0.3)',
              borderTopColor: '#00ffa3',
              borderRadius: '50%',
            }} />
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600, color: '#00ffa3' }}>
              Cambio…
            </span>
          </div>
        ) : (
          <>
            <span style={{
              fontFamily: 'var(--font-display)',
              fontSize: compact ? 11 : 12,
              fontWeight: 700,
              color: '#0A0A0A',
            }}>
              {currentNet?.shortName ?? `Chain ${walletChainId}`}
            </span>
            {gwei !== null && (
              <span className="text-black/50 text-[11px] font-mono font-normal">
                {gwei.toFixed(3)}
              </span>
            )}
            <span style={{
              color: 'rgba(10,10,10,0.55)', fontSize: 9,
              transform: open ? 'rotate(180deg)' : 'none',
              transition: 'transform 0.2s',
              display: 'inline-block',
            }}>▾</span>
          </>
        )}
      </button>

      {/* ═══ Portal: Overlay + Menu renderizzato su document.body ═══ */}
      {open && typeof document !== 'undefined' && createPortal(
        <>
          {/* Overlay scuro — chiude il menu al click */}
          <div
            onClick={() => setOpen(false)}
            style={{
              position: 'fixed', inset: 0, zIndex: 99998,
              background: 'rgba(0,0,0,0.3)',
            }}
          />

          {/* Menu dropdown — SOLIDO, su document.body, fuori dal card */}
          <div
            onClick={e => e.stopPropagation()}
            style={{
              position: 'fixed',
              top: menuPos.top,
              right: menuPos.right,
              minWidth: 240,
              zIndex: 99999,
              background: '#FFFFFF',
              opacity: 1,
              border: '1.5px solid rgba(10,10,10,0.12)',
              borderRadius: 18,
              boxShadow: '0 20px 60px rgba(0,0,0,0.95), 0 0 0 1px rgba(10,10,10,0.05)',
              overflowY: 'auto',
              overflowX: 'hidden',
              maxHeight: `min(480px, calc(100vh - ${menuPos.top + 20}px))`,
              scrollbarWidth: 'thin' as const,
              scrollbarColor: 'rgba(10,10,10,0.2) transparent',
              animation: 'rpFadeUp 0.15s ease both',
            }}
          >
            {/* Header */}
            <div style={{
              padding: '12px 16px 10px',
              borderBottom: '1px solid rgba(10,10,10,0.08)',
              background: '#FFFFFF',
            }}>
              <span style={{
                fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700,
                color: 'rgba(10,10,10,0.55)', textTransform: 'uppercase' as const,
                letterSpacing: '0.08em',
              }}>
                {t('title')}
              </span>
            </div>

            {/* Lista reti */}
            {networks.map((net, i) => {
              const isActive    = net.chainId === walletChainId
              const isSwitching = isPending && pendingId === net.chainId
              const disabled    = !net.hasContract && !net.isTestnet

              return (
                <div
                  key={net.chainId}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    if (disabled || isSwitching) return
                    handleSelect(net.chainId)
                  }}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !disabled && !isSwitching) handleSelect(net.chainId)
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '12px 16px',
                    background: isActive ? `${net.color}12` : '#FFFFFF',
                    borderBottom: i < networks.length - 1 ? '1px solid rgba(10,10,10,0.05)' : 'none',
                    cursor: disabled ? 'not-allowed' : isSwitching ? 'wait' : 'pointer',
                    transition: 'background 0.12s ease',
                    opacity: disabled ? 0.4 : 1,
                    outline: 'none',
                    userSelect: 'none' as const,
                  }}
                  onMouseEnter={e => {
                    if (!isActive && !disabled && !isSwitching)
                      (e.currentTarget as HTMLElement).style.background = 'rgba(10,10,10,0.08)'
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = isActive ? `${net.color}12` : '#FFFFFF'
                  }}
                >
                  {/* Icona */}
                  <div style={{
                    width: 34, height: 34, borderRadius: 10,
                    background: `${net.color}15`, border: `1.5px solid ${net.color}30`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0, overflow: 'hidden',
                  }}>
                    {net.iconUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={net.iconUrl}
                        alt={net.name}
                        width={22}
                        height={22}
                        style={{ width: 22, height: 22, objectFit: 'contain', display: 'block' }}
                        onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                        loading="lazy"
                      />
                    ) : (
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: net.color }} />
                    )}
                  </div>

                  {/* Nome + badge */}
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{
                        fontFamily: 'var(--font-display)', fontSize: 13, fontWeight: 700,
                        color: '#0A0A0A',
                      }}>
                        {net.name}
                      </span>
                      {net.isTestnet && (
                        <span style={{
                          fontFamily: 'var(--font-display)', fontSize: 8, fontWeight: 700,
                          color: '#ffb800', background: 'rgba(255,184,0,0.12)',
                          padding: '2px 5px', borderRadius: 4,
                          border: '1px solid rgba(255,184,0,0.2)',
                        }}>TEST</span>
                      )}
                      {net.isL2 && !net.isTestnet && (
                        <span style={{
                          fontFamily: 'var(--font-display)', fontSize: 8, fontWeight: 700,
                          color: '#00ffa3', background: 'rgba(0,255,163,0.08)',
                          padding: '2px 5px', borderRadius: 4,
                          border: '1px solid rgba(0,255,163,0.15)',
                        }}>L2</span>
                      )}
                    </div>
                    {disabled && (
                      <span style={{ fontFamily: 'var(--font-display)', fontSize: 10, color: 'rgba(10,10,10,0.55)', display: 'block', marginTop: 1 }}>
                        {t('comingSoon')}
                      </span>
                    )}
                    {isSwitching && (
                      <span style={{ fontFamily: 'var(--font-display)', fontSize: 10, color: '#00ffa3', display: 'block', marginTop: 1 }}>
                        {t('confirmInWallet')}
                      </span>
                    )}
                  </div>

                  {/* Indicatore destro */}
                  {isActive && !isSwitching && (
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: '#00ffa3', boxShadow: '0 0 8px #00ffa3',
                      flexShrink: 0,
                    }} />
                  )}
                  {isSwitching && (
                    <div className="rp-spinner" style={{
                      width: 14, height: 14,
                      border: '2px solid rgba(0,255,163,0.3)',
                      borderTopColor: '#00ffa3',
                      borderRadius: '50%', flexShrink: 0,
                    }} />
                  )}
                </div>
              )
            })}
          </div>
        </>,
        document.body
      )}
    </>
  )
}