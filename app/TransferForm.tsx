'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import {
  useAccount, useBalance, useReadContracts,
  useWriteContract, useWaitForTransactionReceipt,
  usePublicClient, useChainId, useSwitchChain,
  useSendTransaction,
} from 'wagmi'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import {
  parseEther, parseUnits, formatEther, formatUnits,
  erc20Abi, isAddress, getAddress, type Abi,
} from 'viem'
import { baseSepolia } from 'wagmi/chains'
import {
  TransactionStatusUI, AddressVerifier, BallisticProgress, MicroStateBadge,
} from './TransactionStatus'
import { useComplianceEngine, type ComplianceRecord } from '../lib/useComplianceEngine'
import { useComplianceAPI }   from '../lib/useComplianceAPI'
import { generatePdfReceipt, type PdfReceiptParams } from '../lib/usePdfReceipt'
import {
  getRegistry, findChainForToken, EUR_RATES, isFeeRouterAvailable,
  type TokenConfig, type NetworkRegistry,
} from '../lib/contractRegistry'
import { useSwapQuote, useDirectQuote } from '../lib/useSwapQuote'
import { UNISWAP_V3_ROUTER_ABI } from '../src/constants/abis/uniswapV3Router'
import { useBackendCallback } from '../lib/useBackendCallback'
import { mutationHeaders } from '../lib/rsendFetch'
import TxConfirmationSheet, { isKnownRecipient, saveKnownRecipient } from './TxConfirmationSheet'
import { SUPPORTED_CHAINS, type ChainId, type TokenInfo, TOKEN_LIST } from './tokens/tokenRegistry'
import { getCCIPConfig, getCCIPChainSelector, CCIP_SUPPORTED_TOKENS } from '@/lib/ccipRegistry'
import { ChainLogo, CHAIN_META } from '../src/components/ChainLogo'
import { useTokenPrices } from './hooks/useTokenPrices'
import { useTokenBalance } from './hooks/useTokenBalance'
import AddressIntelligence, { recordSuccessfulTx } from './AddressIntelligence'
import { useTabLock } from '../lib/useTabLock'
import { useIdempotencyKey } from '../lib/useIdempotencyKey'
import { useKeyboardShortcuts } from '../lib/useKeyboardShortcuts'
import { useClipboardDetection } from '../lib/useClipboardDetection'
import { logger } from '../lib/logger'
import { FEE_ROUTER_V6_ABI } from '../lib/feeRouterAbi'
import { useIsMobile } from '../hooks/useIsMobile'
import { useTranslations } from 'next-intl'
import { useLocale } from 'next-intl'
import { emitTxSubmitted, emitTxConfirmed } from '@/lib/tx-events'

// ── Theme ──────────────────────────────────────────────────────────────────
import { C } from '@/app/designTokens'
const T = {
  ...C,
  // Semantic status colors — mature, low-saturation palette coherent with terracotta brand
  emerald: '#16A34A',   // Success (deep forest green, non-fluo)
  red:     '#B84242',   // Danger (terracotta-adjacent, consistent with brand warmth)
  amber:   '#A07C11',   // Warning (ochre, sober)
  // Aliases
  muted:   C.sub,       // Alias for secondary text color (keeps existing API)
  pink:    C.purple,    // Alias for brand accent terracotta (keeps existing API)
}

// ── ABI FeeRouterV3/V4 ─────────────────────────────────────────────────────
const FEE_ROUTER_ABI: Abi = [
  {
    name: 'transferWithOracle', type: 'function', stateMutability: 'nonpayable',
    inputs: [
      { name: '_token', type: 'address' }, { name: '_amount', type: 'uint256' },
      { name: '_recipient', type: 'address' }, { name: '_nonce', type: 'bytes32' },
      { name: '_deadline', type: 'uint256' }, { name: '_oracleSignature', type: 'bytes' },
    ], outputs: [],
  },
  {
    name: 'transferETHWithOracle', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: '_recipient', type: 'address' }, { name: '_nonce', type: 'bytes32' },
      { name: '_deadline', type: 'uint256' }, { name: '_oracleSignature', type: 'bytes' },
    ], outputs: [],
  },
  {
    name: 'swapAndSend', type: 'function', stateMutability: 'nonpayable',
    inputs: [
      { name: 'tokenIn', type: 'address' }, { name: 'tokenOut', type: 'address' },
      { name: 'amountIn', type: 'uint256' }, { name: 'minAmountOut', type: 'uint256' },
      { name: 'recipient', type: 'address' }, { name: 'nonce', type: 'bytes32' },
      { name: 'deadline', type: 'uint256' }, { name: 'oracleSignature', type: 'bytes' },
    ], outputs: [],
  },
  {
    name: 'swapETHAndSend', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: 'tokenOut', type: 'address' }, { name: 'minAmountOut', type: 'uint256' },
      { name: 'recipient', type: 'address' }, { name: 'nonce', type: 'bytes32' },
      { name: 'deadline', type: 'uint256' }, { name: 'oracleSignature', type: 'bytes' },
    ], outputs: [],
  },
  // View helpers
  { name: 'oracleSigner', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ name: '', type: 'address' }] },
  { name: 'domainSeparator', type: 'function', stateMutability: 'view', inputs: [], outputs: [{ name: '', type: 'bytes32' }] },
  // Custom errors — per decodifica errori leggibili
  { name: 'ZeroAddress', type: 'error', inputs: [] },
  { name: 'ZeroAmount', type: 'error', inputs: [] },
  { name: 'FeeTooHigh', type: 'error', inputs: [] },
  { name: 'ETHTransferFailed', type: 'error', inputs: [] },
  { name: 'DeadlineExpired', type: 'error', inputs: [] },
  { name: 'OracleSignatureInvalid', type: 'error', inputs: [] },
  { name: 'NonceAlreadyUsed', type: 'error', inputs: [] },
  { name: 'RecipientBlacklisted', type: 'error', inputs: [] },
  { name: 'TokenNotAllowed', type: 'error', inputs: [] },
]

// ── CCIP Sender ABI (cross-chain) ──────────────────────────────────────────
const CCIP_SENDER_ABI: Abi = [
  {
    name: 'swapAndBridge', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: 'tokenIn', type: 'address' }, { name: 'tokenOut', type: 'address' },
      { name: 'amountIn', type: 'uint256' }, { name: 'minAmountOut', type: 'uint256' },
      { name: 'destinationChainSelector', type: 'uint64' }, { name: 'recipient', type: 'address' },
    ], outputs: [],
  },
  {
    name: 'swapETHAndBridge', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: 'tokenOut', type: 'address' }, { name: 'amountIn', type: 'uint256' },
      { name: 'minAmountOut', type: 'uint256' }, { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
    ], outputs: [],
  },
  {
    name: 'sendCrossChain', type: 'function', stateMutability: 'payable',
    inputs: [
      { name: 'destinationChainSelector', type: 'uint64' }, { name: 'recipient', type: 'address' },
      { name: 'token', type: 'address' }, { name: 'amount', type: 'uint256' },
    ], outputs: [],
  },
]

// ── Chain colors & names (cross-chain UI) ──────────────────────────────────
const CHAIN_COLORS: Record<number, string> = {
  8453:'#0052FF', 1:'#627EEA', 42161:'#28A0F0', 10:'#FF0420',
  137:'#8247E5', 56:'#F3BA2F', 43114:'#E84142', 324:'#8C8DFC',
  42220:'#FCFF52', 81457:'#FCFC03', 84532:'#0052FF',
}
const CHAIN_NAMES: Record<number, string> = {
  8453:'Base', 1:'Ethereum', 42161:'Arbitrum', 10:'Optimism',
  137:'Polygon', 56:'BNB', 43114:'Avalanche', 324:'ZKsync',
  42220:'Celo', 81457:'Blast', 84532:'Sepolia',
}

type RouteType = 'direct' | 'swap' | 'bridge' | 'swapAndBridge'

type Phase    = 'idle' | 'preflight' | 'approving' | 'wait_approve' | 'signing' | 'wait_send' | 'done' | 'error'
type CtaState = 'disconnected' | 'wrong_network' | 'insufficient' | 'no_recipient' | 'no_amount' | 'oracle_denied' | 'no_liquidity' | 'ready' | 'busy'
type SelectingToken = 'in' | 'out' | null

interface OracleResponse {
  approved: boolean
  oracleSignature: string; oracleSignatures?: string[]; oracleNonce: string; oracleDeadline: number
  paymentRef: string; fiscalRef: string
  riskScore: number; riskLevel: string
  eurValue?: number; isEurc?: boolean; isSwap?: boolean
  sourceChain?: string; gasless?: boolean; rejectionReason?: string
}

function txLog(event: string, data: Record<string, unknown>) {
  const entry = { event, ts: new Date().toISOString(), ...data }
  logger.debug('TransferForm', `tx:${event}`, entry)
  try {
    const raw = localStorage.getItem('rp_tx_history')
    const h: unknown[] = raw ? JSON.parse(raw) : []
    h.push(entry); if (h.length > 200) h.splice(0, h.length - 200)
    localStorage.setItem('rp_tx_history', JSON.stringify(h))
  } catch (err) {
    logger.warn('TransferForm', 'Failed to persist tx history', { error: String(err) })
  }
}

// ── Token Logo ─────────────────────────────────────────────────────────────
function TokenLogo({ token, size = 24 }: {
  token: Pick<TokenConfig, 'symbol' | 'logoURI' | 'isNative'>
  size?: number
}) {
  const [err, setErr] = useState(false)
  const colorMap: Record<string, string> = {
    ETH:'#627EEA', USDC:'#2775CA', USDT:'#26A17B',
    EURC:'#0033cc', cbBTC:'#F7931A', WBTC:'#F7931A',
    DEGEN:'#845ef7', WETH:'#627EEA',
  }
  const color = colorMap[token.symbol] ?? '#4a4a6a'
  return (
    <div style={{ width:size, height:size, borderRadius:'50%', overflow:'hidden', flexShrink:0, background:err?color:'transparent', display:'flex', alignItems:'center', justifyContent:'center', border:'1.5px solid rgba(10,10,10,0.1)' }}>
      {!err
        ? <img src={token.logoURI} alt={token.symbol} width={size} height={size}
            style={{ width:'100%', height:'100%', objectFit:'cover' }}
            onError={() => setErr(true)} />
        : <span style={{ fontSize:size*0.36, fontWeight:800, color:'#fff', fontFamily:T.D }}>
            {token.symbol.slice(0,2)}
          </span>
      }
    </div>
  )
}

// ── Token Pill — bottone nel form che apre la modale ──────────────────────
function TokenPill({ token, onClick, accentColor, busy }: {
  token: (TokenConfig & { balance: bigint }) | null
  onClick: () => void
  accentColor?: string
  busy: boolean
}) {
  const [hovered, setHovered] = useState(false)
  const accent = accentColor ?? T.emerald
  return (
    <button
      type="button"
      onClick={e => { e.stopPropagation(); if (!busy) onClick() }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '9px 13px 9px 9px', borderRadius: 18,
        background: hovered && !busy ? 'rgba(10,10,10,0.12)' : 'rgba(10,10,10,0.08)',
        border: `1px solid ${hovered && !busy ? 'rgba(10,10,10,0.18)' : 'rgba(10,10,10,0.1)'}`,
        cursor: busy ? 'default' : 'pointer',
        transition: 'all 0.15s ease',
        flexShrink: 0,
      }}
    >
      {token && <TokenLogo token={token} size={22} />}
      <span style={{ fontFamily:T.D, fontSize:15, fontWeight:700, color:T.text, letterSpacing:'-0.01em' }}>
        {token?.symbol ?? '—'}
      </span>
      {!busy && (
        <span style={{ color:T.muted, fontSize:9, display:'inline-block' }}>▾</span>
      )}
    </button>
  )
}

