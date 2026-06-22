'use client'


import { useState, useEffect, useRef, useCallback, useMemo, useTransition } from 'react'
import { createPortal } from 'react-dom'
import { useAccount, useBalance, useDisconnect, useChainId } from 'wagmi'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { useWalletMount } from './providers'
import { formatUnits } from 'viem'
import { getRegistry } from '../lib/contractRegistry'
import { useIsMobile } from '../hooks/useIsMobile'
import { useLocale } from 'next-intl'
import { useRouter, usePathname } from '@/i18n/navigation'
import type { Locale } from '@/i18n/routing'


const LOCALES: { code: Locale; flag: string }[] = [
  { code: 'en', flag: 'EN' },
  { code: 'it', flag: 'IT' },
  { code: 'es', flag: 'ES' },
  { code: 'fr', flag: 'FR' },
  { code: 'de', flag: 'DE' },
]

// ── Identicon ──────────────────────────────────────────────────────────────
function addressToColors(address: string): [string, string, string] {
  // Skip 0x prefix for EVM, or use full string for non-EVM (Tron/Solana)
  const h = address.startsWith('0x') ? address.toLowerCase().slice(2) : address.toLowerCase()
  const h1 = parseInt(h.slice(0,6), 16) % 360
  const h2 = (h1 + 120 + (parseInt(h.slice(6,10), 16) % 120)) % 360
  const h3 = (h2 + 90 + (parseInt(h.slice(10,14), 16) % 90)) % 360
  return [`hsl(${h1},70%,55%)`, `hsl(${h2},65%,50%)`, `hsl(${h3},75%,45%)`]
}

function Identicon({ address, size = 28 }: { address: string; size?: number }) {
  const [c1, c2, c3] = useMemo(() => addressToColors(address), [address])
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `conic-gradient(from 30deg, ${c1}, ${c2}, ${c3}, ${c1})`,
      border: '2px solid rgba(10,10,10,0.12)', flexShrink: 0,
    }} />
  )
}

function tr(addr: string, s=6, e=4): string {
  if (!addr || addr.length < s+e+2) return addr
  return `${addr.slice(0,s)}…${addr.slice(-e)}`
}

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND_URL = '/api/backend'

interface RecentTx {
  tx_hash: string; gross_amount: number; currency: string
  status: string; recipient: string; tx_timestamp: string
}

// ── Non-EVM wallet prop ───────────────────────────────────────────────────
export interface NonEvmWalletProps {
  family: 'tron' | 'solana'
  address: string
  disconnect: () => void
}

const NON_EVM_META: Record<string, { name: string; color: string; icon: string; explorer: string }> = {
  tron:   { name: 'TRON',   color: '#FF0000', icon: '◆', explorer: 'https://tronscan.org/#/address/' },
  solana: { name: 'Solana', color: '#9945FF', icon: '◎', explorer: 'https://solscan.io/account/' },
}

// ═══════════════════════════════════════════════════════════════════════════
// Wallet mount gate: pre-click on landing, RainbowKit isn't loaded yet, so
// ConnectButton.Custom wouldn't work. Render a static button that triggers
// the lazy mount instead. After mountWallet() flips the flag, the full
// AccountHeaderImpl renders with all wagmi/RainbowKit hooks available.
export default function AccountHeader(props: { nonEvmWallet?: NonEvmWalletProps } = {}) {
  const { walletRequested, mountWallet } = useWalletMount()
  if (!walletRequested) {
    return (
      <button onClick={mountWallet} style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 16px', borderRadius: 20,
        background: 'linear-gradient(135deg, #00ffa3, #00cc80)',
        border: 'none', fontFamily: 'var(--font-display)',
        fontSize: 13, fontWeight: 700, color: '#000', cursor: 'pointer',
      }}>Connetti Wallet</button>
    )
  }
  return <AccountHeaderImpl {...props} />
}

