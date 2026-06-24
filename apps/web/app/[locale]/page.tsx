'use client'




import { useState, useEffect, useRef, useCallback } from 'react'
import { useAccount, useChainId, useSwitchChain } from 'wagmi'
import { motion, AnimatePresence } from 'framer-motion'
import type { Variants, Transition } from 'framer-motion'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { useTranslations } from 'next-intl'
import LanguageSwitcher from '@/components/LanguageSwitcher'

// STATIC IMPORTS
import AccountHeader from '../AccountHeader'
const HeroGlobe = dynamic(() => import('@/components/HeroGlobe'), { ssr: false })
import { useSweepWebSocket } from '../../lib/useSweepWebSocket'
import { useSweepStats } from '../../lib/useSweepStats'
import AntiPhishingSetup from '../AntiPhishingSetup'
import { TokenRow } from '../TokenSelector'
import { getNativeToken, getTokensForChain, type TokenInfo } from '../tokens/tokenRegistry'
import { ChainLogo } from '../../src/components/ChainLogo'
import { useTokenBalance } from '../hooks/useTokenBalance'
import { useTokenPrices } from '../hooks/useTokenPrices'
import { ChainFamilySwitch } from '../../components/shared/ChainFamilySwitch'
import { useUniversalWallet } from '../../hooks/useUniversalWallet'
import type { ChainFamily } from '../../lib/chain-adapters/types'
import { useWallet as useSolanaWallet } from '@solana/wallet-adapter-react'
import { useWalletModal } from '@solana/wallet-adapter-react-ui'
import { useTron } from '../providers-tron'
import type { NonEvmWalletProps } from '../AccountHeader'
import { ToastContainer } from '../../components/shared/Toast'
import GetStartedSection from '@/components/landing/GetStartedSection'
import LandingSections from '../LandingSections'
import { C, EASE } from '@/app/designTokens'
import SplitText from '@/components/motion/SplitText'
import SmoothScroll from '@/components/SmoothScroll'
import { LandingAuthButtons } from '@/components/auth/LandingAuthButtons'
import { WhySignInSection } from '@/components/landing/WhySignInSection'
import SupportedNetworksCarousel from '@/components/landing/SupportedNetworksCarousel'




const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

const cinematicT: Transition = { duration: 0.45, ease: EASE }

const heroV: Variants = {
  enter:  { opacity: 0, y: 10, filter: 'blur(4px)' },
  center: { opacity: 1, y: 0,  filter: 'blur(0px)' },
  exit:   { opacity: 0, y: -10, filter: 'blur(4px)' },
}

const formV: Variants = {
  enter:  { opacity: 0, y: 12, scale: 0.97 },
  center: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.45, ease: EASE } },
  exit:   { opacity: 0, y: -8, scale: 0.97, transition: { duration: 0.3, ease: EASE } },
}