// ── Token Selector Modal — background solido opaco ────────────────────────
function TokenSelectorModal({ tokens, onSelect, onClose, title, isMobile, multiChainTokens, onSelectMultiChain, currentChainId }: {
  tokens: (TokenConfig & { balance: bigint })[]
  onSelect: (t: TokenConfig & { balance: bigint }) => void
  onClose: () => void
  title: string
  isMobile?: boolean
  multiChainTokens?: TokenInfo[]
  onSelectMultiChain?: (t: TokenInfo) => void
  currentChainId?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [search, setSearch] = useState('')
  const tr = useTranslations('send')

  // Chiudi cliccando fuori
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const timer = setTimeout(() => document.addEventListener('mousedown', h), 50)
    return () => { clearTimeout(timer); document.removeEventListener('mousedown', h) }
  }, [onClose])

  // Chiudi con ESC
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  const fmtBal = (t: TokenConfig & { balance: bigint }) => {
    const v = parseFloat(formatUnits(t.balance, t.decimals))
    return ['USDC','USDT','EURC'].includes(t.symbol) ? v.toFixed(2)
      : t.symbol === 'cbBTC' || t.symbol === 'WBTC' ? v.toFixed(6)
      : v.toFixed(4)
  }

  // Filter tokens by search
  const q = search.toLowerCase().trim()
  const filteredLocal = q ? tokens.filter(t =>
    t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q)
  ) : tokens
  const filteredMultiChain = multiChainTokens && q
    ? multiChainTokens.filter(t =>
        t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q) ||
        (CHAIN_NAMES[t.chainId] ?? '').toLowerCase().includes(q)
      )
    : multiChainTokens

  // Check if a cross-chain route is available (CCIP)
  const isCCIPRoute = (destChainId: number) => {
    if (!currentChainId) return false
    const src = CCIP_SUPPORTED_TOKENS[currentChainId]
    const dst = CCIP_SUPPORTED_TOKENS[destChainId]
    return !!(src && dst)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200,
      background: 'rgba(0,0,0,0.55)',
      display: 'flex', alignItems: isMobile ? 'flex-end' : 'center', justifyContent: 'center',
      padding: isMobile ? 0 : '16px',
    }}>
      <div
        ref={ref}
        style={{
          width: '100%', maxWidth: isMobile ? '100%' : 380,
          ...(isMobile ? { height: '85dvh' } : {}),
          background: '#FFFFFF',
          border: '1px solid rgba(10,10,10,0.10)',
          borderRadius: isMobile ? '20px 20px 0 0' : 20,
          boxShadow: '0 24px 80px rgba(0,0,0,0.9), 0 0 0 1px rgba(10,10,10,0.04)',
          overflow: 'hidden',
          display: 'flex', flexDirection: 'column' as const,
          animation: 'rpFadeUp 0.2s var(--ease-spring) both',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 18px 12px',
          borderBottom: '1px solid rgba(10,10,10,0.08)',
        }}>
          <span style={{ fontFamily:T.D, fontSize:15, fontWeight:800, color:T.text, letterSpacing:'-0.01em' }}>
            {title}
          </span>
          <button
            onClick={onClose}
            style={{ width:30, height:30, borderRadius:8, background:'rgba(10,10,10,0.08)', border:'none', color:T.muted, cursor:'pointer', fontSize:16, display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s' }}
            onMouseEnter={e => e.currentTarget.style.background='rgba(10,10,10,0.12)'}
            onMouseLeave={e => e.currentTarget.style.background='rgba(10,10,10,0.08)'}
          >&#x2715;</button>
        </div>

        {/* Search */}
        {multiChainTokens && (
          <div style={{ padding: '8px 18px 4px' }}>
            <input
              type="text"
              placeholder={tr('searchPlaceholder')}
              value={search}
              onChange={e => setSearch(e.target.value)}
              autoFocus
              style={{
                width: '100%', padding: '10px 14px', borderRadius: 12,
                border: '1px solid rgba(10,10,10,0.1)',
                background: 'rgba(10,10,10,0.04)',
                color: T.text, fontFamily: T.M, fontSize: 13, outline: 'none',
              }}
            />
          </div>
        )}

        {/* Token list */}
        <div style={{ overflowY: 'auto', ...(isMobile ? { flex: 1 } : { maxHeight: multiChainTokens ? 420 : 360 }) }}>
          {/* Same-chain tokens (with balance) */}
          {filteredLocal.length > 0 && (
            <>
              {multiChainTokens && (
                <div style={{ padding: '10px 18px 4px', fontFamily: T.D, fontSize: 10, fontWeight: 700, color: T.muted, letterSpacing: '0.08em', textTransform: 'uppercase' as const }}>
                  {CHAIN_NAMES[currentChainId ?? 0] ?? tr('currentChain')}
                </div>
              )}
              {filteredLocal.map((t, i) => (
                <button
                  key={`local-${t.symbol}`}
                  type="button"
                  onClick={() => { onSelect(t); onClose() }}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: 14,
                    padding: '13px 18px',
                    background: 'transparent', border: 'none',
                    borderBottom: i < filteredLocal.length - 1 ? '1px solid rgba(10,10,10,0.05)' : 'none',
                    cursor: 'pointer', transition: 'background 0.12s ease',
                    textAlign: 'left' as const,
                  }}
                  onMouseEnter={e => e.currentTarget.style.background='rgba(10,10,10,0.05)'}
                  onMouseLeave={e => e.currentTarget.style.background='transparent'}
                >
                  <TokenLogo token={t} size={36} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display:'flex', alignItems:'center', gap:7 }}>
                      <span style={{ fontFamily:T.D, fontSize:15, fontWeight:700, color:T.text }}>
                        {t.symbol}
                      </span>
                      {t.isEurc && (
                        <span style={{ fontFamily:T.D, fontSize:9, fontWeight:700, color:'#6699ff', background:'rgba(0,51,204,0.15)', padding:'2px 6px', borderRadius:4, border:'1px solid rgba(0,51,204,0.3)' }}>
                          &#x2605; EU
                        </span>
                      )}
                      {t.gasless && !t.isEurc && (
                        <span style={{ fontFamily:T.D, fontSize:9, color:T.emerald, background:'rgba(0,255,163,0.1)', padding:'2px 6px', borderRadius:4 }}>
                          Gasless
                        </span>
                      )}
                    </div>
                    <div style={{ fontFamily:T.M, fontSize:11, color:T.muted, marginTop:2 }}>
                      {t.name}
                    </div>
                  </div>
                  <div style={{ textAlign:'right' as const }}>
                    <div style={{ fontFamily:T.M, fontSize:13, fontWeight:600, color:T.text }}>
                      {fmtBal(t)}
                    </div>
                    <div style={{ fontFamily:T.M, fontSize:10, color:T.muted, marginTop:1 }}>
                      {t.symbol}
                    </div>
                  </div>
                </button>
              ))}
            </>
          )}

          {/* Cross-chain tokens */}
          {filteredMultiChain && filteredMultiChain.length > 0 && onSelectMultiChain && (
            <>
              <div style={{ padding: '12px 18px 4px', fontFamily: T.D, fontSize: 10, fontWeight: 700, color: T.muted, letterSpacing: '0.08em', textTransform: 'uppercase' as const, borderTop: '1px solid rgba(10,10,10,0.08)' }}>
                Cross-chain (CCIP)
              </div>
              {filteredMultiChain.map((t, i) => {
                const available = isCCIPRoute(t.chainId)
                return (
                  <button
                    key={`cc-${t.symbol}-${t.chainId}`}
                    type="button"
                    onClick={() => { if (available) { onSelectMultiChain(t); onClose() } }}
                    disabled={!available}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 14,
                      padding: '13px 18px',
                      background: 'transparent', border: 'none',
                      borderBottom: i < filteredMultiChain.length - 1 ? '1px solid rgba(10,10,10,0.05)' : 'none',
                      cursor: available ? 'pointer' : 'default',
                      opacity: available ? 1 : 0.35,
                      transition: 'background 0.12s ease',
                      textAlign: 'left' as const,
                    }}
                    onMouseEnter={e => { if (available) e.currentTarget.style.background='rgba(10,10,10,0.05)' }}
                    onMouseLeave={e => e.currentTarget.style.background='transparent'}
                  >
                    {/* Token icon with chain logo badge */}
                    <div style={{ position: 'relative', width: 36, height: 36, flexShrink: 0 }}>
                      <img
                        src={t.logoUrl} alt={t.symbol}
                        style={{ width: 36, height: 36, borderRadius: '50%', border: '1.5px solid rgba(10,10,10,0.1)' }}
                        onError={e => { e.currentTarget.style.display = 'none' }}
                      />
                      <div style={{
                        position: 'absolute', bottom: -3, right: -3,
                        width: 18, height: 18, borderRadius: '50%',
                        border: '2px solid #FFFFFF',
                        overflow: 'hidden', background: '#FFFFFF',
                      }}>
                        <ChainLogo chainId={t.chainId} size={18} />
                      </div>
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <span style={{ fontFamily: T.D, fontSize: 15, fontWeight: 700, color: T.text }}>
                          {t.symbol}
                        </span>
                        <span style={{
                          fontFamily: T.D, fontSize: 9, fontWeight: 700,
                          color: CHAIN_META[t.chainId]?.color ?? '#888',
                          background: `${CHAIN_META[t.chainId]?.color ?? '#888'}15`,
                          padding: '2px 6px', borderRadius: 4,
                        }}>
                          {CHAIN_META[t.chainId]?.name ?? `Chain ${t.chainId}`}
                        </span>
                      </div>
                      <div style={{ fontFamily: T.M, fontSize: 11, color: T.muted, marginTop: 2 }}>
                        {t.name}
                      </div>
                    </div>
                    {!available && (
                      <span style={{ fontFamily: T.D, fontSize: 9, color: T.muted }}>
                        Coming soon
                      </span>
                    )}
                  </button>
                )
              })}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Toast ──────────────────────────────────────────────────────────────────
