'use client'


import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import {
  useAccount, useBalance, useReadContracts,
  useWriteContract, useWaitForTransactionReceipt,
  usePublicClient, useChainId,
} from 'wagmi'
import {
  parseEther, parseUnits, formatEther, formatUnits,
  erc20Abi, type Abi,
} from 'viem'
import { getRegistry, type TokenConfig } from '../lib/contractRegistry'
import { FEE_ROUTER_V6_ABI } from '../lib/feeRouterAbi'
import { useSwapQuote } from '../lib/useSwapQuote'
import { mutationHeaders } from '../lib/rsendFetch'
import { useIsMobile } from '../hooks/useIsMobile'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { CHAIN_NAMES } from './command-center/shared'
import { emitTxSubmitted, emitTxConfirmed } from '@/lib/tx-events'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'

// ═══════════════════════════════════════════════════════════
//  PALETTE
// ═══════════════════════════════════════════════════════════
import { C as BaseC } from '@/app/designTokens'
const C = { ...BaseC, input: '#FAFAFA', pink: '#C8512C', green: '#00ffa3', red: '#ff2d55', amber: '#ffb800' }

// ═══════════════════════════════════════════════════════════
//  TOKEN ICON
// ═══════════════════════════════════════════════════════════
const TK: Record<string, string> = {
  ETH:'#627EEA',WETH:'#627EEA',USDC:'#2775CA',USDT:'#26A17B',
  EURC:'#2244aa',cbBTC:'#F7931A',WBTC:'#F7931A',DAI:'#F5AC37',
  DEGEN:'#845ef7',AERO:'#0091FF',LINK:'#2A5ADA',
}
const LOGOS: Record<string, string> = {
  ETH:'https://assets.coingecko.com/coins/images/279/small/ethereum.png',
  USDC:'https://assets.coingecko.com/coins/images/6319/small/usdc.png',
  USDT:'https://assets.coingecko.com/coins/images/325/small/Tether.png',
  EURC:'https://assets.coingecko.com/coins/images/26045/small/euro-coin.png',
  cbBTC:'https://assets.coingecko.com/coins/images/40143/small/cbbtc.png',
  WBTC:'https://assets.coingecko.com/coins/images/7598/small/wrapped_bitcoin_wbtc.png',
  DAI:'https://assets.coingecko.com/coins/images/9956/small/Badge_Dai.png',
  DEGEN:'https://assets.coingecko.com/coins/images/34515/small/android-chrome-512x512.png',
}

function TIcon({ symbol, size = 28 }: { symbol: string; size?: number }) {
  const [err, setErr] = useState(false)
  const logo = LOGOS[symbol]
  const c = TK[symbol] ?? '#5E5E5E'
  if (logo && !err) return (
    <div style={{ width:size, height:size, borderRadius:'50%', border:'1px solid rgba(10,10,10,0.08)', overflow:'hidden', flexShrink:0, background:C.surface }}>
      <img src={logo} alt={symbol} width={size} height={size} style={{ width:'100%', height:'100%', objectFit:'cover' }} onError={() => setErr(true)} />
    </div>
  )
  return (
    <div style={{ width:size, height:size, borderRadius:'50%', background:`${c}18`, border:'1px solid rgba(10,10,10,0.08)', display:'flex', alignItems:'center', justifyContent:'center', fontFamily:C.D, fontSize:size*0.36, fontWeight:700, color:`${c}aa`, flexShrink:0 }}>
      {symbol.slice(0,2)}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  FEE ROUTER ABI 
// ═══════════════════════════════════════════════════════════
const FEE_ROUTER_ABI: Abi = [
  { name:'swapAndSend', type:'function', stateMutability:'nonpayable',
    inputs:[{name:'tokenIn',type:'address'},{name:'tokenOut',type:'address'},{name:'amountIn',type:'uint256'},{name:'minAmountOut',type:'uint256'},{name:'recipient',type:'address'},{name:'nonce',type:'bytes32'},{name:'deadline',type:'uint256'},{name:'oracleSignature',type:'bytes'}], outputs:[] },
  { name:'swapETHAndSend', type:'function', stateMutability:'payable',
    inputs:[{name:'tokenOut',type:'address'},{name:'minAmountOut',type:'uint256'},{name:'recipient',type:'address'},{name:'nonce',type:'bytes32'},{name:'deadline',type:'uint256'},{name:'oracleSignature',type:'bytes'}], outputs:[] },
]

type Phase = 'idle' | 'quoting' | 'approving' | 'signing_oracle' | 'swapping' | 'success' | 'error'

// ═══════════════════════════════════════════════════════════
//  SWAP MODULE
// ═══════════════════════════════════════════════════════════
interface PortfolioAsset {
  symbol: string; balance: number; decimals: number
  contractAddress: string; logo?: string | null
}

interface SwapModuleProps {
  onSwapComplete?: () => void
  portfolioAssets?: PortfolioAsset[]
  noCard?: boolean
}

// ─── UI helpers ────────────────────────────────────────────────
function CompactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-3 flex items-center justify-between">
      <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">{label}</span>
      <span className="text-[13px] text-[#2C2C2A] font-mono">{value}</span>
    </div>
  )
}