function AccountHeaderImpl({ nonEvmWallet }: { nonEvmWallet?: NonEvmWalletProps } = {}) {
  const { address: evmAddress, isConnected: evmConnected } = useAccount()
  const { disconnect: evmDisconnect }  = useDisconnect()
  const chainId                        = useChainId()
  const { data: balance }              = useBalance({ address: evmAddress })

  // Resolve active wallet source
  const isNonEvm = !!nonEvmWallet
  const address = isNonEvm ? nonEvmWallet!.address : evmAddress
  const isConnected = isNonEvm ? true : evmConnected
  const disconnect = isNonEvm ? nonEvmWallet!.disconnect : evmDisconnect

  // Locale switcher (moved here from top-right of /[locale]/app)
  const locale = useLocale()
  const router = useRouter()
  const pathname = usePathname()
  const [, startLocaleTransition] = useTransition()

  const [open, setOpen]                 = useState(false)
  const [copied, setCopied]             = useState(false)
  const [recentTxs, setRecentTxs]       = useState<RecentTx[]>([])
  const [menuPos, setMenuPos]           = useState({ top: 0, right: 0 })
  const triggerRef                      = useRef<HTMLButtonElement>(null)

  const reg = getRegistry(chainId)
  const isMobile = useIsMobile()

  // Posizione menu
  const updatePos = useCallback(() => {
    if (!triggerRef.current) return
    const r = triggerRef.current.getBoundingClientRect()
    setMenuPos({ top: r.bottom + 10, right: window.innerWidth - r.right })
  }, [])

  useEffect(() => {
    if (!open) return
    updatePos()
    window.addEventListener('scroll', updatePos, true)
    window.addEventListener('resize', updatePos)
    return () => {
      window.removeEventListener('scroll', updatePos, true)
      window.removeEventListener('resize', updatePos)
    }
  }, [open, updatePos])

  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [open])

  // Fetch recent txs (EVM only)
  useEffect(() => {
    if (isNonEvm || !open || !address) return
    let c = false
    fetch(`${BACKEND_URL}/api/v1/tx/recent?wallet=${address}&limit=3`)
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(d => { if (!c) setRecentTxs(d.records ?? []) })
      .catch(() => { if (!c) setRecentTxs([]) })
    return () => { c = true }
  }, [isNonEvm, open, address])

  const handleCopy = useCallback(async () => {
    if (!address) return
    await navigator.clipboard.writeText(address)
    setCopied(true); setTimeout(() => setCopied(false), 2000)
  }, [address])

  const balFmt = balance ? parseFloat(formatUnits(balance.value, balance.decimals)).toFixed(4) : '0.0000'
  const balSym = balance?.symbol ?? 'ETH'

  if (!isConnected || !address) {
    return (
      <ConnectButton.Custom>
        {({ openConnectModal }) => (
          <button onClick={openConnectModal} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 16px', borderRadius: 20,
            background: 'linear-gradient(135deg, #00ffa3, #00cc80)',
            border: 'none', fontFamily: 'var(--font-display)',
            fontSize: 13, fontWeight: 700, color: '#000', cursor: 'pointer',
          }}>Connetti Wallet</button>
        )}
      </ConnectButton.Custom>
    )
  }

  return (
    <>
      {/* Pill Button */}
      <button ref={triggerRef} type="button" onClick={() => setOpen(p => !p)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '5px 12px 5px 5px', borderRadius: 24,
          background: open ? 'rgba(10,10,10,0.10)' : 'rgba(10,10,10,0.04)',
          border: `1.5px solid ${open ? 'rgba(10,10,10,0.18)' : 'rgba(10,10,10,0.08)'}`,
          cursor: 'pointer', transition: 'all 0.15s', outline: 'none',
        }}
        onMouseEnter={e => { if (!open) e.currentTarget.style.background = 'rgba(10,10,10,0.08)' }}
        onMouseLeave={e => { if (!open) e.currentTarget.style.background = 'rgba(10,10,10,0.04)' }}
      >
        {isNonEvm ? (
          <div style={{
            width: 26, height: 26, borderRadius: '50%',
            background: `${NON_EVM_META[nonEvmWallet!.family].color}20`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, fontWeight: 700, color: NON_EVM_META[nonEvmWallet!.family].color,
            border: `1px solid ${NON_EVM_META[nonEvmWallet!.family].color}30`,
          }}>{NON_EVM_META[nonEvmWallet!.family].icon}</div>
        ) : (
          <Identicon address={address} size={26} />
        )}
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 500, color: '#0A0A0A' }}>
          {tr(address)}
        </span>
      </button>

      {/* Dropdown Portal */}
      {open && typeof document !== 'undefined' && createPortal(
        <>
          <div onClick={() => setOpen(false)} style={{
            position: 'fixed', inset: 0, zIndex: 99998,
            background: 'rgba(0,0,0,0.25)',
          }} />
          <div onClick={e => e.stopPropagation()} style={{
            position: 'fixed', top: menuPos.top,
            ...(isMobile
              ? { left: 8, right: 8 }
              : { right: menuPos.right, width: 320 }),
            zIndex: 99999,
            background: '#FFFFFF', border: '1.5px solid rgba(10,10,10,0.12)',
            borderRadius: 20, boxShadow: '0 24px 80px rgba(0,0,0,0.95)',
            overflow: 'hidden', animation: 'rpFadeUp 0.18s ease both',
          }}>
            {/* Identity */}
            <div style={{ padding: '18px 18px 14px', borderBottom: '1px solid rgba(10,10,10,0.08)', background: '#FFFFFF' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                {isNonEvm ? (
                  <div style={{
                    width: 40, height: 40, borderRadius: '50%',
                    background: `${NON_EVM_META[nonEvmWallet!.family].color}20`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 20, fontWeight: 700, color: NON_EVM_META[nonEvmWallet!.family].color,
                    border: `1.5px solid ${NON_EVM_META[nonEvmWallet!.family].color}30`,
                  }}>{NON_EVM_META[nonEvmWallet!.family].icon}</div>
                ) : (
                  <Identicon address={address} size={40} />
                )}
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 500, color: '#0A0A0A' }}>{tr(address, 8, 6)}</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 11, color: 'rgba(10,10,10,0.55)', marginTop: 2 }}>
                    {isNonEvm ? NON_EVM_META[nonEvmWallet!.family].name : (reg?.chainName ?? 'Base')}
                  </div>
                </div>
              </div>

              {/* Balance — EVM only */}
              {!isNonEvm && (
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 14 }}>
                  <span style={{ fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 800, color: '#0A0A0A', letterSpacing: '-0.03em' }}>{balFmt}</span>
                  <span style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 600, color: 'rgba(10,10,10,0.55)' }}>{balSym}</span>
                </div>
              )}

              {/* Language selector — 5 locale flags (inline, no nested dropdown) */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10,
                padding: '8px 10px', borderRadius: 12,
                background: 'rgba(10,10,10,0.03)', border: '1px solid rgba(10,10,10,0.06)',
              }}>
                <span style={{
                  fontFamily: 'var(--font-display)', fontSize: 10, fontWeight: 700,
                  color: 'rgba(10,10,10,0.55)', textTransform: 'uppercase' as const, letterSpacing: '0.08em',
                }}>Language</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
                  {LOCALES.map((l) => {
                    const isActive = l.code === locale
                    return (
                      <button
                        key={l.code}
                        onClick={() => {
                          const search = typeof window !== 'undefined' ? window.location.search : ''
                          const hash = typeof window !== 'undefined' ? window.location.hash : ''
                          startLocaleTransition(() => {
                            router.replace(pathname + search + hash, { locale: l.code })
                            setOpen(false)
                          })
                        }}
                        style={{
                          padding: '4px 7px', borderRadius: 6, border: 'none',
                          fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
                          background: isActive ? '#0A0A0A' : 'transparent',
                          color: isActive ? '#fff' : 'rgba(10,10,10,0.5)',
                          cursor: 'pointer', transition: 'all 0.15s',
                        }}
                        onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = '#0A0A0A' }}
                        onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = 'rgba(10,10,10,0.5)' }}
                      >{l.flag}</button>
                    )
                  })}
                </div>
              </div>

              {/* Action row */}
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={handleCopy} style={{
                  flex: 1, padding: '8px 0', borderRadius: 10,
                  background: 'rgba(10,10,10,0.05)', border: '1px solid rgba(10,10,10,0.08)',
                  color: copied ? '#00ffa3' : '#0A0A0A',
                  fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                }}>{copied ? '✓ Copiato' : '⎘ Copia'}</button>

                <a href={isNonEvm
                    ? `${NON_EVM_META[nonEvmWallet!.family].explorer}${address}`
                    : `${reg?.blockExplorer ?? 'https://basescan.org'}/address/${address}`}
                  target="_blank" rel="noopener noreferrer" style={{
                  flex: 1, padding: '8px 0', borderRadius: 10,
                  background: 'rgba(10,10,10,0.05)', border: '1px solid rgba(10,10,10,0.08)',
                  color: '#0A0A0A', fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
                  textDecoration: 'none', textAlign: 'center' as const, display: 'block',
                }}>↗ Explorer</a>

                <button onClick={() => { disconnect(); setOpen(false) }} style={{
                  flex: 1, padding: '8px 0', borderRadius: 10,
                  background: 'rgba(255,45,85,0.08)', border: '1px solid rgba(255,45,85,0.15)',
                  color: '#ff2d55', fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                }}>⏻ Esci</button>
              </div>
            </div>

            {/* Recent Activity — EVM only */}
            {!isNonEvm && (
              <div style={{ padding: '14px 18px 16px', background: '#FFFFFF' }}>
                <div style={{
                  fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 700, color: 'rgba(10,10,10,0.55)',
                  textTransform: 'uppercase' as const, letterSpacing: '0.08em', marginBottom: 10,
                }}>Attività Recente</div>
                {recentTxs.length === 0 ? (
                  <div style={{ padding: '12px 0', textAlign: 'center' as const }}>
                    <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, color: 'rgba(10,10,10,0.55)' }}>Nessuna attività</div>
                  </div>
                ) : recentTxs.slice(0, 3).map((tx: RecentTx, i: number) => (
                  <a key={tx.tx_hash || i}
                    href={`${reg?.blockExplorer ?? 'https://basescan.org'}/tx/${tx.tx_hash}`}
                    target="_blank" rel="noopener noreferrer"
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '8px 8px', borderRadius: 10,
                      textDecoration: 'none', transition: 'background 0.12s',
                    }}
                    onMouseEnter={e => (e.currentTarget).style.background = 'rgba(10,10,10,0.04)'}
                    onMouseLeave={e => (e.currentTarget).style.background = 'transparent'}
                  >
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                      background: tx.status === 'completed' ? '#00ffa3' : '#ffb800',
                      boxShadow: `0 0 6px ${tx.status === 'completed' ? '#00ffa3' : '#ffb800'}50`,
                    }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 600, color: '#0A0A0A' }}>
                        {tx.gross_amount?.toFixed(6)} {tx.currency}
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(10,10,10,0.55)', marginTop: 1 }}>
                        → {tr(tx.recipient || '', 6, 4)}
                      </div>
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'rgba(10,10,10,0.55)' }}>↗</div>
                  </a>
                ))}
              </div>
            )}
          </div>
        </>,
        document.body
      )}

    </>
  )
}