// ═══════════════════════════════════════════════════════════
//  PARTICLE INTRO (first visit)
// ═══════════════════════════════════════════════════════════
function ParticleIntro({ onDone }: { onDone: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
    const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2

    interface P { x:number;y:number;tx:number;ty:number;ox:number;oy:number;s:number;h:number;sp:number;a:number;al:number }
    const N = 140
    const particles: P[] = []
    for (let i = 0; i < N; i++) {
      const ang = (i / N) * Math.PI * 2, dist = 200 + Math.random() * 350
      const r = 24 * (0.6 + Math.random() * 0.4)
      particles.push({ x: cx + Math.cos(ang) * dist, y: cy + Math.sin(ang) * dist, tx: cx + Math.cos(ang) * r, ty: cy - 20 + Math.sin(ang) * r, ox: cx + Math.cos(ang) * dist, oy: cy + Math.sin(ang) * dist, s: 1 + Math.random() * 2, h: 240 + Math.random() * 80, sp: 0.003 + Math.random() * 0.004, a: Math.random() * Math.PI * 2, al: 0.3 + Math.random() * 0.7 })
    }

    let start = Date.now(), ph = 0, af: number
    const draw = () => {
      const el = Date.now() - start
      ctx.clearRect(0, 0, W, H)
      const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, W * 0.7)
      bg.addColorStop(0, 'rgba(20,10,40,1)'); bg.addColorStop(1, 'rgba(10,10,15,1)')
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H)
      const na = Math.min(1, el / 2000) * 0.12
      const n1 = ctx.createRadialGradient(cx - 150, cy - 80, 0, cx - 150, cy - 80, 280)
      n1.addColorStop(0, `rgba(200,81,44,${na})`); n1.addColorStop(1, 'transparent')
      ctx.fillStyle = n1; ctx.fillRect(0, 0, W, H)

      if (el > 1500 && ph === 0) { ph = 1; setPhase(1) }
      if (el > 3000 && ph === 1) { ph = 2; setPhase(2) }
      if (el > 4500 && ph === 2) { ph = 3; setPhase(3) }
      if (el > 6000 && ph === 3) { ph = 4; setPhase(4) }

      const cp = ph >= 1 ? Math.min(1, (el - 1500) / 1200) : 0
      const eased = cp * cp * (3 - 2 * cp)
      for (const p of particles) {
        p.a += p.sp
        if (ph >= 1) { p.x += (p.tx - p.x) * (0.02 + eased * 0.04); p.y += (p.ty - p.y) * (0.02 + eased * 0.04) }
        else { p.x = p.ox + Math.sin(el * 0.001 + p.a) * 8; p.y = p.oy + Math.cos(el * 0.0008 + p.a) * 6 }
        const gs = ph >= 2 ? p.s * (1 + Math.sin(el * 0.005) * 0.3) : p.s
        const al = ph >= 4 ? Math.max(0, p.al * (1 - (el - 6000) / 700)) : p.al
        ctx.beginPath(); ctx.arc(p.x, p.y, gs, 0, Math.PI * 2)
        ctx.fillStyle = `hsla(${p.h},80%,70%,${al})`; ctx.fill()
        if (gs > 1.5) { ctx.beginPath(); ctx.arc(p.x, p.y, gs * 2.5, 0, Math.PI * 2); ctx.fillStyle = `hsla(${p.h},80%,70%,${al * 0.1})`; ctx.fill() }
      }
      if (ph < 4) af = requestAnimationFrame(draw)
    }
    af = requestAnimationFrame(draw)
    const timer = setTimeout(onDone, 6700)
    return () => { cancelAnimationFrame(af); clearTimeout(timer) }
  }, [onDone])

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 10000, opacity: phase === 4 ? 0 : 1, transition: 'opacity 0.7s ease', pointerEvents: phase === 4 ? 'none' : 'auto' }}>
      <canvas ref={canvasRef} style={{ position: 'absolute', inset: 0 }} />
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', textAlign: 'center' }}>
        <div style={{ opacity: phase >= 2 ? 1 : 0, transition: 'opacity 0.6s ease', marginBottom: 8 }}>
          <div style={{ width: 52, height: 52, borderRadius: 13, background: C.text, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto', boxShadow: phase >= 2 ? '0 0 50px rgba(200,81,44,0.4)' : 'none' }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M13 2L4.5 12.5h5.5l-1 9.5 8.5-11.5h-5.5L13 2z" fill="white" fillOpacity="0.95"/></svg>
          </div>
        </div>
        <div style={{ opacity: phase >= 3 ? 1 : 0, transform: phase >= 3 ? 'translateY(0)' : 'translateY(10px)', transition: 'all 0.8s cubic-bezier(.16,1,.3,1)' }}>
          <div style={{ fontFamily: C.M, fontSize: 10, letterSpacing: '0.15em', textTransform: 'uppercase' as const, color: 'transparent', background: `linear-gradient(90deg, ${C.text}, ${C.purple}, ${C.text})`, backgroundSize: '200% 100%', WebkitBackgroundClip: 'text', animation: phase >= 3 ? 'holoShift 3s linear infinite' : 'none' }}>
            Multi-chain financial automation
          </div>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  NETWORK + GAS WIDGET — fixed top-right, below navbar
// ═══════════════════════════════════════════════════════════
const _AK = process.env.NEXT_PUBLIC_ALCHEMY_API_KEY ?? ''
const _IK = process.env.NEXT_PUBLIC_INFURA_API_KEY ?? ''
function _alch(sub: string) { return _AK ? `https://${sub}.g.alchemy.com/v2/${_AK}` : '' }
function _inf(net: string) { return _IK ? `https://${net}.infura.io/v3/${_IK}` : '' }

const CHAINS = [
  // ── Mainnet ──
  { id: 1,     name: 'Ethereum',      short: 'ETH',       color: '#627EEA', rpc: [_alch('eth-mainnet'), _inf('mainnet'), 'https://eth.llamarpc.com'].filter(Boolean) },
  { id: 8453,  name: 'Base',          short: 'Base',      color: '#0052FF', rpc: [_alch('base-mainnet'), 'https://mainnet.base.org'].filter(Boolean) },
  { id: 42161, name: 'Arbitrum',      short: 'ARB',       color: '#28A0F0', rpc: [_alch('arb-mainnet'), _inf('arbitrum-mainnet'), 'https://arb1.arbitrum.io/rpc'].filter(Boolean) },
  { id: 10,    name: 'Optimism',      short: 'OP',        color: '#FF0420', rpc: [_alch('opt-mainnet'), _inf('optimism-mainnet'), 'https://mainnet.optimism.io'].filter(Boolean) },
  { id: 137,   name: 'Polygon',       short: 'POL',       color: '#8247E5', rpc: [_alch('polygon-mainnet'), _inf('polygon-mainnet'), 'https://polygon-rpc.com'].filter(Boolean) },
  { id: 56,    name: 'BNB Chain',     short: 'BNB',       color: '#F0B90B', rpc: ['https://bsc-dataseed.binance.org', 'https://bsc-dataseed1.ninicoin.io'] },
  { id: 43114, name: 'Avalanche',     short: 'AVAX',      color: '#E84142', rpc: [_inf('avalanche-mainnet'), 'https://api.avax.network/ext/bc/C/rpc'].filter(Boolean) },
  { id: 324,   name: 'ZKsync Era',    short: 'ZK',        color: '#8C8DFC', rpc: [_alch('zksync-mainnet'), 'https://mainnet.era.zksync.io'].filter(Boolean) },
  { id: 42220, name: 'Celo',          short: 'CELO',      color: '#35D07F', rpc: [_inf('celo-mainnet'), 'https://forno.celo.org'].filter(Boolean) },
  { id: 81457, name: 'Blast',         short: 'BLAST',     color: '#FCFC03', rpc: [_alch('blast-mainnet'), 'https://rpc.blast.io'].filter(Boolean) },
  // ── Testnet ──
  { id: 84532, name: 'Base Sepolia',  short: 'Sepolia',   color: '#ffb800', rpc: [_alch('base-sepolia'), 'https://sepolia.base.org'].filter(Boolean), testnet: true },
]

function NetworkTokenWidget({
  onChainSelect,
  selectedToken,
  onTokenSelect,
  selectedChainId,
  walletAddress,
  tokenBalanceFmt,
  tokenBalanceEur,
  tokenBalanceLoading,
  onFamilyChange,
}: {
  onChainSelect?: (chainId: number) => void
  selectedToken: TokenInfo | null
  onTokenSelect: (token: TokenInfo) => void
  selectedChainId: number
  walletAddress?: `0x${string}`
  tokenBalanceFmt: string
  tokenBalanceEur: number | null
  tokenBalanceLoading: boolean
  onFamilyChange?: (family: ChainFamily) => void
}) {
  const chainId = useChainId()
  const { switchChain } = useSwitchChain()
  const { isConnected } = useAccount()
  const [gas, setGas] = useState<number | null>(null)
  const [openPanel, setOpenPanel] = useState<'chain' | 'token' | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const wallet = useUniversalWallet()
  const isEvmActive = wallet.activeFamily === 'evm'
  const tron = useTron()
  const { connecting: solanaConnecting } = useSolanaWallet()
  const { setVisible: setSolanaModalVisible } = useWalletModal()

  const chain = CHAINS.find(c => c.id === chainId) ?? CHAINS[0]
  const isTestnet = !!(chain as typeof CHAINS[number] & { testnet?: boolean }).testnet
  const chainTokens = getTokensForChain(selectedChainId)

  // Gas polling with RPC fallback
  useEffect(() => {
    const rpcs = chain.rpc
    const f = async () => {
      for (const rpc of rpcs) {
        try {
          const r = await fetch(rpc, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_gasPrice', params: [] }),
            signal: AbortSignal.timeout(5000),
          })
          if (!r.ok) continue
          const data = await r.json()
          if (data.result) { setGas(parseInt(data.result, 16) / 1e9); return }
        } catch { /* try next RPC */ }
      }
    }
    f(); const iv = setInterval(f, 30000); return () => clearInterval(iv)
  }, [chain.rpc])

  // Close on outside click
  useEffect(() => {
    if (!openPanel) return
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpenPanel(null) }
    const t = setTimeout(() => document.addEventListener('mousedown', h), 30)
    return () => { clearTimeout(t); document.removeEventListener('mousedown', h) }
  }, [openPanel])

  // Close on ESC
  useEffect(() => {
    if (!openPanel) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpenPanel(null) }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [openPanel])

  const gasLevel = gas === null ? 'unknown' : gas < 0.02 ? 'low' : gas < 0.1 ? 'med' : 'high'
  const gasColor = gasLevel === 'low' ? C.green : gasLevel === 'med' ? '#ffb800' : gasLevel === 'high' ? '#FF4C6A' : C.dim

  // Format balance for display
  const fmtBal = (() => {
    const v = parseFloat(tokenBalanceFmt || '0')
    if (selectedToken && ['USDC', 'USDT', 'DAI', 'EURC'].includes(selectedToken.symbol))
      return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    if (selectedToken && ['cbBTC', 'WBTC'].includes(selectedToken.symbol))
      return v.toFixed(6)
    return v.toFixed(4)
  })()

  if (!isConnected) return null

  return (
    <div ref={ref} style={{
      position: 'fixed', top: 68, right: 24, zIndex: 999,
      display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6,
    }}>
      {/* ── Chain family switch: EVM / Solana / Tron ──────── */}
      <ChainFamilySwitch
        active={wallet.activeFamily}
        onSelect={(family) => {
          wallet.setActiveFamily(family)
          onFamilyChange?.(family)
        }}
        connections={wallet.connections}
      />

      {/* ── Non-EVM wallet address display ───────────────── */}
      {!isEvmActive && (
        wallet.activeAddress ? (
          <div
            className="bf-blur-16"
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: C.surface,
              borderRadius: 14, padding: '8px 14px',
              border: '1px solid rgba(10,10,10,0.12)',
            }}
          >
            <div style={{
              width: 7, height: 7, borderRadius: '50%',
              background: '#00D68F', boxShadow: '0 0 6px #00D68F60',
            }} />
            <span style={{ fontFamily: C.M, fontSize: 11, color: C.text }}>
              {wallet.activeAddress.display}
            </span>
            <span style={{ fontFamily: C.D, fontSize: 10, color: C.dim, textTransform: 'uppercase' }}>
              {wallet.activeFamily}
            </span>
          </div>
        ) : (() => {
          const isTron = wallet.activeFamily === 'tron'
          const tronMissing = isTron && !tron.isInstalled
          const connecting = isTron ? tron.isConnecting : solanaConnecting
          const label = tronMissing
            ? 'Install TronLink \u2197'
            : connecting
            ? 'Connecting…'
            : `Connect ${isTron ? 'TronLink' : 'Phantom'}`
          const handleClick = () => {
            if (connecting) return
            if (tronMissing) {
              window.open('https://www.tronlink.org/', '_blank', 'noopener,noreferrer')
              return
            }
            if (isTron) tron.connect()
            else setSolanaModalVisible(true)
          }
          return (
            <button
              type="button"
              onClick={handleClick}
              disabled={connecting}
              onMouseEnter={e => {
                if (connecting) return
                e.currentTarget.style.filter = 'brightness(1.15)'
                e.currentTarget.style.transform = 'scale(1.03)'
                e.currentTarget.style.boxShadow = '0 4px 18px rgba(200,81,44,0.45)'
              }}
              onMouseLeave={e => {
                if (connecting) return
                e.currentTarget.style.filter = 'brightness(1)'
                e.currentTarget.style.transform = 'scale(1)'
                e.currentTarget.style.boxShadow = '0 2px 12px rgba(200,81,44,0.30)'
              }}
              style={{
                fontFamily: C.D, fontSize: 12, fontWeight: 700, color: '#fff',
                letterSpacing: '0.02em',
                background: 'linear-gradient(135deg, #C8512C, #C8512C)',
                border: 'none', borderRadius: 10,
                padding: '8px 18px',
                cursor: connecting ? 'default' : 'pointer',
                opacity: connecting ? 0.7 : 1,
                boxShadow: '0 2px 12px rgba(200,81,44,0.30)',
                transition: 'filter 0.15s, transform 0.15s, box-shadow 0.15s, opacity 0.15s',
              }}
            >
              {label}
            </button>
          )
        })()
      )}

      {/* ── Unified pill: Chain | Token | Gas (EVM only) ──── */}
      {isEvmActive && <div
        className="bf-blur-16"
        style={{
          display: 'flex', alignItems: 'center',
          background: C.surface,
          borderRadius: 14,
          border: `1px solid ${openPanel ? 'rgba(10,10,10,0.12)' : 'rgba(10,10,10,0.12)'}`,
          transition: 'border-color 0.2s ease',
          overflow: 'hidden',
        }}
      >
        {/* Network section */}
        <button
          onClick={() => setOpenPanel(openPanel === 'chain' ? null : 'chain')}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 10px',
            background: openPanel === 'chain' ? 'rgba(10,10,10,0.04)' : 'transparent',
            border: 'none', cursor: 'pointer', transition: 'background 0.15s',
            borderRight: '1px solid rgba(10,10,10,0.06)',
          }}
        >
          <ChainLogo chainId={chain.id} size={20} />
          <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text }}>{chain.short}</span>
          {isTestnet && (
            <span style={{ fontFamily: C.M, fontSize: 8, fontWeight: 700, color: '#ffb800', background: 'rgba(255,184,0,0.1)', padding: '1px 4px', borderRadius: 3, lineHeight: '1.2' }}>TEST</span>
          )}
          <span style={{ color: C.dim, fontSize: 7 }}>▾</span>
        </button>


        {/* Gas section */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '7px 10px 7px 8px',
        }}>
          <div style={{ width: 5, height: 5, borderRadius: '50%', background: gasColor, boxShadow: `0 0 4px ${gasColor}50` }} />
          <span style={{ fontFamily: C.M, fontSize: 10, color: gasColor, fontWeight: 600 }}>
            {gas !== null ? gas.toFixed(4) : '—'}
          </span>
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>Gwei</span>
        </div>
      </div>}

      {/* ── Balance sub-line (EVM only) ───────────────────── */}
      {isEvmActive && selectedToken && !tokenBalanceLoading && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          paddingRight: 4,
        }}>
          <span style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
            {fmtBal} {selectedToken.symbol}
          </span>
          {tokenBalanceEur !== null && (
            <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>
              ≈ €{tokenBalanceEur >= 1 ? tokenBalanceEur.toFixed(2) : tokenBalanceEur.toFixed(4)}
            </span>
          )}
        </div>
      )}

      {/* ── Chain dropdown (EVM only) ─────────────────────── */}
      <AnimatePresence>
        {openPanel === 'chain' && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15, ease: [0.4, 0, 0.2, 1] }}
            style={{
              position: 'absolute', top: 'calc(100%)', right: 0, zIndex: 100,
              minWidth: 220, maxHeight: 300, overflowY: 'auto' as const, background: '#FFFFFF',
              border: '1px solid rgba(10,10,10,0.10)',
              borderRadius: 14,
              boxShadow: '0 16px 48px rgba(0,0,0,0.7), 0 0 0 1px rgba(10,10,10,0.03)',
            }}
          >
            <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid rgba(10,10,10,0.05)' }}>
              <span style={{ fontFamily: C.D, fontSize: 10, fontWeight: 700, color: C.dim, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>Network</span>
            </div>
            {CHAINS.map(c => {
              const active = chainId === c.id
              const test = !!(c as typeof c & { testnet?: boolean }).testnet
              return (
                <button
                  key={c.id}
                  onClick={() => { switchChain({ chainId: c.id }); onChainSelect?.(c.id); setOpenPanel(null) }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px', background: active ? 'rgba(10,10,10,0.04)' : 'transparent',
                    border: 'none', cursor: 'pointer', transition: 'background 0.12s',
                    borderBottom: '1px solid rgba(10,10,10,0.04)',
                    textAlign: 'left' as const,
                  }}
                  onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'rgba(10,10,10,0.03)' }}
                  onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent' }}
                >
                  <ChainLogo chainId={c.id} size={22} />
                  <div style={{ flex: 1 }}>
                    <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: active ? C.text : C.sub }}>{c.name}</span>
                    {test && <span style={{ fontFamily: C.M, fontSize: 8, color: '#ffb800', marginLeft: 6 }}>testnet</span>}
                  </div>
                  {active && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontFamily: C.M, fontSize: 10, color: gasColor }}>{gas !== null ? gas.toFixed(4) : '—'}</span>
                      <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>gwei</span>
                      <div style={{ width: 5, height: 5, borderRadius: '50%', background: C.green }} />
                    </div>
                  )}
                </button>
              )
            })}
            <div style={{ padding: '8px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              {[
                { l: 'Low', c: C.green },
                { l: 'Med', c: '#ffb800' },
                { l: 'High', c: '#FF4C6A' },
              ].map(g => (
                <div key={g.l} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 4, height: 4, borderRadius: '50%', background: g.c }} />
                  <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>{g.l}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Token dropdown ────────────────────────────────── */}
      <AnimatePresence>
        {openPanel === 'token' && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.97 }}
            transition={{ duration: 0.15, ease: [0.4, 0, 0.2, 1] }}
            style={{
              position: 'absolute', top: 'calc(100%)', right: 0, zIndex: 100,
              minWidth: 240, background: '#FFFFFF',
              border: '1px solid rgba(10,10,10,0.10)',
              borderRadius: 14, overflow: 'hidden',
              boxShadow: '0 16px 48px rgba(0,0,0,0.7), 0 0 0 1px rgba(10,10,10,0.03)',
            }}
          >
            <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid rgba(10,10,10,0.05)' }}>
              <span style={{ fontFamily: C.D, fontSize: 10, fontWeight: 700, color: C.dim, textTransform: 'uppercase' as const, letterSpacing: '0.08em' }}>Select Token</span>
            </div>
            <div style={{ maxHeight: 320, overflowY: 'auto' }}>
              {chainTokens.map(token => {
                const active = selectedToken?.symbol === token.symbol && selectedToken?.chainId === token.chainId
                return (
                  <TokenRow
                    key={`${token.chainId}-${token.symbol}`}
                    token={token}
                    isSelected={active}
                    walletAddress={walletAddress}
                    onSelect={(t) => { onTokenSelect(t); setOpenPanel(null) }}
                  />
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  LIQUID GLASS NAVBAR
// ═══════════════════════════════════════════════════════════
function Navbar({
  sweeps24h, vol24h,
}: {
  sweeps24h: number
  vol24h: number
}) {
  const [isMobile, setIsMobile] = useState(false)
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  return (
    <nav className="bf-blur-24s" style={{
      position: 'fixed', top: 3, left: 0, right: 0, zIndex: 1000,
      height: isMobile ? 52 : 60,
      paddingTop: 'var(--sat, 0px)',
      background: 'rgba(250,250,250,0.85)',
      borderBottom: '1px solid rgba(10,10,10,0.08)',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: isMobile ? '0 12px' : '0 24px',
    }}>
        {/* Left: Logo */}
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
          }}
        >
          <img src="/favicon.svg" alt="RSends" width={28} height={28} style={{ borderRadius: 7 }} />
          <span style={{ fontFamily: C.D, fontSize: 16, fontWeight: 800, color: C.text, letterSpacing: '-0.03em' }}>
            RSends
          </span>
        </div>

        {/* Right: Language + Auth */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <LanguageSwitcher />
          <LandingAuthButtons />
        </div>
    </nav>
  )
}

// ════════��══════════════════════════════════════════════════
//  ENGINE STATUS (compact for navbar)
// ═══════════════════════════════════════════════════════════
function EngineStatus() {
  const { isConnected } = useAccount()
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '5px 12px', borderRadius: 16,
      background: 'rgba(10,10,10,0.04)',
      border: `1px solid ${C.border}`,
    }}>
      <div style={{ position: 'relative', width: 7, height: 7 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: isConnected ? C.green : C.dim }} />
        {isConnected && <div style={{ position: 'absolute', inset: -3, borderRadius: '50%', border: `2px solid ${C.green}`, animation: 'rsPulse 2s ease infinite' }} />}
      </div>
      <span style={{ fontFamily: C.M, fontSize: 9, fontWeight: 600, color: isConnected ? C.green : C.dim }}>
        {isConnected ? 'ONLINE' : 'OFFLINE'}
      </span>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  HERO TITLE — AnimatePresence mode="wait" for no overlap
// ═══════════════════════════════════════════════════════════

function HeroTitle({ isMobile }: { isMobile?: boolean }) {
  const t = useTranslations('hero')
  const HERO_EASE = [0.22, 1, 0.36, 1] as [number, number, number, number]

  return (
    <div style={{
      width: '100%',
      maxWidth: 1440,
      margin: '0 auto',
      padding: isMobile ? '0 20px' : '0 96px',
      textAlign: isMobile ? 'center' : 'left',
      position: 'relative',
      zIndex: 2,
    }}>
      {/* Eyebrow — 0.0s (hidden when empty) */}
      {t('eyebrow') && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: HERO_EASE }}
          style={{
            fontFamily: C.M,
            fontSize: 16,
            fontWeight: 500,
            color: C.purple,
            letterSpacing: '0.18em',
            marginBottom: 8,
            textTransform: 'uppercase' as const,
          }}
        >
          {t('eyebrow')}
        </motion.div>
      )}

      {/* Title — split reveal 0.15s / 0.45s / 0.75s */}
      <h1 style={{
        fontFamily: C.D,
        fontSize: isMobile ? 56 : 'clamp(74px, 8vw, 96px)',
        fontWeight: 500,
        color: C.text,
        lineHeight: 1.1,
        letterSpacing: '-0.02em',
        margin: '0 0 24px',
        maxWidth: 880,
      }}>
        <SplitText text={t('titleLine1')} delay={0.15} style={{ fontFamily: C.D }} />
        <br/>
        <SplitText text={t('titleLine2')} delay={0.45} style={{ fontFamily: C.D }} />
        <br/>
        <SplitText text={t('titleLine3')} delay={0.75} style={{ fontFamily: C.D }} />
      </h1>

      {/* Subtitle — 0.95s */}
      <motion.p
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.95, ease: HERO_EASE }}
        style={{
          fontFamily: C.D,
          fontSize: isMobile ? 17 : 19,
          color: C.sub,
          lineHeight: 1.6,
          margin: '0 0 28px',
          maxWidth: 560,
        }}
      >
        {t('subtitle')}
      </motion.p>

      {/* CTAs — 1.15s, hover lift */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 1.15, ease: HERO_EASE }}
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'center',
          marginBottom: 32,
          flexWrap: 'wrap',
          justifyContent: isMobile ? 'center' : 'flex-start',
        }}
      >
        <Link href="/login" style={{ textDecoration: 'none', width: isMobile ? '100%' : 'auto' }}>
          <motion.button
            whileHover={{ y: -2 }}
            whileTap={{ y: 0, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 400, damping: 28 }}
            style={{
              padding: '14px 28px',
              minHeight: 48,
              width: isMobile ? '100%' : 'auto',
              background: C.text,
              color: C.bg,
              border: 'none',
              borderRadius: 3,
              fontFamily: C.D,
              fontSize: 16,
              fontWeight: 500,
              cursor: 'pointer',
              letterSpacing: 0,
            }}
          >
            {t('ctaPrimary')}
          </motion.button>
        </Link>
      </motion.div>

      {/* Divider — scaleX reveal 1.35s */}
      <motion.div
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 1.2, delay: 1.35, ease: HERO_EASE }}
        style={{
          transformOrigin: 'left',
          height: '0.5px',
          background: C.border,
          maxWidth: 1600,
          marginTop: 28,
          marginBottom: 8,
        }}
      />

      {/* Supported Networks carousel — replaces old metrics row */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 1.5, ease: HERO_EASE }}
        style={{ marginLeft: isMobile ? -20 : -96, marginRight: isMobile ? -20 : -96 }}
      >
        <SupportedNetworksCarousel />
      </motion.div>
    </div>
  )
}


      