function RowKV({ k, v, mono = false, color }: { k: string; v: React.ReactNode; mono?: boolean; color?: string }) {
  return (
    <div className="flex justify-between text-[#888780]">
      <span>{k}</span>
      <span className={mono ? 'text-[#2C2C2A] font-mono' : ''} style={color ? { color } : undefined}>{v}</span>
    </div>
  )
}

export default function SwapModule({ onSwapComplete, portfolioAssets, noCard }: SwapModuleProps) {
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const publicClient = usePublicClient()
  const reg = getRegistry(chainId)
  const isMobile = useIsMobile()
  const t = useTranslations('swap')

  // Token state
  const tokens = useMemo(() => {
    if (!reg) return []
    return Object.values(reg.tokens) as TokenConfig[]
  }, [reg])

  const [tokenIn, setTokenIn] = useState<TokenConfig | null>(null)
  const [tokenOut, setTokenOut] = useState<TokenConfig | null>(null)
  const [amount, setAmount] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [txHash, setTxHash] = useState<`0x${string}` | undefined>()
  const [selectingFor, setSelectingFor] = useState<'in' | 'out' | null>(null)
  const [slippage, setSlippage] = useState(0.5)
  const [showSettings, setShowSettings] = useState(false)

  // Init default tokens
  useEffect(() => {
    if (!tokens.length) return
    const eth = tokens.find(t => t.isNative) ?? tokens[0]
    const usdc = tokens.find(t => t.symbol === 'USDC') ?? tokens[1] ?? eth
    setTokenIn(eth ?? null)
    setTokenOut(usdc ?? null)
    setAmount('')
    setPhase('idle')
  }, [tokens])

  // Balances — prefer portfolio data, fallback to RPC
  const { data: ethBal } = useBalance({ address })
  const erc20s = tokens.filter(t => !t.isNative)
  const { data: erc20Bals } = useReadContracts({
    contracts: erc20s.map(t => ({
      address: t.address!, abi: erc20Abi,
      functionName: 'balanceOf' as const, args: [address!],
    })),
    query: { enabled: !!address && erc20s.length > 0 },
  })

  const getBalance = useCallback((t: TokenConfig): bigint => {
    // 1. Try portfolio data first (most reliable, already fetched from Alchemy)
    if (portfolioAssets?.length) {
      const pa = portfolioAssets.find(a =>
        a.symbol === t.symbol ||
        (a.contractAddress?.toLowerCase() === t.address?.toLowerCase() && t.address !== '0x0000000000000000000000000000000000000000')
      )
      if (pa && pa.balance > 0) {
        return BigInt(Math.round(pa.balance * (10 ** (t.decimals ?? 18))))
      }
    }

    // 2. Fallback: RPC data
    if (t.isNative) return ethBal?.value ?? 0n
    const idx = erc20s.findIndex(e => e.symbol === t.symbol)
    if (idx >= 0) {
      const val = erc20Bals?.[idx]?.result as bigint | undefined
      if (val && val > 0n) return val
    }

    return 0n
  }, [ethBal, erc20Bals, erc20s, portfolioAssets])

  const inBal = tokenIn ? getBalance(tokenIn) : 0n
  const inBalFmt = tokenIn ? parseFloat(formatUnits(inBal, tokenIn.decimals)) : 0

  // Parse amount
  const parsedAmount = useMemo((): bigint | null => {
    if (!tokenIn || !amount || isNaN(Number(amount)) || Number(amount) <= 0) return null
    try { return tokenIn.isNative ? parseEther(amount) : parseUnits(amount, tokenIn.decimals) }
    catch { return null }
  }, [tokenIn, amount])

  // Swap quote
  const quote = useSwapQuote({
    chainId,
    tokenIn: tokenIn && tokenOut && tokenIn.address !== tokenOut.address ? tokenIn : null,
    tokenOut: tokenIn && tokenOut && tokenIn.address !== tokenOut.address ? tokenOut : null,
    amountIn: amount,
    slippageBps: Math.round(slippage * 100),
  })

  // TX receipt
  const { writeContractAsync } = useWriteContract()
  const { isSuccess } = useWaitForTransactionReceipt({
    hash: txHash, query: { enabled: !!txHash && phase === 'swapping' },
  })

  const clientIdRef = useRef<string | null>(null)
  const lastSubmittedHashRef = useRef<string | null>(null)
  const lastConfirmedHashRef = useRef<string | null>(null)

  useEffect(() => {
    if (isSuccess && phase === 'swapping') {
      setPhase('success')
      sendCallback()
      onSwapComplete?.()
    }
  }, [isSuccess, phase])

  // ── Server persistence: emit tx-submitted once per new txHash ──────────
  useEffect(() => {
    if (!txHash || phase !== 'swapping' || !address || !tokenIn || !tokenOut) return
    if (lastSubmittedHashRef.current === txHash) return
    lastSubmittedHashRef.current = txHash

    const clientId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    clientIdRef.current = clientId

    emitTxSubmitted({
      clientId,
      chain_id: chainId,
      tx_hash: txHash,
      wallet_address: address,
      tx_type: 'swap',
      tx_status: 'confirming',
      direction: 'out',
      token_symbol: tokenIn.symbol,
      token_address: tokenIn.address ?? null,
      amount_raw: parsedAmount ? parsedAmount.toString() : null,
      amount_decimal: amount || null,
      counterparty_address: address,
      extra_metadata: {
        source: 'SwapModule',
        tokenOutSymbol: tokenOut.symbol,
        tokenOutAddress: tokenOut.address ?? null,
        slippageBps: Math.round(slippage * 100),
        minAmountOut:
          quote?.status === 'success' && quote.minAmountOut
            ? quote.minAmountOut.toString()
            : null,
      },
      submitted_at: new Date().toISOString(),
    })
  }, [txHash, phase, address, chainId, tokenIn, tokenOut, parsedAmount, amount, slippage, quote])

  // ── Server persistence: emit tx-confirmed when phase resolves ──────────
  useEffect(() => {
    const clientId = clientIdRef.current
    if (!txHash || !clientId) return
    if (lastConfirmedHashRef.current === txHash) return
    const tx_status: 'confirmed' | 'failed' | null =
      phase === 'success' ? 'confirmed' : phase === 'error' ? 'failed' : null
    if (!tx_status) return
    lastConfirmedHashRef.current = txHash
    emitTxConfirmed({
      clientId,
      tx_hash: txHash,
      chain_id: chainId,
      tx_status,
      confirmed_at: new Date().toISOString(),
    })
  }, [phase, txHash, chainId])

  // Flip tokens
  const flip = () => {
    const tmp = tokenIn
    setTokenIn(tokenOut)
    setTokenOut(tmp)
    setAmount('')
  }

  // Percentage buttons
  const setPercentage = (pct: number) => {
    if (!tokenIn) return
    const bal = getBalance(tokenIn)
    let amt: bigint
    if (pct === 100 && tokenIn.isNative) {
      // Reserve gas
      const gasReserve = 50000n * 10000000n // ~0.0005 ETH
      amt = bal > gasReserve ? bal - gasReserve : 0n
    } else {
      amt = (bal * BigInt(pct)) / 100n
    }
    setAmount(formatUnits(amt, tokenIn.decimals))
  }

  // Execute swap
  const handleSwap = async () => {
    if (!parsedAmount || !tokenIn || !tokenOut || !reg || !address) return
    if (!quote || quote.status !== 'success') return

    setError('')

    try {
      // 1. Oracle signature
      setPhase('signing_oracle')
      const oracleRes = await fetch('/api/oracle/sign', {
        method: 'POST', headers: mutationHeaders(),
        body: JSON.stringify({
          sender: address,
          recipient: address, // swap to self
          tokenIn: tokenIn.isNative ? '0x0000000000000000000000000000000000000000' : tokenIn.address,
          tokenOut: tokenOut.address,
          amountIn: formatUnits(parsedAmount, tokenIn.decimals),
          amountInWei: parsedAmount.toString(),
          symbol: tokenIn.symbol,
          chainId,
        }),
        signal: AbortSignal.timeout(10000),
      })
      const oracle = await oracleRes.json()
      if (!oracle?.approved) {
        setError(oracle?.rejectionReason ?? t('oracleRejected'))
        setPhase('error'); return
      }

      // M1 slice B: V5/V6 take a threshold bytes[] (oracleSignatures); V4 a single bytes.
      const isV6 = reg.version === 'v6'
      const routerAbi = isV6 ? FEE_ROUTER_V6_ABI : FEE_ROUTER_ABI
      const oracleSigArg = isV6
        ? (oracle.oracleSignatures as `0x${string}`[])
        : (oracle.oracleSignature as `0x${string}`)

      // 2. Approve (ERC-20 only)
      if (!tokenIn.isNative) {
        setPhase('approving')
        const appHash = await writeContractAsync({
          address: tokenIn.address!, abi: erc20Abi,
          functionName: 'approve',
          args: [reg.feeRouter, parsedAmount],
        })
        // Wait for approval (simplified)
        await publicClient?.waitForTransactionReceipt({ hash: appHash })
      }

      // 3. Swap
      setPhase('swapping')
      const minOut = quote.minAmountOut

      let hash: `0x${string}`
      if (tokenIn.isNative) {
        hash = await writeContractAsync({
          address: reg.feeRouter, abi: routerAbi,
          functionName: 'swapETHAndSend',
          args: [tokenOut.address!, minOut, address, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg],
          value: parsedAmount,
        })
      } else {
        hash = await writeContractAsync({
          address: reg.feeRouter, abi: routerAbi,
          functionName: 'swapAndSend',
          args: [tokenIn.address!, tokenOut.address!, parsedAmount, minOut, address, oracle.oracleNonce as `0x${string}`, BigInt(oracle.oracleDeadline), oracleSigArg],
        })
      }
      setTxHash(hash)

    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('rejected') || msg.includes('denied')) {
        setPhase('idle'); return
      }
      setError(msg.slice(0, 100))
      setPhase('error')
    }
  }

  // Backend callback
  const sendCallback = async () => {
    if (!txHash || !tokenIn || !tokenOut || !address) return
    try {
      await fetch(`${BACKEND}/api/v1/tx/callback`, {
        method: 'POST', headers: mutationHeaders(),
        body: JSON.stringify({
          fiscal_ref: `SWAP-${Date.now()}`,
          tx_hash: txHash,
          gross_amount: parseFloat(amount),
          net_amount: quote?.netAmountOut ? parseFloat(formatUnits(quote.netAmountOut, tokenOut.decimals)) : 0,
          fee_amount: quote?.feeAmount ? parseFloat(formatUnits(quote.feeAmount, tokenOut.decimals)) : 0,
          currency: `${tokenIn.symbol}→${tokenOut.symbol}`,
          network: chainId === 8453 ? 'BASE_MAINNET' : chainId === 84532 ? 'BASE_SEPOLIA' : 'BASE',
          status: 'completed',
          recipient: address,
          timestamp: new Date().toISOString(),
          x_signature: 'PENDING_HMAC_SHA256',
          is_testnet: chainId === 84532,
        }),
      })
    } catch { /* silent */ }
  }

  // Derived state
  const insufficient = !!parsedAmount && parsedAmount > inBal
  const noLiquidity = quote?.status === 'error_liquidity'
  const sameToken = tokenIn?.address === tokenOut?.address
  const busy = ['signing_oracle','approving','swapping'].includes(phase)
  const canSwap = isConnected && parsedAmount && !insufficient && !noLiquidity && !sameToken && quote?.status === 'success' && !busy

  const priceImpact = useMemo(() => {
    if (!quote || quote.status !== 'success' || !parsedAmount || !tokenIn || !tokenOut) return null
    // Rough price impact estimation
    const inUsd = parseFloat(amount) * 2150 // simplified
    const outUsd = parseFloat(formatUnits(quote.amountOut, tokenOut.decimals))
    if (inUsd === 0) return null
    const impact = ((inUsd - outUsd) / inUsd) * 100
    return Math.abs(impact)
  }, [quote, parsedAmount, amount, tokenIn, tokenOut])

  // Reset on success
  const reset = () => {
    setPhase('idle'); setAmount(''); setError(''); setTxHash(undefined)
  }

  // ─── Redesign state (UI-only) ────────────────────────────────
  const [slippageMode, setSlippageMode] = useState<'auto' | 'preset' | 'custom'>('preset')
  const [customSlippage, setCustomSlippage] = useState<string>('')
  const [flipRotation, setFlipRotation] = useState<number>(0)

  const handleFlip = () => { flip(); setFlipRotation(r => r + 180) }

  const chainLabel = CHAIN_NAMES[chainId] ?? `Chain ${chainId}`

  const amountOutDisplay = useMemo(() => {
    if (!quote || !tokenOut) return '0'
    if (quote.status === 'loading') return '…'
    if (quote.status !== 'success') return '0'
    return parseFloat(formatUnits(quote.amountOut, tokenOut.decimals)).toFixed(4)
  }, [quote, tokenOut])

  const rate = useMemo(() => {
    if (quote?.status !== 'success' || !parseFloat(amount || '0')) return '—'
    const r = parseFloat(amountOutDisplay) / parseFloat(amount)
    return Number.isFinite(r) ? r.toFixed(4) : '—'
  }, [quote, amount, amountOutDisplay])

  const slippageWarning = useMemo(() => {
    if (slippage > 5) return { severity: 'high' as const, message: 'Very high slippage — frontrunning risk.' }
    if (slippage > 1) return { severity: 'medium' as const, message: 'High slippage — you may receive less than expected.' }
    return null
  }, [slippage])

  const minReceivedFmt = useMemo(() => {
    if (!quote || quote.status !== 'success' || !tokenOut) return '—'
    return parseFloat(formatUnits(quote.minAmountOut, tokenOut.decimals)).toFixed(4)
  }, [quote, tokenOut])

  const priceImpactDisplay = priceImpact == null ? '< 0.01%' : `${priceImpact.toFixed(2)}%`
  const priceImpactColor = priceImpact == null ? undefined
    : priceImpact < 1 ? '#639922'
    : priceImpact < 3 ? '#BA7517'
    : '#A32D2D'

  const networkFeeFmt = quote?.gasEstimate ? `~$${parseFloat(String(quote.gasEstimate)).toFixed(2)}` : '~$0.02'
  const routeLabel = `Uniswap V3 · ${chainLabel}`

  if (!reg) return null

  return (
    <div className={noCard ? '' : 'rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white p-4'}>
      <div className="mx-auto w-full max-w-[440px] flex flex-col gap-1 rp-stagger-host">

        {/* ── PAY ───────────────────────────────────────────── */}
        {showSettings ? (
          <CompactRow label={t('pay') ?? 'Pay'} value={`${amount || '0'} ${tokenIn?.symbol ?? ''}`} />
        ) : (
          <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">{t('pay') ?? 'Pay'}</span>
              {tokenIn && (
                <span className="text-[11px] text-[#888780] font-mono">
                  {inBalFmt.toFixed(4)} {tokenIn.symbol}
                </span>
              )}
            </div>
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectingFor('in')}
                disabled={busy}
                className="flex items-center gap-2 pl-1.5 pr-2.5 py-1.5 rounded-full border border-[rgba(200,81,44,0.2)] bg-[#FAFAF7] text-[#2C2C2A] shrink-0 hover:bg-[#F5F2ED] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {tokenIn && <TIcon symbol={tokenIn.symbol} size={22} />}
                <span className="text-sm font-medium">{tokenIn?.symbol ?? '—'}</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="opacity-50">
                  <path d="M2.5 4L5 6.5L7.5 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
              <input
                type="number" placeholder="0.00" min="0" step="any"
                value={amount} onChange={e => { setAmount(e.target.value); setPhase('idle') }}
                disabled={busy}
                className="flex-1 min-w-0 bg-transparent border-none outline-none text-right text-[#2C2C2A] text-[28px] font-medium tabular-nums tracking-[-0.02em] disabled:opacity-50"
              />
            </div>
            <div className="flex items-center gap-1 mt-3">
              {[25, 50, 75, 100].map(p => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPercentage(p)}
                  disabled={busy}
                  className="flex-1 px-2 py-1 text-[10px] font-medium rounded-md border border-[rgba(200,81,44,0.2)] text-[#888780] hover:text-[#C8512C] hover:border-[rgba(200,81,44,0.4)] hover:bg-[rgba(200,81,44,0.04)] transition-colors disabled:opacity-50"
                >
                  {p === 100 ? (t('max') ?? 'Max') : `${p}%`}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Flip divider (hidden when panel open) ────────── */}
        {!showSettings && (
          <div className="relative z-[2] flex justify-center -my-2.5">
            <motion.button
              type="button"
              onClick={handleFlip}
              disabled={busy || !tokenIn || !tokenOut}
              aria-label={t('flip') ?? 'Flip tokens'}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.92 }}
              animate={{ rotate: flipRotation }}
              transition={{ type: 'spring', stiffness: 320, damping: 22 }}
              className="w-9 h-9 rounded-[10px] bg-white border border-[rgba(200,81,44,0.35)] text-[#C8512C] flex items-center justify-center hover:bg-[#FAFAF7] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M4 2v10M4 12l-2-2M4 12l2-2M10 12V2M10 2l-2 2M10 2l2 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </motion.button>
          </div>
        )}

        {/* ── RECEIVE ───────────────────────────────────────── */}
        {showSettings ? (
          <CompactRow label={t('receive') ?? 'Receive'} value={`${amountOutDisplay} ${tokenOut?.symbol ?? ''}`} />
        ) : (
          <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white px-5 py-4">
            <div className="flex items-center justify-between mb-3.5">
              <span className="text-[12px] font-medium text-[#C8512C] tracking-[0.3px]">{t('receive') ?? 'Receive'}</span>
              {/* Cross-chain stub chip — disabled */}
              <div
                className="inline-flex items-center gap-1 px-2 py-1 text-[10px] text-[#888780] bg-[rgba(136,135,128,0.08)] border border-[rgba(136,135,128,0.2)] rounded-md cursor-not-allowed"
                title="Cross-chain swap coming soon"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#1D9E75]" />
                <span>{chainLabel}</span>
              </div>
              {/* TODO(crosschain): wire to NetworkSelector state; when enabled, show dropdown to pick destination chain. Requires CCIPSender integration. */}
            </div>
            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setSelectingFor('out')}
                disabled={busy}
                className="flex items-center gap-2 pl-1.5 pr-2.5 py-1.5 rounded-full border border-[rgba(200,81,44,0.2)] bg-[#FAFAF7] text-[#2C2C2A] shrink-0 hover:bg-[#F5F2ED] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {tokenOut && <TIcon symbol={tokenOut.symbol} size={22} />}
                <span className="text-sm font-medium">{tokenOut?.symbol ?? '—'}</span>
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="opacity-50">
                  <path d="M2.5 4L5 6.5L7.5 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </button>
              <span className="flex-1 min-w-0 text-right text-[#2C2C2A] text-[28px] font-medium tabular-nums tracking-[-0.02em]">
                {amountOutDisplay}
              </span>
            </div>
          </div>
        )}

        {/* ── Rate strip + expandable slippage panel ────────── */}
        <div className={showSettings ? 'mt-2 rounded-xl border border-[rgba(200,81,44,0.35)] bg-white overflow-hidden' : ''}>
          <button
            type="button"
            onClick={() => setShowSettings(s => !s)}
            aria-expanded={showSettings}
            className={[
              'w-full flex items-center justify-between gap-3 px-4 py-2.5 text-[11px] transition-colors',
              showSettings
                ? 'bg-[rgba(200,81,44,0.04)] border-b border-[rgba(200,81,44,0.15)]'
                : 'mt-2 rounded-xl border border-[rgba(200,81,44,0.2)] bg-[rgba(200,81,44,0.04)] hover:bg-[rgba(200,81,44,0.08)]',
            ].join(' ')}
          >
            <div className="flex items-center gap-3 text-[#888780] flex-wrap">
              <span>1 {tokenIn?.symbol ?? ''} = <span className="text-[#2C2C2A] font-mono">{rate}</span> {tokenOut?.symbol ?? ''}</span>
              <span className="text-[#888780]/40">·</span>
              <span>{t('fee') ?? 'Fee'} <span className="text-[#2C2C2A]">0.5%</span></span>
              <span className="text-[#888780]/40">·</span>
              <span>{t('slippage') ?? 'Slippage'} <span className="text-[#C8512C] font-medium">{slippage}%</span></span>
            </div>
            <svg
              width="12" height="12" viewBox="0 0 12 12" fill="none"
              className={['text-[#C8512C] opacity-70 transition-transform shrink-0', showSettings ? 'rotate-180' : ''].join(' ')}
            >
              <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>

          <AnimatePresence initial={false}>
            {showSettings && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
                style={{ overflow: 'hidden' }}
              >
                <div className="px-4 py-3.5 flex flex-col gap-3">

                  {/* Preset row */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[12px] font-medium text-[#2C2C2A]">{t('maxSlippage') ?? 'Max slippage'}</span>
                      <span className="text-[11px] text-[#888780]">
                        {slippageMode === 'auto' ? `Auto · ${slippage}%` : `${slippage}%`}
                      </span>
                    </div>
                    <div className="flex gap-1.5">
                      {([
                        { key: 'auto', label: 'Auto', val: 0.5 },
                        { key: 'p1',   label: '0.1%', val: 0.1 },
                        { key: 'p5',   label: '0.5%', val: 0.5 },
                        { key: 'p10',  label: '1%',   val: 1   },
                      ] as const).map((opt) => {
                        const isAuto = opt.key === 'auto'
                        const active = isAuto
                          ? slippageMode === 'auto'
                          : (slippageMode === 'preset' && slippage === opt.val)
                        return (
                          <button
                            key={opt.key}
                            type="button"
                            onClick={() => {
                              if (isAuto) { setSlippageMode('auto'); setSlippage(0.5) }
                              else { setSlippageMode('preset'); setSlippage(opt.val) }
                              setCustomSlippage('')
                            }}
                            className={[
                              'flex-1 px-2 py-1.5 text-[11px] font-medium rounded-lg transition-colors',
                              active
                                ? 'bg-[rgba(200,81,44,0.1)] border border-[rgba(200,81,44,0.3)] text-[#C8512C]'
                                : 'bg-transparent border border-[rgba(136,135,128,0.3)] text-[#888780] hover:text-[#2C2C2A]',
                            ].join(' ')}
                          >
                            {opt.label}
                          </button>
                        )
                      })}
                      <div className={[
                        'flex-[1.2] flex items-center px-2 text-[11px] rounded-lg border transition-colors',
                        slippageMode === 'custom'
                          ? 'border-[rgba(200,81,44,0.3)] bg-[rgba(200,81,44,0.06)]'
                          : 'border-[rgba(136,135,128,0.3)] bg-transparent',
                      ].join(' ')}>
                        <input
                          placeholder="Custom"
                          value={customSlippage}
                          onChange={(e) => {
                            const v = e.target.value
                            setCustomSlippage(v)
                            setSlippageMode('custom')
                            const n = parseFloat(v)
                            if (Number.isFinite(n) && n > 0) setSlippage(n)
                          }}
                          className="flex-1 min-w-0 border-none bg-transparent outline-none text-[11px] text-[#2C2C2A] font-mono placeholder:text-[#888780]"
                        />
                        <span className="text-[#888780]">%</span>
                      </div>
                    </div>

                    {slippageWarning && (
                      <div className={[
                        'mt-2 px-3 py-2 rounded-lg text-[11px] flex items-start gap-2',
                        slippageWarning.severity === 'high'
                          ? 'bg-[rgba(226,75,74,0.08)] text-[#A32D2D] border border-[rgba(226,75,74,0.2)]'
                          : 'bg-[rgba(239,159,39,0.08)] text-[#854F0B] border border-[rgba(239,159,39,0.2)]',
                      ].join(' ')}>
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="mt-[1px] shrink-0">
                          <path d="M6 1l5 9H1l5-9z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
                          <path d="M6 5v2" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
                          <circle cx="6" cy="8.5" r="0.5" fill="currentColor"/>
                        </svg>
                        <span>{slippageWarning.message}</span>
                      </div>
                    )}
                  </div>

                  <div className="h-px bg-[rgba(136,135,128,0.2)]" />

                  {/* KV details */}
                  <div className="flex flex-col gap-1.5 text-[11px]">
                    <RowKV k={t('minReceived') ?? 'Minimum received'} v={`${minReceivedFmt} ${tokenOut?.symbol ?? ''}`} mono />
                    <RowKV k={t('priceImpact') ?? 'Price impact'} v={priceImpactDisplay} color={priceImpactColor} />
                    <RowKV k={t('route') ?? 'Route'} v={routeLabel} />
                    <RowKV k={t('networkFee') ?? 'Network fee'} v={networkFeeFmt} mono />
                    <RowKV
                      k={t('receiveChain') ?? 'Receive on'}
                      v={
                        <span className="flex items-center gap-1.5 text-[#888780]">
                          <span>{chainLabel}</span>
                          <span className="px-1.5 py-0.5 text-[9px] bg-[rgba(136,135,128,0.1)] border border-[rgba(136,135,128,0.2)] rounded uppercase tracking-wide">
                            {t('sameChain') ?? 'Same chain'}
                          </span>
                        </span>
                      }
                    />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* ── Errors / warnings ─────────────────────────────── */}
        {noLiquidity && (
          <div className="mt-2 px-3 py-2.5 rounded-xl bg-[rgba(226,75,74,0.08)] border border-[rgba(226,75,74,0.2)] text-[11px] text-[#A32D2D]">
            {quote?.errorMessage ?? t('insufficientLiquidity')}
          </div>
        )}
        {phase === 'error' && error && (
          <div className="mt-2 px-3 py-2.5 rounded-xl bg-[rgba(226,75,74,0.08)] border border-[rgba(226,75,74,0.2)] text-[11px] text-[#A32D2D]">
            {error}
          </div>
        )}

        {/* ── Success ───────────────────────────────────────── */}
        {phase === 'success' && txHash && (
          <div className="mt-2 px-4 py-3.5 rounded-2xl bg-[rgba(29,158,117,0.08)] border border-[rgba(29,158,117,0.25)] text-center">
            <div className="text-[13px] font-semibold text-[#0F7A52]">{t('swapCompleted')}</div>
            <div className="mt-2">
              <a
                href={`${reg?.blockExplorer ?? 'https://basescan.org'}/tx/${txHash}`}
                target="_blank" rel="noopener noreferrer"
                className="text-[10px] text-[#888780] underline"
              >
                {t('viewOnExplorer')}
              </a>
            </div>
            <div className="mt-2.5">
              <button
                type="button"
                onClick={reset}
                className="px-5 py-2 rounded-xl bg-white border border-[rgba(200,81,44,0.3)] text-[#2C2C2A] text-[12px] font-medium hover:bg-[#FAFAF7] transition-colors"
              >
                {t('newSwap')}
              </button>
            </div>
          </div>
        )}

        {/* ── CTA ───────────────────────────────────────────── */}
        {phase !== 'success' && (
          <button
            type="button"
            onClick={handleSwap}
            disabled={!canSwap}
            className={[
              'mt-3 w-full py-3.5 rounded-2xl text-sm font-medium transition-colors',
              canSwap
                ? 'bg-[#C8512C] text-white border border-transparent hover:bg-[#B04424]'
                : 'bg-[rgba(200,81,44,0.08)] text-[rgba(200,81,44,0.55)] border border-[rgba(200,81,44,0.3)] cursor-not-allowed',
            ].join(' ')}
          >
            {busy ? (
              <span className="flex items-center justify-center gap-2">
                <span className="rp-spinner" style={{ width: 14, height: 14, border: '2px solid rgba(200,81,44,0.25)', borderTopColor: '#fff', borderRadius: '50%' }} />
                {phase === 'signing_oracle' ? t('amlCheck')
                  : phase === 'approving' ? t('approving')
                  : t('swapping')}
              </span>
            ) : insufficient ? t('insufficientBalance')
              : sameToken ? t('selectDifferentTokens')
              : noLiquidity ? t('insufficientLiquidity')
              : !parsedAmount ? t('enterAmount')
              : `Swap ${tokenIn?.symbol} → ${tokenOut?.symbol}`}
          </button>
        )}

      </div>

      {/* ── Token Selector Modal ───────────────────────────── */}
      {selectingFor && createPortal(
        <div style={{ position: 'fixed', inset: 0, zIndex: 100000, display: 'flex', alignItems: isMobile ? 'flex-end' : 'center', justifyContent: 'center' }}>
          <div onClick={() => setSelectingFor(null)} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.55)' }} />
          <div style={{
            position: 'relative',
            ...(isMobile ? { width: '100%', maxHeight: '85dvh', borderRadius: '20px 20px 0 0' } : { width: 380, maxHeight: 420, borderRadius: 20 }),
            background: '#FFFFFF', border: '1px solid rgba(10,10,10,0.10)',
            boxShadow: '0 24px 80px rgba(0,0,0,0.9), 0 0 0 1px rgba(10,10,10,0.04)',
            overflow: 'hidden', display: 'flex', flexDirection: 'column' as const,
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '16px 18px 12px', borderBottom: '1px solid rgba(10,10,10,0.08)',
            }}>
              <span style={{ fontFamily: C.D, fontSize: 15, fontWeight: 800, color: C.text }}>{t('selectToken')}</span>
              <button onClick={() => setSelectingFor(null)} style={{
                width: 30, height: 30, borderRadius: 8, background: 'rgba(10,10,10,0.08)',
                border: 'none', color: C.dim, cursor: 'pointer', fontSize: 16,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>✕</button>
            </div>
            <div style={{ overflowY: 'auto', ...(isMobile ? { flex: 1 } : { maxHeight: 360 }) }}>
              {[...tokens]
                .sort((a, b) => {
                  const bA = Number(getBalance(a)) / (10 ** a.decimals)
                  const bB = Number(getBalance(b)) / (10 ** b.decimals)
                  return bB - bA
                })
                .map((t, i, arr) => {
                  const bal = getBalance(t)
                  const balFmt = parseFloat(formatUnits(bal, t.decimals))
                  return (
                    <button key={t.symbol} onClick={() => {
                      if (selectingFor === 'in') setTokenIn(t)
                      else setTokenOut(t)
                      setSelectingFor(null)
                      setAmount('')
                    }} style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 14,
                      padding: '13px 18px', background: 'transparent', border: 'none',
                      borderBottom: i < arr.length - 1 ? '1px solid rgba(10,10,10,0.05)' : 'none',
                      cursor: 'pointer', transition: 'background 0.12s', textAlign: 'left' as const,
                      opacity: balFmt > 0 ? 1 : 0.5,
                    }}
                      onMouseEnter={e => e.currentTarget.style.background = 'rgba(10,10,10,0.05)'}
                      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <TIcon symbol={t.symbol} size={36} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontFamily: C.D, fontSize: 15, fontWeight: 700, color: C.text }}>{t.symbol}</div>
                        <div style={{ fontFamily: C.M, fontSize: 11, color: C.dim, marginTop: 2 }}>{t.name}</div>
                      </div>
                      <div style={{ textAlign: 'right' as const }}>
                        <div style={{ fontFamily: C.M, fontSize: 13, fontWeight: 600, color: balFmt > 0 ? C.text : C.dim }}>
                          {balFmt > 0 ? balFmt.toFixed(4) : '0'}
                        </div>
                        <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginTop: 1 }}>{t.symbol}</div>
                      </div>
                    </button>
                  )
                })}
            </div>
          </div>
        </div>
      , document.body)}
    </div>
  )
}