function Toast({ message, color=T.amber, onDismiss }: { message:string; color?:string; onDismiss:()=>void }) {
  useEffect(() => { const t = setTimeout(onDismiss, 5000); return () => clearTimeout(t) }, [onDismiss])
  return (
    <div className="rp-toast" style={{ position:'fixed', bottom:24, left:'50%', zIndex:9999, minWidth:280, maxWidth:440, background:T.card, border:`1px solid ${color}30`, borderRadius:14, padding:'13px 18px', display:'flex', alignItems:'center', gap:10, boxShadow:`0 12px 40px rgba(0,0,0,0.8)` }}>
      <div style={{ width:8, height:8, borderRadius:'50%', background:color, boxShadow:`0 0 8px ${color}`, flexShrink:0 }} />
      <span style={{ fontFamily:T.D, fontSize:13, color:T.text, flex:1 }}>{message}</span>
      <button onClick={onDismiss} style={{ color:T.muted, background:'none', border:'none', cursor:'pointer', fontSize:16, padding:0 }}>✕</button>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════
export default function TransferForm({ noCard, externalToken }: { noCard?: boolean; externalToken?: TokenInfo | null }): React.JSX.Element {
  const { address, isConnected } = useAccount()
  const chainId                  = useChainId()
  const { switchChain }          = useSwitchChain()
  const publicClient             = usePublicClient()
  const { generateRecord }       = useComplianceEngine()
  const complianceApi            = useComplianceAPI()
  const sendBackend              = useBackendCallback()
  const { isLocked, acquireLock, releaseLock } = useTabLock()
  const { generateKey: generateIdempotencyKey, getKey: getIdempotencyKey } = useIdempotencyKey()
  const { clipboardAddress, dismiss: dismissClipboard } = useClipboardDetection()
  const isMobile = useIsMobile()
  const t = useTranslations('send')
  const locale = useLocale()

  useKeyboardShortcuts({
    onEscape: () => { if (showConfirmation) setShowConfirmation(false) },
    enabled: true,
  })

  // ── External token: direct ERC-20 transfer (bypasses FeeRouter) ─────
  const { prices: tokenPrices } = useTokenPrices()
  const { balance: extTokenBalance } = useTokenBalance(
    externalToken && !externalToken.isNative ? externalToken : null,
    address,
  )
  const [directERC20Mode, setDirectERC20Mode] = useState(false)
  const isExtERC20 = !!(externalToken && !externalToken.isNative && externalToken.address)

  // ── Registry ──────────────────────────────────────────────────────────
  const [registry,  setRegistry]  = useState<NetworkRegistry | null>(null)
  const [tokenList, setTokenList] = useState<(TokenConfig & { balance: bigint })[]>([])
  const [tokenIn,   setTokenIn]   = useState<(TokenConfig & { balance: bigint }) | null>(null)
  const [tokenOut,  setTokenOut]  = useState<(TokenConfig & { balance: bigint }) | null>(null)

  // ── Cross-chain state ──────────────────────────────────────────────────
  const [crossChainOut, setCrossChainOut] = useState<TokenInfo | null>(null)

  // Cross-chain (CCIP) feature flag — build-time constant inlined by Next.
  // Incomplete CCIP paths stay unreachable until contracts are wired + flag=true.
  const CROSSCHAIN_ENABLED = process.env.NEXT_PUBLIC_FEATURE_CROSSCHAIN === 'true'

  // ── isSwapMode — auto-detection (niente useState) ─────────────────────
  // Direct se stesso token (stesso address) — Swap se token diversi
  const isSwapMode = !!(tokenIn && tokenOut && tokenIn.address !== tokenOut.address) && !crossChainOut

  // ── Route detection ──────────────────────────────────────────────────
  const destChainId = crossChainOut?.chainId ?? chainId
  const isCrossChain = destChainId !== chainId

  const routeType: RouteType = (() => {
    if (!crossChainOut) {
      // Same-chain logic (existing)
      if (tokenIn && tokenOut && tokenIn.address !== tokenOut.address) return 'swap'
      return 'direct'
    }
    // Cross-chain logic
    const sameSymbol = tokenIn?.symbol === crossChainOut.symbol
    if (sameSymbol) return 'bridge'
    return 'swapAndBridge'
  })()

  const routeLabels: Record<RouteType, { label: string; icon: string; color: string }> = {
    direct:        { label: t('routeDirect'), icon: '\u2192', color: T.emerald },
    swap:          { label: t('routeSwap'), icon: '\u26A1', color: T.purple },
    bridge:        { label: t('routeBridge'), icon: '\u{1F309}', color: '#3B82F6' },
    swapAndBridge: { label: t('routeSwapAndBridge'), icon: '\u26A1\u{1F309}', color: T.amber },
  }

  // ── Token selector modal ───────────────────────────────────────────────
  const [selectingToken, setSelectingToken] = useState<SelectingToken>(null)

  // ── Form ───────────────────────────────────────────────────────────────
  const [amount,     setAmount]     = useState('')
  const [recipient,  setRecipient]  = useState('')
  const [focused,    setFocused]    = useState(false)
  const [addrError,  setAddrError]  = useState('')
  const [showExtras, setShowExtras] = useState(false)
  const [paymentRef, setPaymentRef] = useState('')
  const [fiscalRef,  setFiscalRef]  = useState('')
  const [copied,     setCopied]     = useState(false)
  const [toast,      setToast]      = useState<{ msg: string; color?: string } | null>(null)
  const [showConfirmation, setShowConfirmation] = useState(false)

  // ── Oracle ─────────────────────────────────────────────────────────────
  const [oracleData,     setOracleData]     = useState<OracleResponse | null>(null)
  const [oracleDenied,   setOracleDenied]   = useState(false)
  const [oracleChecking, setOracleChecking] = useState(false)
  const [needsApproval,  setNeedsApproval]  = useState(false)

  // ── TX ─────────────────────────────────────────────────────────────────
  const [phase,      setPhase]      = useState<Phase>('idle')
  const [approvHash, setApprovHash] = useState<`0x${string}` | undefined>()
  const [sendHash,   setSendHash]   = useState<`0x${string}` | undefined>()
  const [txError,    setTxError]    = useState('')
  const [report,     setReport]     = useState<{
    gross: bigint; net: bigint; fee: bigint
    decimals: number; symbol: string
    txHash: `0x${string}`; timestamp: string; eurValue?: string
  } | null>(null)
  const [compRec, setCompRec] = useState<ComplianceRecord | null>(null)

  const inputRef = useRef<HTMLInputElement>(null)
  const { writeContractAsync } = useWriteContract()
  const { sendTransactionAsync } = useSendTransaction()

  const clientIdRef = useRef<string | null>(null)
  const lastSubmittedHashRef = useRef<string | null>(null)
  const lastConfirmedHashRef = useRef<string | null>(null)

  // ── Quote engine — alimentato da isSwapMode ───────────────────────────
  const swapQuote = useSwapQuote({
    chainId,
    tokenIn:    isSwapMode ? tokenIn  : null,  // null in direct → nessuna call Uniswap
    tokenOut:   isSwapMode ? tokenOut : null,
    amountIn:   amount,
    debounceMs: 600,
  })

  const directQuote = useDirectQuote(amount, tokenIn?.decimals ?? 18)

  // ── Load registry quando cambia chainId ──────────────────────────────
  useEffect(() => {
    const reg = getRegistry(chainId)
    setRegistry(reg)
    if (!reg) return
    const list = Object.values(reg.tokens).map(t => ({ ...t as TokenConfig, balance: 0n as bigint }))
    setTokenList(list)
    const ethToken = list.find(t => t.isNative) ?? list[0]
    setTokenIn(ethToken ?? null)
    setTokenOut(ethToken ?? null)  // stesso token → isSwapMode=false (direct)
    setAmount('')
    setOracleData(null); setOracleDenied(false)
  }, [chainId])

  // ── Balances ──────────────────────────────────────────────────────────
  const { data: ethBal } = useBalance({ address })
  const erc20s = tokenList.filter(t => !t.isNative)
  const { data: erc20Bals } = useReadContracts({
    contracts: erc20s.map(t => ({
      address: t.address!, abi: erc20Abi,
      functionName: 'balanceOf' as const, args: [address!],
    })),
    query: { enabled: !!address && erc20s.length > 0 },
  })

  useEffect(() => {
    if (!registry) return
    const updated = tokenList.map(t => {
      if (t.isNative) return { ...t as TokenConfig, balance: ethBal?.value ?? 0n }
      const idx = erc20s.findIndex(e => e.symbol === t.symbol)
      const raw = erc20Bals?.[idx]?.result as bigint | undefined
      return { ...t as TokenConfig, balance: raw ?? 0n }
    })
    setTokenList(updated)
    setTokenIn((prev: (TokenConfig & { balance: bigint }) | null) =>
      prev ? (updated.find(t => t.symbol === prev.symbol) ?? updated[0]) : (updated[0] ?? null)
    )
    setTokenOut((prev: (TokenConfig & { balance: bigint }) | null) =>
      prev ? (updated.find(t => t.symbol === prev.symbol) ?? null) : null
    )
  }, [ethBal, erc20Bals])

  // ── Oracle preflight auto ─────────────────────────────────────────────
  useEffect(() => {
    const run = async () => {
      if (!address || !recipient || !amount || addrError || !isAddress(recipient) || !tokenIn) return
      // Skip Oracle preflight on chains without FeeRouter — no on-chain verification needed
      if (!isFeeRouterAvailable(chainId)) return
      const r = parseAmtIn(); if (!r) return
      setOracleChecking(true); setOracleData(null); setOracleDenied(false)
      try {
        const res = await fetch('/api/oracle/sign', {
          method: 'POST', headers: mutationHeaders(),
          body: JSON.stringify({
            sender: address,
            recipient,
            tokenIn:  tokenIn.isNative ? '0x0000000000000000000000000000000000000000' : tokenIn.address,
            tokenOut: isSwapMode && tokenOut
              ? tokenOut.address
              : (tokenIn.isNative ? '0x0000000000000000000000000000000000000000' : tokenIn.address),
            amountIn:    formatUnits(r, tokenIn.decimals),
            amountInWei: r.toString(),
            symbol:      tokenIn.symbol,
            chainId,
          }),
          signal: AbortSignal.timeout(8000),
        })
        if (res.ok) {
          const data: OracleResponse = await res.json()
          setOracleData(data); setOracleDenied(!data.approved)
          txLog('oracle.preflight', { approved: data.approved, isSwap: isSwapMode, sourceChain: data.sourceChain })
        }
      } catch { /* Oracle offline */ }
      finally { setOracleChecking(false) }
    }
    const t = setTimeout(run, 800)
    return () => clearTimeout(t)
  }, [recipient, amount, tokenIn?.symbol, tokenOut?.symbol, isSwapMode, address, chainId])

  const parseAmtIn = useCallback((): bigint | null => {
    if (!tokenIn || !amount || isNaN(Number(amount)) || Number(amount) <= 0) return null
    try { return tokenIn.isNative ? parseEther(amount) : parseUnits(amount, tokenIn.decimals) }
    catch { return null }
  }, [tokenIn, amount])

  // ── Receipts ──────────────────────────────────────────────────────────
  const { isSuccess: approveOk } = useWaitForTransactionReceipt({
    hash: approvHash, query: { enabled: !!approvHash && phase === 'wait_approve' },
  })
  const { isSuccess: sendOk } = useWaitForTransactionReceipt({
    hash: sendHash, query: { enabled: !!sendHash && phase === 'wait_send' },
  })

  // ── Server persistence: emit tx-submitted once per new sendHash ────────
  useEffect(() => {
    if (!sendHash || phase !== 'wait_send' || !address || !tokenIn) return
    if (lastSubmittedHashRef.current === sendHash) return
    lastSubmittedHashRef.current = sendHash

    const clientId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    clientIdRef.current = clientId

    const rawAmount = parseAmtIn()
    const outTokenSym = isSwapMode && tokenOut
      ? tokenOut.symbol
      : (crossChainOut ? crossChainOut.symbol : tokenIn.symbol)

    emitTxSubmitted({
      clientId,
      chain_id: chainId,
      tx_hash: sendHash,
      wallet_address: address,
      tx_type: isCrossChain ? 'bridge' : (isSwapMode ? 'swap' : 'transfer'),
      tx_status: 'confirming',
      direction: 'out',
      token_symbol: tokenIn.symbol,
      token_address: tokenIn.address ?? null,
      amount_raw: rawAmount ? rawAmount.toString() : null,
      amount_decimal: amount || null,
      counterparty_address: recipient && isAddress(recipient) ? recipient : null,
      extra_metadata: {
        isSwapMode,
        isCrossChain,
        destChainId,
        tokenOutSymbol: outTokenSym,
        tokenOutAddress: isSwapMode && tokenOut ? tokenOut.address ?? null : null,
        directERC20Mode,
      },
      submitted_at: new Date().toISOString(),
    })
  }, [sendHash, phase, address, chainId, tokenIn, tokenOut, crossChainOut, isSwapMode, isCrossChain, destChainId, directERC20Mode, recipient, amount, parseAmtIn])

  // ── Server persistence: emit tx-confirmed when phase resolves ──────────
  useEffect(() => {
    const clientId = clientIdRef.current
    if (!sendHash || !clientId) return
    if (lastConfirmedHashRef.current === sendHash) return
    const tx_status: 'confirmed' | 'failed' | null =
      phase === 'done' ? 'confirmed' : phase === 'error' ? 'failed' : null
    if (!tx_status) return
    lastConfirmedHashRef.current = sendHash
    emitTxConfirmed({
      clientId,
      tx_hash: sendHash,
      chain_id: chainId,
      tx_status,
      confirmed_at: new Date().toISOString(),
    })
  }, [phase, sendHash, chainId])

  const execSwap = useCallback(async (oracle: OracleResponse) => {
    const r = parseAmtIn(); if (!r || !tokenIn || !tokenOut || !registry) return
    if (!swapQuote || swapQuote.status !== 'success') {
      setTxError(t('quoteUnavailableDot')); setPhase('error'); return
    }
    const minOut = swapQuote.minAmountOut
    if (minOut === 0n) { setTxError('MEV Guard: slippage non configurato.'); setPhase('error'); return }
    setPhase('signing')
    try {
      // M1 slice B: V5/V6 take a threshold bytes[]; V4 a single bytes.
      const isV6 = registry.version === 'v6'
      const routerAbi = isV6 ? FEE_ROUTER_V6_ABI : FEE_ROUTER_ABI
      const oracleSigArg = isV6
        ? (oracle.oracleSignatures as `0x${string}`[])
        : (oracle.oracleSignature as `0x${string}`)
      const args = tokenIn.isNative
        ? [tokenOut.address!, minOut, getAddress(recipient) as `0x${string}`, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg]
        : [tokenIn.address!, tokenOut.address!, r, minOut, getAddress(recipient) as `0x${string}`, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg]
      logger.debug('TransferForm', 'execSwap args', { tokenIn: tokenIn.symbol, tokenOut: tokenOut?.symbol, isNative: tokenIn.isNative, chainId: String(chainId) })
      logger.debug('TransferForm', 'execSwap oracle', { deadline: String(oracle.oracleDeadline) })
      const hash = await writeContractAsync({
        address: registry.feeRouter, abi: routerAbi,
        functionName: tokenIn.isNative ? 'swapETHAndSend' : 'swapAndSend',
        args, ...(tokenIn.isNative ? { value: r } : {}),
      })
      txLog('swap.broadcast', { hash, tokenIn: tokenIn.symbol, tokenOut: tokenOut.symbol })
      setSendHash(hash); setPhase('wait_send')
    } catch (e) { handleErr(e) }
  }, [parseAmtIn, tokenIn, tokenOut, registry, swapQuote, recipient])

  // ── Direct swap via Uniswap V3 Router (no FeeRouter, no Oracle) ────────
  const execSwapDirect = useCallback(async () => {
    const r = parseAmtIn(); if (!r || !tokenIn || !tokenOut || !registry) return
    if (!swapQuote || swapQuote.status !== 'success') {
      setTxError(t('quoteUnavailableDot')); setPhase('error'); return
    }
    const minOut = swapQuote.minAmountOut
    if (minOut === 0n) { setTxError('MEV Guard: slippage non configurato.'); setPhase('error'); return }
    setPhase('signing')
    try {
      const weth = registry.weth
      const addrIn = tokenIn.isNative ? weth : tokenIn.address!
      const addrOut = tokenOut.isNative ? weth : tokenOut.address!
      const deadline = BigInt(Math.floor(Date.now() / 1000) + 1800) // 30 min

      logger.debug('TransferForm', 'execSwapDirect (no FeeRouter)', { tokenIn: tokenIn.symbol, tokenOut: tokenOut.symbol, poolFee: String(swapQuote.poolFee), chainId: String(chainId) })

      const hash = await writeContractAsync({
        address: registry.swapRouter as `0x${string}`,
        abi: UNISWAP_V3_ROUTER_ABI,
        functionName: 'exactInputSingle',
        args: [{
          tokenIn: addrIn,
          tokenOut: addrOut,
          fee: swapQuote.poolFee,
          recipient: getAddress(recipient) as `0x${string}`,
          deadline,
          amountIn: r,
          amountOutMinimum: minOut,
          sqrtPriceLimitX96: 0n,
        }],
        ...(tokenIn.isNative ? { value: r } : {}),
      })

      txLog('swap.broadcast', { hash, tokenIn: tokenIn.symbol, tokenOut: tokenOut.symbol, fallback: true })
      setSendHash(hash); setPhase('wait_send')
    } catch (e) { handleErr(e) }
  }, [parseAmtIn, tokenIn, tokenOut, registry, swapQuote, recipient, chainId])

  const execDirect = useCallback(async (oracle: OracleResponse) => {
    const r = parseAmtIn(); if (!r || !tokenIn || !registry) return
    setPhase('signing')
    try {
      let hash: `0x${string}`

      if (isFeeRouterAvailable(chainId)) {
        // ── FeeRouter path (Base, Base Sepolia) ─────────────────────
        logger.debug('TransferForm', 'execDirect FeeRouter path', { token: tokenIn.symbol, isNative: tokenIn.isNative, fn: tokenIn.isNative ? 'transferETHWithOracle' : 'transferWithOracle', chainId: String(chainId) })
        // M1 slice B: V5/V6 take a threshold bytes[]; V4 a single bytes.
        const isV6 = registry.version === 'v6'
        const routerAbi = isV6 ? FEE_ROUTER_V6_ABI : FEE_ROUTER_ABI
        const oracleSigArg = isV6
          ? (oracle.oracleSignatures as `0x${string}`[])
          : (oracle.oracleSignature as `0x${string}`)
        if (tokenIn.isNative) {
          logger.debug('TransferForm', 'transferETHWithOracle', { chainId: String(chainId), deadline: String(oracle.oracleDeadline) })
          hash = await writeContractAsync({
            address: registry.feeRouter, abi: routerAbi,
            functionName: 'transferETHWithOracle',
            args: [getAddress(recipient) as `0x${string}`, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg],
            value: r,
          })
        } else {
          hash = await writeContractAsync({
            address: registry.feeRouter, abi: routerAbi,
            functionName: 'transferWithOracle',
            args: [tokenIn.address!, r, getAddress(recipient) as `0x${string}`, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg],
          })
        }
      } else {
        // ── Direct transfer fallback (no FeeRouter on this chain) ───
        logger.debug('TransferForm', 'execDirect fallback (no FeeRouter)', { token: tokenIn.symbol, isNative: tokenIn.isNative, chainId: String(chainId) })
        if (tokenIn.isNative) {
          hash = await sendTransactionAsync({
            to: getAddress(recipient) as `0x${string}`,
            value: r,
          })
        } else {
          hash = await writeContractAsync({
            address: tokenIn.address! as `0x${string}`,
            abi: erc20Abi,
            functionName: 'transfer',
            args: [getAddress(recipient) as `0x${string}`, r],
          })
        }
      }

      txLog('direct.broadcast', { hash, token: tokenIn.symbol })
      setSendHash(hash); setPhase('wait_send')
    } catch (e) { handleErr(e) }
  }, [parseAmtIn, tokenIn, registry, recipient, chainId, sendTransactionAsync])

  // ── Cross-chain: bridge (same token, different chain) ─────────────────
  const execBridge = useCallback(async () => {
    const r = parseAmtIn(); if (!r || !tokenIn || !crossChainOut) return
    const ccipConfig = getCCIPConfig(chainId)
    const destSelector = getCCIPChainSelector(destChainId)
    if (!ccipConfig || !destSelector) {
      setTxError(t('crossChainUnavailable')); setPhase('error'); return
    }
    if (ccipConfig.senderContract === '0x0000000000000000000000000000000000000000') {
      setTxError('CCIP Sender non deployato. Aggiorna ccipRegistry.ts.'); setPhase('error'); return
    }
    setPhase('signing')
    try {
      // Estimate CCIP fee: ~0.001 ETH placeholder + 10% buffer
      const ccipFeeEst = parseEther('0.002')
      const hash = await writeContractAsync({
        address: ccipConfig.senderContract,
        abi: CCIP_SENDER_ABI,
        functionName: 'sendCrossChain',
        args: [destSelector, getAddress(recipient) as `0x${string}`, tokenIn.address!, r],
        value: ccipFeeEst,
      })
      txLog('bridge.broadcast', { hash, token: tokenIn.symbol, destChain: destChainId })
      setSendHash(hash); setPhase('wait_send')
    } catch (e) { handleErr(e) }
  }, [parseAmtIn, tokenIn, crossChainOut, chainId, destChainId, recipient])

  // ── Cross-chain: swap & bridge (different token, different chain) ──────
  const execSwapAndBridge = useCallback(async () => {
    const r = parseAmtIn(); if (!r || !tokenIn || !crossChainOut) return
    const ccipConfig = getCCIPConfig(chainId)
    const destSelector = getCCIPChainSelector(destChainId)
    if (!ccipConfig || !destSelector) {
      setTxError(t('crossChainUnavailable')); setPhase('error'); return
    }
    if (ccipConfig.senderContract === '0x0000000000000000000000000000000000000000') {
      setTxError('CCIP Sender non deployato. Aggiorna ccipRegistry.ts.'); setPhase('error'); return
    }
    if (!swapQuote || swapQuote.status !== 'success') {
      setTxError(t('quoteUnavailableDot')); setPhase('error'); return
    }
    setPhase('signing')
    try {
      const minOut = swapQuote.minAmountOut
      const ccipFeeEst = parseEther('0.002')

      // Resolve the tokenOut address on the source chain for the swap
      // The swap happens on source chain, then the output token is bridged
      const tokenOutAddr = crossChainOut.address as `0x${string}` | null
      if (!tokenOutAddr) {
        setTxError(t('tokenOutUnavailable')); setPhase('error'); return
      }

      if (tokenIn.isNative) {
        // swapETHAndBridge: msg.value = amountIn + ccipFee
        const hash = await writeContractAsync({
          address: ccipConfig.senderContract,
          abi: CCIP_SENDER_ABI,
          functionName: 'swapETHAndBridge',
          args: [tokenOutAddr, r, minOut, destSelector, getAddress(recipient) as `0x${string}`],
          value: r + ccipFeeEst,
        })
        txLog('swapAndBridge.broadcast', { hash, tokenIn: tokenIn.symbol, tokenOut: crossChainOut.symbol, destChain: destChainId })
        setSendHash(hash); setPhase('wait_send')
      } else {
        // swapAndBridge: msg.value = ccipFee only
        const hash = await writeContractAsync({
          address: ccipConfig.senderContract,
          abi: CCIP_SENDER_ABI,
          functionName: 'swapAndBridge',
          args: [tokenIn.address!, tokenOutAddr, r, minOut, destSelector, getAddress(recipient) as `0x${string}`],
          value: ccipFeeEst,
        })
        txLog('swapAndBridge.broadcast', { hash, tokenIn: tokenIn.symbol, tokenOut: crossChainOut.symbol, destChain: destChainId })
        setSendHash(hash); setPhase('wait_send')
      }
    } catch (e) { handleErr(e) }
  }, [parseAmtIn, tokenIn, crossChainOut, chainId, destChainId, swapQuote, recipient])

  useEffect(() => {
    if (!approveOk || phase !== 'wait_approve') return
    // Cross-chain routes
    if (CROSSCHAIN_ENABLED && isCrossChain && crossChainOut) {
      if (routeType === 'bridge') execBridge()
      else execSwapAndBridge()
      return
    }
    // FeeRouter path: Oracle available → use execSwap/execDirect with Oracle
    if (oracleData) {
      if (isSwapMode) execSwap(oracleData)
      else execDirect(oracleData)
    } else if (isSwapMode) {
      // Direct swap fallback (no FeeRouter, no Oracle) → use Uniswap directly
      execSwapDirect()
    }
  }, [approveOk, phase, oracleData, isSwapMode, isCrossChain, crossChainOut, routeType, execSwap, execDirect, execSwapDirect, execBridge, execSwapAndBridge])

  useEffect(() => {
    if (!sendOk || phase !== 'wait_send' || !sendHash || !tokenIn || !address || directERC20Mode) return
    const r = parseAmtIn(); if (!r) return
    const outToken  = isSwapMode && tokenOut ? tokenOut : tokenIn
    const grossOut  = isSwapMode && swapQuote?.status === 'success' ? swapQuote.amountOut : r
    const feeOut    = (grossOut * 50n) / 10_000n
    const netOut    = grossOut - feeOut
    const eurRate   = EUR_RATES[outToken.symbol] ?? 1
    const eurVal    = outToken.isEurc
      ? parseFloat(formatUnits(netOut, outToken.decimals)).toFixed(2) + ' EUR'
      : (parseFloat(formatUnits(netOut, outToken.decimals)) * eurRate).toFixed(2) + ' EUR'
    setReport({ gross: grossOut, net: netOut, fee: feeOut, decimals: outToken.decimals, symbol: outToken.symbol, txHash: sendHash, timestamp: new Date().toISOString(), eurValue: eurVal })
    generateRecord({
      txHash: sendHash, sender: address, recipient,
      gross: grossOut, net: netOut, fee: feeOut,
      decimals: outToken.decimals, symbol: outToken.symbol,
      paymentRef: oracleData?.paymentRef || '—',
      fiscalRef:  oracleData?.fiscalRef  || '—',
      chainId, isTestnet: chainId === baseSepolia.id,
    }).then(async rec => {
      setCompRec(rec)
      const api = await complianceApi.submitAfterFinality(rec, 2500)
      if (api.queued) setTimeout(() => setToast({ msg: t('complianceInQueue'), color: T.amber }), 3000)

      // ── Invia al backend RPagos ─────────────────────────────
      sendBackend({
        txHash:    sendHash,
        grossStr:  formatUnits(grossOut, outToken.decimals),
        netStr:    formatUnits(netOut, outToken.decimals),
        feeStr:    formatUnits(feeOut, outToken.decimals),
        symbol:    outToken.symbol,
        recipient,
        paymentRef: oracleData?.paymentRef,
        fiscalRef:  oracleData?.fiscalRef,
        eurValue:   eurVal,
        timestamp:  new Date().toISOString(),
        isTestnet:  chainId === baseSepolia.id,
        complianceRecord: rec ? {
          compliance_id:    rec.compliance_id,
          block_timestamp:  rec.block_timestamp,
          fiat_rate:        rec.fiat_rate ?? undefined,
          asset:            rec.asset,
          fiat_gross:       rec.fiat_gross ? parseFloat(rec.fiat_gross) : undefined,
          ip_jurisdiction:  rec.ip_jurisdiction,
          mica_applicable:  rec.mica_applicable,
          fiscal_ref:       rec.fiscal_ref,
          network:          rec.network,
        } : undefined,
      }).catch(err => console.warn('[RPagos Backend] callback error:', err))
    })
    txLog('tx.completed', { hash: sendHash, isSwap: isSwapMode, tokenIn: tokenIn.symbol, tokenOut: outToken.symbol })
    if (recipient && isAddress(recipient)) recordSuccessfulTx(recipient)
    releaseLock()
    setPhase('done')
  }, [sendOk, phase])

  // ── Receipt handler: direct ERC-20 transfer ────────────────────────────
  useEffect(() => {
    if (!sendOk || phase !== 'wait_send' || !sendHash || !directERC20Mode || !externalToken || !address) return
    const amountWei = parseUnits(amount, externalToken.decimals)
    const fee = (amountWei * 50n) / 10_000n
    const net = amountWei - fee
    const eurRate = tokenPrices[externalToken.coingeckoId]?.eur ?? 0
    const eurVal = eurRate > 0
      ? (parseFloat(formatUnits(net, externalToken.decimals)) * eurRate).toFixed(2) + ' EUR'
      : undefined
    setReport({
      gross: amountWei, net, fee,
      decimals: externalToken.decimals, symbol: externalToken.symbol,
      txHash: sendHash, timestamp: new Date().toISOString(),
      eurValue: eurVal,
    })
    txLog('direct_erc20.completed', { hash: sendHash, token: externalToken.symbol })
    if (recipient && isAddress(recipient)) recordSuccessfulTx(recipient)
    releaseLock()
    setDirectERC20Mode(false)
    setPhase('done')
  }, [sendOk, phase, directERC20Mode])

  function handleErr(e: unknown) {
    releaseLock()
    const m    = e instanceof Error ? e.message : String(e)
    const code = (e as { code?: number })?.code
    if (code === 4001 || m.includes('rejected') || m.includes('denied') || m.includes('cancel')) {
      setToast({ msg: t('transactionCancelled'), color: T.amber }); setPhase('idle')
    } else if (m.includes('OracleSignatureInvalid')){ setTxError(t('oracleSignatureInvalid')); setPhase('error') }
    else if (m.includes('DeadlineExpired'))       { setTxError(t('deadlineExpired')); setPhase('error') }
    else if (m.includes('NonceAlreadyUsed'))      { setTxError(t('nonceAlreadyUsed')); setPhase('error') }
    else if (m.includes('MEVGuard'))              { setTxError('MEV Guard: slippage non configurato.'); setPhase('error') }
    else if (m.includes('InsufficientLiquidity')) { setTxError(t('insufficientLiquidity')); setPhase('error') }
    else if (m.includes('SlippageExceeded'))      { setTxError(t('slippageExceeded')); setPhase('error') }
    // ── ERC-20 specific errors ─────────────────────────────────────────
    else if (m.includes('insufficient') && m.includes('balance'))
      { setTxError(t('error', { message: m.slice(0, 200) })); setPhase('error') }
    else if (m.includes('insufficient') && m.includes('allowance'))
      { setTxError(t('error', { message: m.slice(0, 200) })); setPhase('error') }
    else if (m.includes('blacklisted') || m.includes('Blacklistable'))
      { setTxError(t('error', { message: m.slice(0, 200) })); setPhase('error') }
    else if (m.includes('transfer amount exceeds balance'))
      { setTxError(t('error', { message: m.slice(0, 200) })); setPhase('error') }
    else                                          { setTxError(t('error', { message: m.slice(0, 200) })); setPhase('error') }
  }

  const handleTransfer = async () => {
    // ── Direct ERC-20 transfer (no FeeRouter, no Oracle) ─────────────────
    if (isExtERC20 && externalToken?.address) {
      if (!amount || isNaN(Number(amount)) || Number(amount) <= 0) return
      if (!validateAddr(recipient)) return
      if (isLocked) { setToast({ msg: t('transactionInProgress'), color: T.amber }); return }
      acquireLock()

      const amountWei = parseUnits(amount, externalToken.decimals)
      const fee = (amountWei * 50n) / 10_000n
      const netAmount = amountWei - fee

      // Balance guard
      if (extTokenBalance < amountWei) {
        setToast({ msg: t('error', { message: `${externalToken.symbol} insufficient balance` }), color: T.red })
        releaseLock(); return
      }

      setDirectERC20Mode(true)
      setPhase('signing')
      txLog('direct_erc20.initiated', { token: externalToken.symbol, amount, chain: chainId })
      try {
        const hash = await writeContractAsync({
          address: externalToken.address as `0x${string}`,
          abi: erc20Abi,
          functionName: 'transfer',
          args: [getAddress(recipient) as `0x${string}`, netAmount],
        })
        txLog('direct_erc20.broadcast', { hash, token: externalToken.symbol, net: formatUnits(netAmount, externalToken.decimals) })
        setSendHash(hash)
        setPhase('wait_send')
      } catch (e) {
        setDirectERC20Mode(false)
        handleErr(e)
      }
      return
    }

    const r = parseAmtIn(); if (!r || !tokenIn || !validateAddr(recipient) || !registry) return

    // ── GUARD: tab lock — TX in corso su altra scheda ─────────────────────
    if (isLocked) {
      setToast({ msg: t('transactionInProgress'), color: T.amber })
      return
    }
    acquireLock()
    const txIdempotencyKey = generateIdempotencyKey()

    // ── Cross-chain routes: bridge or swapAndBridge ─────────────────────
    if (CROSSCHAIN_ENABLED && isCrossChain && crossChainOut) {
      // AML check for cross-chain
      try {
        const checkRes = await fetch('/api/oracle/check-crosschain', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sender: address, recipient,
            token: crossChainOut.symbol, amount,
            sourceChainId: chainId, destChainId,
          }),
        })
        const checkData = await checkRes.json()
        if (!checkData.approved) {
          setTxError(t('transactionBlocked'))
          setPhase('error'); releaseLock(); return
        }
      } catch {
        // AML check fail → proceed (fail-open for frontend, backend enforces)
      }

      if (routeType === 'bridge') {
        // Same token, different chain → approve + sendCrossChain
        if (!tokenIn.isNative) {
          const ccipConfig = getCCIPConfig(chainId)
          if (ccipConfig && ccipConfig.senderContract !== '0x0000000000000000000000000000000000000000') {
            try {
              setPhase('approving')
              const ah = await writeContractAsync({
                address: tokenIn.address! as `0x${string}`, abi: erc20Abi,
                functionName: 'approve',
                args: [ccipConfig.senderContract, r],
              })
              setApprovHash(ah); setPhase('wait_approve')
              // execBridge called after approve via effect below
            } catch (e) { handleErr(e) }
          } else {
            await execBridge()
          }
        } else {
          await execBridge()
        }
      } else {
        // swapAndBridge → approve tokenIn + call swapAndBridge
        if (!tokenIn.isNative) {
          const ccipConfig = getCCIPConfig(chainId)
          if (ccipConfig && ccipConfig.senderContract !== '0x0000000000000000000000000000000000000000') {
            try {
              setPhase('approving')
              const ah = await writeContractAsync({
                address: tokenIn.address! as `0x${string}`, abi: erc20Abi,
                functionName: 'approve',
                args: [ccipConfig.senderContract, r],
              })
              setApprovHash(ah); setPhase('wait_approve')
            } catch (e) { handleErr(e) }
          } else {
            await execSwapAndBridge()
          }
        } else {
          await execSwapAndBridge()
        }
      }
      return
    }

    // ── GUARD: contratto non deployato su questa chain ─────────────────────
    const ZERO_ADDR = '0x0000000000000000000000000000000000000000'
    const hasFeeRouter = isFeeRouterAvailable(chainId)

    if (!tokenIn.isNative) {
      const tokenChains = findChainForToken(tokenIn.symbol)
      if (!tokenChains.includes(chainId)) {
        const targetChain = tokenChains[0]
        if (targetChain) {
          setToast({ msg: t('networkUnavailable', { chain: tokenIn.symbol }), color: T.amber })
          switchChain({ chainId: targetChain as 1 | 8453 | 84532 | 11155111 })
          releaseLock()
          return
        }
      }
    }

    // ── Fallback path: no FeeRouter on this chain ─────────────────────────
    if (!hasFeeRouter) {
      if (isSwapMode) {
        // ── Direct swap via Uniswap V3 Router (no Oracle, no fee) ───────
        txLog('tx.initiated', { isSwap: true, token: tokenIn.symbol, chain: chainId, fallback: true })
        try {
          if (!tokenIn.isNative) {
            setPhase('approving')
            const ah = await writeContractAsync({
              address: tokenIn.address! as `0x${string}`,
              abi: erc20Abi,
              functionName: 'approve',
              args: [registry.swapRouter as `0x${string}`, r],
            })
            setApprovHash(ah); setPhase('wait_approve')
            // execSwapDirect will be called after approve confirms (via useEffect)
          } else {
            await execSwapDirect()
          }
        } catch (e) { handleErr(e) }
      } else {
        // ── Direct transfer (no Oracle, no fee) ────────────────────────
        txLog('tx.initiated', { isSwap: false, token: tokenIn.symbol, chain: chainId, fallback: true })
        setPhase('signing')
        try {
          let hash: `0x${string}`
          if (tokenIn.isNative) {
            hash = await sendTransactionAsync({
              to: getAddress(recipient) as `0x${string}`,
              value: r,
            })
          } else {
            hash = await writeContractAsync({
              address: tokenIn.address! as `0x${string}`,
              abi: erc20Abi,
              functionName: 'transfer',
              args: [getAddress(recipient) as `0x${string}`, r],
            })
          }
          txLog('direct.broadcast', { hash, token: tokenIn.symbol, fallback: true })
          setSendHash(hash); setPhase('wait_send')

          // ── Compliance callback (best-effort) ──────────────────
          try {
            sendBackend({
              txHash:    hash,
              grossStr:  amount,
              netStr:    amount,
              feeStr:    '0',
              symbol:    tokenIn.symbol,
              recipient,
              fiscalRef: `RP-${Date.now()}`,
              timestamp: new Date().toISOString(),
              isTestnet: chainId === baseSepolia.id,
            })
          } catch { /* best-effort */ }
        } catch (e) { handleErr(e) }
      }
      return
    }

    // ── FeeRouter path (oracle + on-chain) ─────────────────────────────────
    if (!registry.feeRouter || registry.feeRouter === ZERO_ADDR) {
      setToast({
        msg: `⚠ Contratto non configurato su ${registry.chainName}. Passa a Base Sepolia o aggiungi NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA su Vercel.`,
        color: T.red,
      })
      releaseLock()
      return
    }
    let oracle = oracleData
    if (!oracle || !oracle.approved) {
      setPhase('preflight')
      try {
        const res = await fetch('/api/oracle/sign', {
          method: 'POST', headers: mutationHeaders(),
          body: JSON.stringify({
            sender: address,
            recipient,
            tokenIn:  tokenIn.isNative ? '0x0000000000000000000000000000000000000000' : tokenIn.address,
            tokenOut: isSwapMode && tokenOut
              ? tokenOut.address
              : (tokenIn.isNative ? '0x0000000000000000000000000000000000000000' : tokenIn.address),
            amountIn:    formatUnits(r, tokenIn.decimals),
            amountInWei: r.toString(),   // wei esatti — evita errori di arrotondamento
            symbol:      tokenIn.symbol,
            chainId,
          }),
          signal: AbortSignal.timeout(10_000),
        })
        oracle = await res.json()
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[TransferForm] Oracle fetch failed:', msg, err)
        setTxError(`Oracle non raggiungibile: ${msg}`)
        setPhase('error')
        releaseLock()
        return
      }
    }
    if (!oracle?.approved) { setOracleDenied(true); setOracleData(oracle); setPhase('idle'); releaseLock(); return }
    txLog('tx.initiated', { isSwap: isSwapMode, token: tokenIn.symbol, chain: chainId })
    try {
      if (isSwapMode) {
        if (!tokenIn.isNative) {
          setPhase('approving')
          const ah = await writeContractAsync({ address: tokenIn.address!, abi: erc20Abi, functionName: 'approve', args: [registry.feeRouter, r] })
          setApprovHash(ah); setPhase('wait_approve')
        } else { await execSwap(oracle) }
      } else {
        if (!tokenIn.isNative) {
          setPhase('approving')
          const ah = await writeContractAsync({ address: tokenIn.address!, abi: erc20Abi, functionName: 'approve', args: [registry.feeRouter, r] })
          setApprovHash(ah); setPhase('wait_approve')
        } else { await execDirect(oracle) }
      }
    } catch (e) { handleErr(e) }
  }

  const reset = () => {
    setPhase('idle'); setAmount(''); setRecipient(''); setPaymentRef(''); setFiscalRef('')
    setReport(null); setCompRec(null); setApprovHash(undefined); setSendHash(undefined)
    setTxError(''); setOracleData(null); setOracleDenied(false); setDirectERC20Mode(false)
    setCrossChainOut(null)
  }

  const handlePdf = async () => {
    if (!report || !address) return

    // Fetch tasso di cambio reale
    let exchangeRate: PdfReceiptParams['exchangeRate'] = undefined
    if (report.symbol !== 'EURC') {
      try {
        const cgIds: Record<string, string> = {
          'ETH': 'ethereum', 'WETH': 'ethereum', 'USDC': 'usd-coin',
          'USDT': 'tether', 'DAI': 'dai', 'WBTC': 'bitcoin',
          'cbBTC': 'bitcoin', 'BNB': 'binancecoin', 'AVAX': 'avalanche-2',
          'MATIC': 'matic-network', 'POL': 'matic-network',
        }
        const cgId = cgIds[report.symbol.toUpperCase()]
        if (cgId) {
          const res = await fetch(
            `/api/market/simple/price?ids=${cgId}&vs_currencies=eur`,
            { signal: AbortSignal.timeout(5000) }
          )
          const data = await res.json()
          const rate = data[cgId]?.eur
          if (rate) {
            exchangeRate = {
              tokenSymbol: report.symbol,
              fiatCurrency: 'EUR',
              rate,
              source: 'CoinGecko API (coingecko.com)',
              fetchedAt: new Date().toISOString(),
            }
          }
        }
      } catch {
        // Se CoinGecko fallisce, il PDF mostrerà "stima non verificata"
      }
    }

    const registry = getRegistry(chainId)
    const chainName = registry?.chainName ?? 'Base'

    await generatePdfReceipt({
      txHash: report.txHash, timestamp: report.timestamp, sender: address, recipient,
      grossAmount: formatUnits(report.gross, report.decimals),
      netAmount:   formatUnits(report.net,   report.decimals),
      feeAmount:   formatUnits(report.fee,   report.decimals),
      symbol: report.symbol, paymentRef: oracleData?.paymentRef || '—',
      fiscalRef: oracleData?.fiscalRef || '—', eurValue: report.eurValue,
      network: chainName,

      // Campi fiscali
      emittente: {
        legalName: process.env.NEXT_PUBLIC_COMPANY_NAME || 'RSends S.r.l.',
        vatNumber: process.env.NEXT_PUBLIC_COMPANY_VAT || 'IT______________',
        registeredOffice: process.env.NEXT_PUBLIC_COMPANY_ADDRESS || '(sede da configurare)',
        pec: process.env.NEXT_PUBLIC_COMPANY_PEC || '',
      },
      exchangeRate,
    })
  }

  const fmtBal = (t: TokenConfig & { balance: bigint }) => {
    const v = parseFloat(formatUnits(t.balance, t.decimals))
    return ['USDC','USDT','EURC'].includes(t.symbol) ? v.toFixed(2)
      : t.symbol === 'cbBTC' || t.symbol === 'WBTC' ? v.toFixed(6)
      : v.toFixed(4)
  }
  const validateAddr = (addr: string) => {
    if (!addr) { setAddrError(''); return false }
    if (!isAddress(addr)) { setAddrError(t('invalidAddress')); return false }
    setAddrError(''); return true
  }
  const handleMax = async () => {
    if (!tokenIn) return
    if (tokenIn.isNative) {
      try {
        const gp   = await publicClient?.getGasPrice() ?? 1_500_000_000n
        const cost = (21_000n * gp * 12n) / 10n
        setAmount(formatEther(tokenIn.balance > cost ? tokenIn.balance - cost : 0n))
      } catch { setAmount(formatEther(tokenIn.balance)) }
    } else { setAmount(formatUnits(tokenIn.balance, tokenIn.decimals)) }
    setTimeout(() => inputRef.current?.focus(), 10)
  }
  const setAmountPercent = async (pct: 25 | 50 | 100) => {
    if (!tokenIn) return
    if (pct === 100) { await handleMax(); return }
    const raw = (tokenIn.balance * BigInt(pct)) / 100n
    setAmount(tokenIn.isNative ? formatEther(raw) : formatUnits(raw, tokenIn.decimals))
    setTimeout(() => inputRef.current?.focus(), 10)
  }
  // ── Valori derivati ────────────────────────────────────────────────────
  const rawIn    = parseAmtIn()
  const busy     = ['preflight','approving','wait_approve','signing','wait_send'].includes(phase)
  const sym      = tokenIn?.symbol  ?? 'ETH'
  const symOut   = crossChainOut ? crossChainOut.symbol : (isSwapMode ? (tokenOut?.symbol ?? 'USDC') : sym)
  const displaySym = isExtERC20 ? externalToken!.symbol : sym
  const isWrong  = isConnected && !([8453, 1, 42161, 10, 137, 56, 43114, 324, 42220, 81457, 84532, 11155111] as number[]).includes(chainId as number)
  const hasInsuf = isConnected && !!rawIn && !!tokenIn && rawIn > tokenIn.balance
  // Balance check for external ERC-20 token
  const extAmtWei = isExtERC20 && amount ? (() => { try { return parseUnits(amount, externalToken!.decimals) } catch { return null } })() : null
  const hasInsufExt = isConnected && isExtERC20 && !!extAmtWei && extAmtWei > extTokenBalance
  const noLiq    = isSwapMode && swapQuote?.status === 'error_liquidity'
  const isL2     = chainId === 8453 || chainId === 84532
  const regChain = getRegistry(chainId)
  const feeRouterAvailable = isFeeRouterAvailable(chainId)
  const noContract = isConnected && !isWrong && regChain?.feeRouter === '0x0000000000000000000000000000000000000000'

  const ctaState: CtaState = !isConnected   ? 'disconnected'
    : isWrong                               ? 'wrong_network'
    : busy                                  ? 'busy'
    : (hasInsuf || hasInsufExt)             ? 'insufficient'
    : (isExtERC20 || !feeRouterAvailable ? false : oracleDenied) ? 'oracle_denied'
    : noLiq                                 ? 'no_liquidity'
    : !recipient || !!addrError             ? 'no_recipient'
    : (isExtERC20 ? !extAmtWei : !rawIn)    ? 'no_amount'
    :                                         'ready'

  const C = {
    card:  { borderRadius:20, background:'rgba(8,12,30,0.72)', border:'1px solid rgba(10,10,10,0.18)', overflow:'hidden' as const, boxShadow:'0 8px 48px rgba(0,0,0,0.55), inset 0 1px 0 rgba(10,10,10,0.15)' } satisfies React.CSSProperties,
    box:   { borderRadius:14, background:focused?'rgba(10,10,10,0.08)':'rgba(10,10,10,0.04)', padding:'10px 14px', border:'1.5px solid', borderColor:focused?`${T.emerald}60`:'rgba(10,10,10,0.14)', transition:'all 0.2s ease', cursor:'text', boxShadow:focused?`0 0 0 3px ${T.emerald}12`:'inset 0 1px 0 rgba(10,10,10,0.08)' } satisfies React.CSSProperties,
    box2:  { borderRadius:14, background:'rgba(10,10,10,0.04)', padding:'10px 14px', border:'1.5px solid rgba(10,10,10,0.12)' } satisfies React.CSSProperties,
    row:   { display:'flex', alignItems:'center', justifyContent:'space-between' } satisfies React.CSSProperties,
    input: { width:'100%', background:'rgba(10,10,10,0.08)', border:'1px solid rgba(10,10,10,0.12)', borderRadius:10, padding:'10px 12px', color:T.text, fontSize:13, outline:'none', transition:'border-color 0.2s ease, box-shadow 0.2s ease', fontFamily:T.M, boxSizing:'border-box' as const, backdropFilter:'blur(8px)', WebkitBackdropFilter:'blur(8px)' } satisfies React.CSSProperties,
  }

  // ── SUCCESS ───────────────────────────────────────────────────────────
  if (phase === 'done' && report) return (
    <>
      <div style={noCard ? {} : C.card} className={`rp-anim-0${noCard ? '' : ' bf-blur-32s'}`}>
        <div style={{ padding:'18px 20px 16px', borderBottom:`1px solid ${T.border}`, display:'flex', alignItems:'center', gap:10 }}>
          <div style={{ width:9, height:9, borderRadius:'50%', background:T.emerald, boxShadow:`0 0 12px ${T.emerald}` }} />
          <span style={{ fontFamily:T.D, color:T.emerald, fontSize:13, fontWeight:700, textTransform:'uppercase' as const, letterSpacing:'0.06em' }}>{t('paymentConfirmed')}</span>
          {oracleData?.isSwap && (
            <span style={{ fontFamily:T.D, fontSize:10, color:T.purple, background:`${T.purple}15`, padding:'2px 7px', borderRadius:5, border:`1px solid ${T.purple}30` }}>
              ⚡ Swap V3
            </span>
          )}
          <span style={{ fontFamily:T.M, fontSize:11, color:T.muted, marginLeft:'auto' }}>
            {new Date(report.timestamp).toLocaleString(locale)}
          </span>
        </div>
        <div style={{ padding:'20px' }}>
          <TransactionStatusUI
            phase="done" txHash={report.txHash} isTestnet={chainId === baseSepolia.id}
            grossStr={formatUnits(report.gross, report.decimals)}
            netStr={formatUnits(report.net, report.decimals)}
            feeStr={formatUnits(report.fee, report.decimals)}
            symbol={report.symbol} recipient={recipient}
            paymentRef={oracleData?.paymentRef || '—'}
            fiscalRef={oracleData?.fiscalRef || '—'}
            eurValue={report.eurValue} timestamp={report.timestamp}
            complianceRecord={compRec ?? undefined}
            onCopyHash={async () => { await navigator.clipboard.writeText(report.txHash); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
            copied={copied} onReset={reset} onDownloadPdf={handlePdf}
          />
        </div>
      </div>
      {toast && <Toast message={toast.msg} color={toast.color} onDismiss={() => setToast(null)} />}
    </>
  )

  // ── MAIN FORM — Jupiter-style: no header, direct Sell/Buy ──────────
  return (
    <>
      <div style={noCard ? {} : C.card} className={noCard ? 'max-w-[440px] mx-auto w-full' : 'bf-blur-32s'}>
        <div className="rp-stagger-host">

          {/* ── Card Pay ─────────────────────────────────────── */}
          <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">Pay</span>
              {isConnected && tokenIn && (
                <button
                  type="button"
                  onClick={e => { e.stopPropagation(); handleMax() }}
                  className="text-[11px] text-[#888780] font-mono hover:text-[#2C2C2A] transition-colors bg-transparent border-none cursor-pointer p-0"
                >
                  Balance {fmtBal(tokenIn)} {sym}
                </button>
              )}
            </div>

            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectingToken('in')}
                disabled={busy}
                className="flex items-center gap-2 pl-1.5 pr-2.5 py-1.5 rounded-full border border-[rgba(200,81,44,0.2)] bg-[#FAFAF7] text-[#2C2C2A] shrink-0 hover:bg-[#F5F2ED] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <img
                  src={tokenIn?.logoURI ?? '/tokens/eth.svg'}
                  alt={tokenIn?.symbol ?? 'ETH'}
                  width={22}
                  height={22}
                  className="w-[22px] h-[22px] rounded-full"
                />
                <span className="text-sm font-medium">{tokenIn?.symbol ?? 'ETH'}</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="opacity-50">
                  <path d="M2.5 4L5 6.5L7.5 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>

              <input
                ref={inputRef}
                type="number"
                inputMode="decimal"
                placeholder="0.0"
                min="0"
                step="any"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                value={amount}
                onChange={e => setAmount(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                disabled={busy}
                className="flex-1 min-w-0 bg-transparent outline-none border-none text-right text-[#2C2C2A] text-[32px] font-medium tabular-nums tracking-[-0.02em] placeholder:text-[#888780]"
              />
            </div>

            <div className="flex items-center justify-between mt-2.5">
              <div className="flex gap-1.5">
                {([25, 50, 100] as const).map(pct => (
                  <button
                    key={pct}
                    type="button"
                    onClick={() => setAmountPercent(pct)}
                    disabled={busy || !tokenIn || tokenIn.balance === 0n}
                    className={[
                      'px-2.5 py-1 text-[10px] font-medium rounded-md transition-colors',
                      pct === 100
                        ? 'bg-[rgba(200,81,44,0.12)] border border-[rgba(200,81,44,0.3)] text-[#C8512C] hover:bg-[rgba(200,81,44,0.18)]'
                        : 'bg-[rgba(200,81,44,0.08)] border border-[rgba(200,81,44,0.2)] text-[#C8512C] hover:bg-[rgba(200,81,44,0.14)]',
                      'disabled:opacity-40 disabled:cursor-not-allowed',
                    ].join(' ')}
                  >
                    {pct === 100 ? 'MAX' : `${pct}%`}
                  </button>
                ))}
              </div>
              <span className="text-[12px] text-[#888780] font-mono">
                {amount && tokenIn
                  ? `$${(parseFloat(amount) * (EUR_RATES[tokenIn.symbol] ?? 1)).toFixed(2)}`
                  : '$0.00'}
              </span>
            </div>
          </div>

          {/* ── Divider (flip tokens) ───────────────────────── */}
          <div className="relative z-[2] flex justify-center -my-2.5">
            <button
              type="button"
              aria-label="Flip tokens"
              onClick={() => {
                if (!tokenIn || !tokenOut) return
                const tmp = tokenIn
                setTokenIn(tokenOut)
                setTokenOut(tmp)
                setAmount('')
              }}
              disabled={busy || !tokenIn || !tokenOut}
              className="w-9 h-9 rounded-[10px] bg-white border border-[rgba(200,81,44,0.35)] text-[#C8512C] flex items-center justify-center hover:bg-[#FAFAF7] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M4 2v10M4 12l-2-2M4 12l2-2M10 12V2M10 2l-2 2M10 2l2 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>

          {/* ── Card Receive ─────────────────────────────────── */}
          <div className="mt-2 rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">Receive</span>
              <span className="text-[11px] text-[#888780] font-mono">
                {isSwapMode ? 'Recipient receives' : 'Direct send'}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectingToken('out')}
                disabled={busy}
                className="flex items-center gap-2 pl-1.5 pr-2.5 py-1.5 rounded-full border border-[rgba(200,81,44,0.2)] bg-[#FAFAF7] text-[#2C2C2A] shrink-0 hover:bg-[#F5F2ED] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <img
                  src={tokenOut?.logoURI ?? '/tokens/eth.svg'}
                  alt={tokenOut?.symbol ?? 'ETH'}
                  width={22}
                  height={22}
                  className="w-[22px] h-[22px] rounded-full"
                />
                <span className="text-sm font-medium">{tokenOut?.symbol ?? tokenIn?.symbol ?? 'ETH'}</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="opacity-50">
                  <path d="M2.5 4L5 6.5L7.5 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
              <span className="flex-1 min-w-0 text-right text-[#2C2C2A] text-[32px] font-medium tabular-nums tracking-[-0.02em]">
                {isSwapMode
                  ? (swapQuote?.status === 'success' ? swapQuote.netAmountFmt
                     : swapQuote?.status === 'loading' ? '…' : '0')
                  : (directQuote ? directQuote.netFmt : '0')}
              </span>
            </div>
            <div className="flex items-center justify-end mt-2.5">
              <span className="text-[12px] text-[#888780] font-mono">
                {isSwapMode
                  ? (swapQuote?.status === 'success' ? `≈ $${(parseFloat(swapQuote.netAmountFmt) * (EUR_RATES[symOut] ?? 1)).toFixed(2)}` : '≈ $0')
                  : (directQuote ? `≈ $${(parseFloat(directQuote.netFmt) * (EUR_RATES[sym] ?? 1)).toFixed(2)}` : '≈ $0')}
              </span>
            </div>
          </div>

          {/* ── Rate strip (solo swap mode) ─────────────────── */}
          {isSwapMode && swapQuote?.status === 'success' && parseFloat(amount) > 0 && (
            <div className="mt-2 px-4 py-2.5 rounded-xl border border-[rgba(200,81,44,0.2)] bg-[rgba(200,81,44,0.04)] flex items-center gap-3 text-[11px]">
              <span className="text-[#888780]">
                1 {sym} = <span className="text-[#2C2C2A] font-mono">{(parseFloat(swapQuote.amountOutFmt) / parseFloat(amount)).toFixed(4)}</span> {symOut}
              </span>
              <span className="text-[#888780]/50">·</span>
              <span className="text-[#888780]">Fee <span className="text-[#2C2C2A]">0.5%</span></span>
              <span className="text-[#888780]/50">·</span>
              <span className="text-[#888780]">Slippage <span className="text-[#2C2C2A]">0.5%</span></span>
            </div>
          )}

          {/* ── Card Send to ────────────────────────────────── */}
          <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">Send to</span>
              <button
                type="button"
                onClick={() => setToast({ msg: 'Contacts coming soon' })}
                className="flex items-center gap-1 px-2.5 py-1 text-[10px] font-medium text-[#C8512C] bg-transparent border border-[rgba(200,81,44,0.2)] rounded-md hover:bg-[rgba(200,81,44,0.06)] transition-colors cursor-pointer"
              >
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M2 3h8M2 6h8M2 9h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg>
                Contacts
              </button>
            </div>

            {clipboardAddress && clipboardAddress.toLowerCase() !== recipient.toLowerCase() && (
              <div className="flex items-center justify-between gap-2 mb-3 px-3 py-2 rounded-lg bg-[rgba(127,119,221,0.06)] border border-[rgba(127,119,221,0.2)]">
                <span className="text-[11px] text-[#2C2C2A] font-mono">
                  📋 {clipboardAddress.slice(0, 8)}…{clipboardAddress.slice(-6)}
                </span>
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => { setRecipient(clipboardAddress); validateAddr(clipboardAddress); setOracleData(null); setOracleDenied(false); dismissClipboard() }}
                    className="px-2 py-0.5 text-[10px] font-medium text-[#C8512C] bg-[rgba(200,81,44,0.1)] border border-[rgba(200,81,44,0.3)] rounded hover:bg-[rgba(200,81,44,0.18)] transition-colors cursor-pointer"
                  >
                    {t('useAddress')}
                  </button>
                  <button
                    type="button"
                    onClick={dismissClipboard}
                    className="px-2 py-0.5 text-[10px] text-[#7F77DD] bg-transparent border border-[rgba(127,119,221,0.2)] rounded hover:bg-[rgba(127,119,221,0.08)] transition-colors cursor-pointer"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )}

            <div className="flex items-center gap-3">
              <div className="w-[34px] h-[34px] rounded-[9px] bg-[rgba(200,81,44,0.06)] border border-[rgba(200,81,44,0.15)] flex items-center justify-center text-[#C8512C] shrink-0">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <circle cx="8" cy="6" r="2.5" stroke="currentColor" strokeWidth="1.3"/>
                  <path d="M3 13c0-2.5 2.2-4 5-4s5 1.5 5 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                </svg>
              </div>
              <input
                type="text"
                value={recipient}
                onChange={e => { setRecipient(e.target.value); validateAddr(e.target.value); setOracleData(null); setOracleDenied(false) }}
                placeholder="0x… or name.eth"
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                disabled={busy}
                className="flex-1 min-w-0 bg-transparent outline-none border-none text-[#2C2C2A] text-[15px] font-mono placeholder:text-[#888780]"
              />
            </div>

            {addrError && (
              <div className="mt-2 text-[11px] text-red-400 font-mono">{addrError}</div>
            )}

            <div className="mt-2">
              <AddressVerifier address={recipient} />
            </div>
          </div>

          {/* ── Warning banners ──────────────────────────────── */}
          {isLocked && (
            <div className="mt-2 flex items-center gap-2 rounded-xl px-3 py-2.5 bg-[rgba(217,119,6,0.06)] border border-[rgba(217,119,6,0.2)]">
              <span className="text-sm">🔒</span>
              <span className="text-[11px] font-medium text-[#B45309]">{t('transactionInProgress')}</span>
            </div>
          )}

          {oracleDenied && oracleData && !busy && (
            <div className="mt-2 rounded-xl px-3 py-2.5 bg-[rgba(220,38,38,0.08)] border border-[rgba(220,38,38,0.25)]">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-medium text-red-400">🚫 {t('blockedAml')}</span>
              </div>
              {oracleData.rejectionReason && (
                <div className="mt-1 text-[10px] text-[#888780] font-mono">{oracleData.rejectionReason}</div>
              )}
            </div>
          )}

          {showExtras && (
            <div className="mt-2 rounded-xl px-3.5 py-3 bg-[#FAFAF7] border border-[rgba(200,81,44,0.2)]">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-[0.08em] text-[#888780]">MiCA</div>
              <input
                type="text"
                placeholder={t('paymentRefPlaceholder')}
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                value={paymentRef}
                onChange={e => setPaymentRef(e.target.value)}
                disabled={busy}
                className="w-full mb-1.5 px-3 py-2 text-sm text-[#2C2C2A] bg-white border border-[rgba(200,81,44,0.2)] rounded-lg placeholder:text-[#888780] outline-none focus:border-[#C8512C]/60 transition-colors"
              />
              <input
                type="text"
                placeholder={t('fiscalId')}
                autoComplete="off"
                autoCorrect="off"
                spellCheck={false}
                value={fiscalRef}
                onChange={e => setFiscalRef(e.target.value)}
                disabled={busy}
                className="w-full px-3 py-2 text-sm text-[#2C2C2A] bg-white border border-[rgba(200,81,44,0.2)] rounded-lg placeholder:text-[#888780] outline-none focus:border-[#C8512C]/60 transition-colors"
              />
            </div>
          )}

          {phase === 'wait_send' && <div className="mt-2"><BallisticProgress active={true} /></div>}
          {(busy || phase === 'error') && (
            <div className="mt-2">
              {busy && <MicroStateBadge phase={phase} silent={false} />}
              {phase === 'error' && (
                <TransactionStatusUI phase="error" error={txError} isTestnet={chainId === baseSepolia.id} onReset={reset} />
              )}
            </div>
          )}

          {!feeRouterAvailable && isConnected && !isWrong && (
            <div className="mt-2 rounded-xl px-3 py-2.5 bg-[rgba(217,119,6,0.06)] border border-[rgba(217,119,6,0.2)]">
              <div className="text-[10px] leading-[1.5] text-[#B45309]">
                <strong>Direct mode</strong> — FeeRouter not deployed on {regChain?.chainName ?? 'this network'}.
                Transaction will be sent directly without Oracle verification and 0.5% fee.
              </div>
            </div>
          )}

          {/* ── CTA ──────────────────────────────────────────── */}
          <div className="mt-3">
            {ctaState === 'disconnected' ? (
              <ConnectButton.Custom>
                {({ openConnectModal }) => (
                  <button
                    type="button"
                    onClick={openConnectModal}
                    className="w-full py-3.5 rounded-2xl text-sm font-medium bg-[rgba(200,81,44,0.12)] text-[rgba(200,81,44,0.85)] border border-[rgba(200,81,44,0.25)] hover:bg-[rgba(200,81,44,0.2)] transition-colors cursor-pointer"
                  >
                    {t('connectWallet')}
                  </button>
                )}
              </ConnectButton.Custom>
            ) : (
              <button
                type="button"
                onClick={
                  ctaState === 'wrong_network' ? () => switchChain({ chainId: 8453 })
                  : ctaState === 'ready' ? () => setShowConfirmation(true)
                  : undefined
                }
                disabled={['busy','insufficient','no_recipient','no_amount','oracle_denied','no_liquidity'].includes(ctaState)}
                className={[
                  'w-full py-3.5 rounded-2xl text-sm font-medium transition-colors',
                  ctaState === 'ready' || ctaState === 'wrong_network'
                    ? 'bg-[#C8512C] text-white hover:bg-[#B04424] border-none cursor-pointer'
                    : 'bg-[rgba(200,81,44,0.12)] text-[rgba(200,81,44,0.5)] border border-[rgba(200,81,44,0.2)] cursor-not-allowed',
                ].join(' ')}
              >
                {busy ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="rp-spinner inline-block w-3.5 h-3.5 border-2 border-white/25 border-t-transparent rounded-full" />
                    <span>
                      {phase === 'preflight' ? 'AML Check…'
                        : phase === 'approving' || phase === 'wait_approve' ? t('approving')
                        : t('finalizing')}
                    </span>
                  </span>
                ) : ctaState === 'oracle_denied' ? t('transactionBlockedCta')
                  : ctaState === 'no_liquidity' ? t('insufficientLiquidityCta')
                  : ctaState === 'wrong_network' ? (noContract ? t('networkUnavailable', { chain: regChain?.chainName ?? 'Network' }) : t('switchNetwork'))
                  : ctaState === 'insufficient' ? t('ctaInsufficient', { symbol: displaySym })
                  : ctaState === 'no_recipient' ? t('enterRecipient')
                  : ctaState === 'no_amount' ? t('enterAmount')
                  : needsApproval && !tokenIn?.isNative ? t('ctaApprove', { symbol: displaySym })
                  : feeRouterAvailable ? t('ctaSend', { symbol: displaySym })
                  : t('ctaSendDirect', { symbol: displaySym })}
              </button>
            )}
          </div>

        </div>
      </div>

      {/* Token Selector Modal */}
      {selectingToken && createPortal(
        <TokenSelectorModal
          title={selectingToken === 'in' ? t('selectInputToken') : t('selectOutputToken')}
          tokens={tokenList}
          onClose={() => setSelectingToken(null)}
          isMobile={isMobile}
          currentChainId={chainId}
          multiChainTokens={selectingToken === 'out' && CROSSCHAIN_ENABLED
            ? TOKEN_LIST.filter(t => t.chainId !== chainId)
            : undefined}
          onSelectMultiChain={selectingToken === 'out' && CROSSCHAIN_ENABLED
            ? (t: TokenInfo) => {
                setCrossChainOut(t)
                // Find matching local token for tokenOut display (same symbol on current chain)
                const localMatch = tokenList.find(lt => lt.symbol === t.symbol)
                if (localMatch) setTokenOut(localMatch)
                setAmount(''); setOracleData(null); setOracleDenied(false)
                setSelectingToken(null)
              }
            : undefined}
          onSelect={t => {
            if (selectingToken === 'in') {
              setTokenIn(t)
            } else {
              setTokenOut(t)
              setCrossChainOut(null) // selecting local token → clear cross-chain
            }
            setAmount(''); setOracleData(null); setOracleDenied(false)
            setSelectingToken(null)
          }}
        />
      , document.body)}

      {toast && <Toast message={toast.msg} color={toast.color} onDismiss={() => setToast(null)} />}

      {/* TX Confirmation Sheet */}
      {(() => {
        // Fee breakdown computation
        const activeSym = displaySym
        const cgId = isExtERC20 ? externalToken!.coingeckoId : (tokenIn?.symbol === 'ETH' ? 'ethereum' : undefined)
        const eurRate = cgId && tokenPrices[cgId]
          ? (tokenPrices[cgId].eur ?? 0)
          : (tokenIn ? (EUR_RATES[tokenIn.symbol] ?? 1) : 0)
        const amtNum = parseFloat(amount || '0')
        const fiatNum = amtNum * eurRate
        const feeAmt = amtNum * 0.005
        const netAmt = amtNum - feeAmt
        const ethPrice = tokenPrices['ethereum']?.eur ?? 0
        const isStable = ['USDC', 'USDT', 'DAI', 'EURC'].includes(activeSym)
        const fmtDec = isStable ? 2 : activeSym === 'cbBTC' ? 6 : 4

        // Build TokenInfo for confirmation sheet
        const confirmTokenInfo: TokenInfo = isExtERC20
          ? externalToken!
          : {
              symbol: tokenIn?.symbol ?? 'ETH',
              name: tokenIn?.name ?? 'Ether',
              decimals: tokenIn?.decimals ?? 18,
              address: tokenIn?.isNative ? null : (tokenIn?.address as string ?? null),
              chainId,
              isNative: tokenIn?.isNative ?? true,
              logoUrl: tokenIn?.logoURI ?? '/tokens/eth.svg',
              coingeckoId: cgId ?? 'ethereum',
              minAmount: '0.0001',
            }

        // Chain info from registry
        const chainInfo = SUPPORTED_CHAINS[chainId as ChainId]

        // Gas estimates
        const gasEth = isL2 ? '0.00001' : '0.001'
        const gasEur = ethPrice > 0 ? (isL2 ? 0.00001 * ethPrice : 0.001 * ethPrice) : null

        return (
          <TxConfirmationSheet
            isOpen={showConfirmation}
            onConfirm={() => {
              setShowConfirmation(false)
              saveKnownRecipient(recipient)
              handleTransfer()
            }}
            onCancel={() => setShowConfirmation(false)}
            recipient={recipient}
            tokenInfo={confirmTokenInfo}
            amount={amount}
            eurValue={fiatNum > 0 ? fiatNum : null}
            feeAmount={feeAmt > 0 ? feeAmt.toFixed(fmtDec) : '0'}
            netAmount={netAmt > 0 ? netAmt.toFixed(fmtDec) : '0'}
            gasEstimate={{
              eth: gasEth,
              eur: gasEur,
              level: isL2 ? 'low' : 'medium',
            }}
            chain={chainInfo
              ? { name: chainInfo.name, iconUrl: chainInfo.iconUrl }
              : { name: regChain?.chainName ?? 'Base', iconUrl: '/chains/base.svg' }
            }
            estimatedTime={isL2 ? t('estimatedTimeL2') : t('estimatedTimeL1')}
            isHighValue={fiatNum >= 1000}
            isNewRecipient={recipient ? !isKnownRecipient(recipient) : false}
            antiPhishingCode={(() => { try { return localStorage.getItem('rsend_antiphishing_code') || undefined } catch { return undefined } })()}
          />
        )
      })()}
    </>
  )
}