// ═══════════════════════════════════════════════════════════
//  MAIN PAGE
// ═══════════════════════════════════════════════════════════
export default function Home() {
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const walletInfo = useUniversalWallet()
  const [activeFamily, setActiveFamily] = useState<ChainFamily>('evm')
  const wallet = { ...walletInfo, activeFamily }

  // Non-EVM disconnect hooks
  const { disconnect: solanaDisconnect } = useSolanaWallet()
  const tron = useTron()

  // Build nonEvmWallet prop for AccountHeader when on Tron/Solana
  const nonEvmWallet: NonEvmWalletProps | undefined = (() => {
    if (activeFamily === 'evm') return undefined
    const conn = activeFamily === 'tron' ? wallet.connections.tron : wallet.connections.solana
    if (!conn?.address) return undefined
    return {
      family: activeFamily as 'tron' | 'solana',
      address: conn.address,
      disconnect: activeFamily === 'tron' ? tron.disconnect : solanaDisconnect,
    }
  })()
  const [showIntro, setShowIntro] = useState(false)
  const [ready, setReady] = useState(false)
  const [showAntiPhishing, setShowAntiPhishing] = useState(false)
  const [isMobileHome, setIsMobileHome] = useState(false)
  // Globe panel only renders when the split hero has room for it beside the text.
  const [globeFits, setGlobeFits] = useState(false)
  useEffect(() => {
    const check = () => {
      setIsMobileHome(window.innerWidth < 768)
      setGlobeFits(window.innerWidth >= 1024)
    }
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  // ── Multi-token/chain selector state ──────────────────────────────────
  const [selectedChainId, setSelectedChainId] = useState<number>(chainId)
  const [selectedToken, setSelectedToken] = useState<TokenInfo | null>(
    () => getNativeToken(chainId) ?? null,
  )
  // Sync when wallet chain changes
  useEffect(() => {
    setSelectedChainId(chainId)
    setSelectedToken(getNativeToken(chainId) ?? null)
  }, [chainId])

  // ── Selected token balance + EUR for inline display ────────────────
  const { balance: selTokenBal, formatted: selTokenFmt, isLoading: selTokenLoading } = useTokenBalance(selectedToken, address)
  const { prices: tokenPricesPage } = useTokenPrices()
  const selTokenEur = selectedToken && tokenPricesPage[selectedToken.coingeckoId]?.eur
    ? parseFloat(selTokenFmt) * tokenPricesPage[selectedToken.coingeckoId].eur
    : null

  // Sweep stats for top bar
  const { daily } = useSweepStats(address)
  const today = daily.length > 0 ? daily[daily.length - 1] : null
  const sweeps24h = today?.sweep_count ?? 0
  const vol24h = today?.volume_eth ?? 0

  // Track unseen sweep events for Flow badge
  const { events: sweepEvents } = useSweepWebSocket(address)
  const [unseenCount, setUnseenCount] = useState(0)
  const lastSeenRef = useRef(0)

  // Increment unseen when new events arrive and user isn't on command tab
  useEffect(() => {
    if (sweepEvents.length > lastSeenRef.current) {
      setUnseenCount(prev => prev + (sweepEvents.length - lastSeenRef.current))
      lastSeenRef.current = sweepEvents.length
    }
  }, [sweepEvents.length])

  useEffect(() => { setReady(true) }, [])

  // Parallax — orbs layer drifts at 15% of scroll velocity for depth.
  // .rp-bg is position:fixed, so the container's translate is all the movement.
  const orbLayerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let ticking = false
    let lastScrollY = 0
    const onScroll = () => {
      lastScrollY = window.scrollY
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        if (orbLayerRef.current) {
          orbLayerRef.current.style.transform = `translate3d(0, ${lastScrollY * 0.15}px, 0)`
        }
        ticking = false
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <SmoothScroll>
      <ToastContainer />
      {/* Background */}
      <div className="rp-bg" aria-hidden="true">
        <div className="rp-bg__base" />
        <div ref={orbLayerRef} style={{ position: 'absolute', inset: 0, willChange: 'transform' }}>
          <div className="rp-orb rp-orb--1" style={{ opacity: 1 }} />
          <div className="rp-orb rp-orb--2" style={{ opacity: 1 }} />
          <div className="rp-orb rp-orb--3" style={{ opacity: 1 }} />
          <div className="rp-orb rp-orb--4" style={{ opacity: 1 }} />
          <div className="rp-orb rp-orb--5" style={{ opacity: 1 }} />
          <div className="rp-orb rp-orb--9" style={{ opacity: 2 }} />
          <div className="rp-orb rp-orb--6" style={{ opacity: 0.65 }} />
          <div className="rp-orb rp-orb--7" style={{ opacity: 0.55 }} />
          <div className="rp-orb rp-orb--8" style={{ opacity: 0.50 }} />
        </div>
        <div className="rp-bg__noise" />
      </div>

      {/* Top bar accent — ink line with terracotta segment left */}
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0,
        height: 3, background: C.text, zIndex: 1001,
      }}>
        <div style={{
          position: 'absolute', top: 0, left: 0,
          width: 96, height: 3, background: C.purple,
        }} />
      </div>

      {/* Navbar */}
      <Navbar sweeps24h={sweeps24h} vol24h={vol24h} />

      {/* Main content — padded below navbar */}
      <main className="main-content" style={{
        minHeight: '100dvh',
        paddingTop: isMobileHome ? '72px' : 'clamp(64px, 6vh, 88px)',
        paddingBottom: isMobileHome ? '40px' : '120px',
        display: 'flex', flexDirection: 'column', alignItems: 'stretch',
        opacity: ready ? 1 : 0, transition: 'opacity 0.9s ease',
      }}>

        {/* Hero */}
        <div style={{ width: '100%', position: 'relative' }}>
          <HeroTitle isMobile={isMobileHome} />
          {globeFits && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: '-50%' }}
              animate={{ opacity: 1, scale: 1, y: '-50%' }}
              transition={{ duration: 1.2, delay: 0.4, ease: [0.22, 1, 0.36, 1] }}
              style={{
                position: 'absolute',
                right: '2%',
                top: '50%',
                width: 'clamp(360px, calc(120vw - 820px), 920px)',
                height: 'clamp(300px, 42vw, 520px)',
                zIndex: 1,
                pointerEvents: 'none',
              }}
            >
              <HeroGlobe />
            </motion.div>
          )}
        </div>

      </main>

      {/* ── Why Sign In value props ──── */}
      <WhySignInSection />

      {/* ── B2B Landing Sections ──── */}
      <LandingSections />

      {/* ── Get started closing block ──── */}
      <GetStartedSection />

      

      {/* Anti-Phishing Setup Modal */}
      <AntiPhishingSetup
        isOpen={showAntiPhishing}
        onClose={() => setShowAntiPhishing(false)}
        onSave={(code) => {
          localStorage.setItem('rsend_antiphishing_code', code)
          setShowAntiPhishing(false)
        }}
      />

      <style>{`
        @keyframes rsPulse{0%{transform:scale(1);opacity:.8}50%{transform:scale(1.8);opacity:0}100%{transform:scale(1);opacity:0}}
        @keyframes holoShift{0%{background-position:0% 50%}100%{background-position:200% 50%}}
        @keyframes rsSpin{100%{transform:rotate(360deg)}}
        @keyframes rpCtaPulse{0%,100%{transform:scale(1);box-shadow:0 4px 24px rgba(59,130,246,0.3)}50%{transform:scale(1.02);box-shadow:0 6px 32px rgba(59,130,246,0.45)}}
      `}</style>
    </SmoothScroll>
  )
}