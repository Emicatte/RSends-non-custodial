// @ts-nocheck — archived reference code, excluded from the build (tsconfig "exclude");
// kept only for future reuse. The IDE type-checks open files regardless of the exclude.
'use client'

import { useState, useEffect, useCallback } from 'react'
import { useAccount, useChainId, usePublicClient, useWalletClient } from 'wagmi'
import { parseUnits, formatUnits, encodeFunctionData, type Hex } from 'viem'
import { CCIP_CHAINS, getCCIPConfig, isCCIPAvailable, getCCIPChainSelector, CCIP_SUPPORTED_TOKENS, type CCIPChainConfig } from '@/lib/ccipRegistry'
import { C } from '@/app/designTokens'
import FeatureDisabled from '@/components/FeatureDisabled'

// ── ABI ──────────────────────────────────────────────────────────────────
const CCIP_SENDER_ABI = [
  {
    name: 'swapAndBridge',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'tokenIn', type: 'address' },
      { name: 'tokenOut', type: 'address' },
      { name: 'amountIn', type: 'uint256' },
      { name: 'minAmountOut', type: 'uint256' },
      { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
    ],
    outputs: [],
  },
  {
    name: 'swapETHAndBridge',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'tokenOut', type: 'address' },
      { name: 'amountIn', type: 'uint256' },
      { name: 'minAmountOut', type: 'uint256' },
      { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
    ],
    outputs: [],
  },
  {
    name: 'sendCrossChain',
    type: 'function',
    stateMutability: 'payable',
    inputs: [
      { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [],
  },
  {
    name: 'estimateSwapAndBridgeFee',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'tokenOut', type: 'address' },
      { name: 'netAmountOut', type: 'uint256' },
      { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
    ],
    outputs: [{ name: 'ccipFee', type: 'uint256' }],
  },
  {
    name: 'estimateFee',
    type: 'function',
    stateMutability: 'view',
    inputs: [
      { name: 'destinationChainSelector', type: 'uint64' },
      { name: 'recipient', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'netAmount', type: 'uint256' },
    ],
    outputs: [{ name: 'ccipFee', type: 'uint256' }],
  },
] as const

type BridgeMode = 'bridge' | 'swapBridge'
type BridgeStatus = 'idle' | 'checking' | 'approving' | 'sending' | 'pending' | 'success' | 'error'

// Token list with addresses per chain (subset for CCIP)
const TOKEN_ADDRESSES: Record<number, Record<string, `0x${string}`>> = {
  8453: {
    USDC: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    LINK: '0x88Fb150BDc53A65fe94Dea0c9BA0a6dAf8C6e196',
    WETH: '0x4200000000000000000000000000000000000006',
    ETH:  '0x0000000000000000000000000000000000000000',
  },
  1: {
    USDC: '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
    USDT: '0xdAC17F958D2ee523a2206206994597C13D831ec7',
    LINK: '0x514910771AF9Ca656af840dff83E8264EcF986CA',
    WETH: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    WBTC: '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
    ETH:  '0x0000000000000000000000000000000000000000',
  },
  42161: {
    USDC: '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    LINK: '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4',
    WETH: '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
    WBTC: '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',
    ETH:  '0x0000000000000000000000000000000000000000',
  },
  10: {
    USDC: '0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85',
    LINK: '0x350a791Bfc2C21F9Ed5d10980Dad2e2638ffa7f6',
    WETH: '0x4200000000000000000000000000000000000006',
    ETH:  '0x0000000000000000000000000000000000000000',
  },
  137: {
    USDC: '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359',
    LINK: '0xb0897686c545045aFc77CF20eC7A532E3120E0F1',
  },
  56: {
    USDC: '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
    LINK: '0x404460C6A5EdE2D891e8297795264fDe62ADBB75',
  },
  43114: {
    USDC: '0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E',
    LINK: '0x5947BB275c521040051D82396192181b413227A3',
  },
}

interface Props {
  noCard?: boolean
}

export default function CrossChainForm({ noCard }: Props) {
  // Feature flag: cross-chain UI is hidden until CCIP contract calls
  // are fully wired and tested end-to-end. Toggle via
  // NEXT_PUBLIC_FEATURE_CROSSCHAIN=true. Early-return is safe before
  // hooks because the value is a build-time constant.
  if (process.env.NEXT_PUBLIC_FEATURE_CROSSCHAIN !== 'true') {
    return <FeatureDisabled message="Cross-chain transfers coming soon." />
  }

  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const publicClient = usePublicClient()
  const { data: walletClient } = useWalletClient()

  const [mode, setMode] = useState<BridgeMode>('bridge')
  const [destChainId, setDestChainId] = useState<number>(0)
  const [recipient, setRecipient] = useState('')
  const [tokenInSymbol, setTokenInSymbol] = useState('ETH')
  const [tokenOutSymbol, setTokenOutSymbol] = useState('USDC')
  const [tokenSymbol, setTokenSymbol] = useState('USDC') // for bridge mode
  const [amount, setAmount] = useState('')
  const [minAmountOut, setMinAmountOut] = useState('')
  const [ccipFeeEstimate, setCcipFeeEstimate] = useState<string>('')
  const [status, setStatus] = useState<BridgeStatus>('idle')
  const [txHash, setTxHash] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  // Available destination chains (exclude current)
  const destChains = (Object.values(CCIP_CHAINS) as CCIPChainConfig[]).filter(c => c.chainId !== chainId)

  // Available tokens for current chain
  const availableTokens = CCIP_SUPPORTED_TOKENS[chainId] ?? []
  const allTokens = [...availableTokens, 'ETH']

  // Source chain config
  const sourceConfig = getCCIPConfig(chainId)

  // ── Estimate CCIP fee ───────────────────────────────────────────────────
  const estimateFee = useCallback(async () => {
    if (!sourceConfig || !destChainId || !amount || !recipient || !publicClient) return
    const destConfig = getCCIPConfig(destChainId)
    if (!destConfig) return
    if (sourceConfig.senderContract === '0x0000000000000000000000000000000000000000') {
      setCcipFeeEstimate('Contracts not deployed')
      return
    }

    try {
      setCcipFeeEstimate('~0.001 ETH')
    } catch {
      setCcipFeeEstimate('Unable to estimate')
    }
  }, [sourceConfig, destChainId, amount, recipient, publicClient])

  useEffect(() => {
    const t = setTimeout(estimateFee, 500)
    return () => clearTimeout(t)
  }, [estimateFee])

  // ── Send cross-chain (bridge mode) ──────────────────────────────────────
  const handleBridge = async () => {
    if (!walletClient || !address || !sourceConfig || !destChainId) return

    setStatus('checking')
    setErrorMsg('')

    try {
      // 1. AML check
      const checkRes = await fetch('/api/oracle/check-crosschain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: address,
          recipient,
          token: mode === 'bridge' ? tokenSymbol : tokenOutSymbol,
          amount,
          sourceChainId: chainId,
          destChainId,
        }),
      })
      const checkData = await checkRes.json()
      if (!checkData.approved) {
        setStatus('error')
        setErrorMsg('Transaction blocked by compliance check')
        return
      }

      setStatus('sending')

      // Check if contracts are deployed
      if (sourceConfig.senderContract === '0x0000000000000000000000000000000000000000') {
        setStatus('error')
        setErrorMsg('Bridge contracts not yet deployed. Update ccipRegistry.ts with deployed addresses.')
        return
      }

      // TODO: Wire up actual contract calls after deploy:
      // - Bridge mode: approve token → sendCrossChain()
      // - Swap & Bridge (ERC20): approve tokenIn → swapAndBridge()
      // - Swap & Bridge (ETH): swapETHAndBridge() with msg.value = amountIn + ccipFee

      setStatus('error')
      setErrorMsg('Bridge contracts not yet deployed. Update ccipRegistry.ts with deployed addresses.')

    } catch (err: unknown) {
      setStatus('error')
      setErrorMsg(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────
  const containerStyle: React.CSSProperties = noCard
    ? { padding: '20px 16px' }
    : {
        background: 'rgba(8,12,30,0.72)',
        border: `1px solid ${C.border}`,
        borderRadius: 20,
        padding: '20px 16px',
      }

  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '12px 14px',
    borderRadius: 12,
    border: `1px solid rgba(10,10,10,0.1)`,
    background: 'rgba(10,10,10,0.04)',
    color: C.text,
    fontFamily: C.M,
    fontSize: 14,
    outline: 'none',
  }

  const selectStyle: React.CSSProperties = {
    ...inputStyle,
    cursor: 'pointer',
    appearance: 'none' as const,
  }

  const labelStyle: React.CSSProperties = {
    fontFamily: C.D,
    fontSize: 11,
    fontWeight: 700,
    color: C.sub,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
    marginBottom: 6,
    display: 'block',
  }

  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: '8px 0',
    borderRadius: 10,
    border: 'none',
    background: active ? 'rgba(59,130,246,0.15)' : 'transparent',
    color: active ? C.blue : C.dim,
    fontFamily: C.D,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'all 0.2s ease',
  })

  if (!isConnected) {
    return (
      <div style={containerStyle}>
        <p style={{ color: C.sub, fontFamily: C.D, fontSize: 14, textAlign: 'center', padding: 40 }}>
          Connect wallet to bridge tokens cross-chain
        </p>
      </div>
    )
  }

  const isSwapMode = mode === 'swapBridge'
  const isReady = isSwapMode
    ? (destChainId && recipient && amount && tokenInSymbol && tokenOutSymbol && tokenInSymbol !== tokenOutSymbol)
    : (destChainId && recipient && amount && tokenSymbol)

  return (
    <div style={containerStyle}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <h3 style={{
          fontFamily: C.D, fontSize: 16, fontWeight: 700, color: C.text,
          margin: 0, marginBottom: 4,
        }}>
          Cross-Chain Transfer
        </h3>
        <p style={{ fontFamily: C.M, fontSize: 11, color: C.dim, margin: 0 }}>
          Powered by Chainlink CCIP
        </p>
      </div>

      {/* Mode tabs */}
      <div style={{
        display: 'flex', gap: 4, padding: 3,
        borderRadius: 12,
        background: 'rgba(10,10,10,0.03)',
        marginBottom: 16,
      }}>
        <button style={tabStyle(mode === 'bridge')} onClick={() => setMode('bridge')}>
          Bridge
        </button>
        <button style={tabStyle(mode === 'swapBridge')} onClick={() => setMode('swapBridge')}>
          Swap & Bridge
        </button>
      </div>

      {/* Source chain (read-only) */}
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>From</label>
        <div style={{ ...inputStyle, opacity: 0.6 }}>
          {sourceConfig?.chainName ?? `Chain ${chainId}`}
        </div>
      </div>

      {/* Destination chain */}
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>To</label>
        <select
          value={destChainId}
          onChange={e => setDestChainId(Number(e.target.value))}
          style={selectStyle}
        >
          <option value={0}>Select destination chain</option>
          {destChains.map(c => (
            <option key={c.chainId} value={c.chainId}>{c.chainName}</option>
          ))}
        </select>
      </div>

      {/* Token selection */}
      {isSwapMode ? (
        /* Swap & Bridge: tokenIn + tokenOut */
        <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Token In</label>
            <select
              value={tokenInSymbol}
              onChange={e => setTokenInSymbol(e.target.value)}
              style={selectStyle}
            >
              {allTokens.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div style={{
            display: 'flex', alignItems: 'flex-end', paddingBottom: 8,
            color: C.dim, fontFamily: C.D, fontSize: 18,
          }}>
            &rarr;
          </div>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Token Out</label>
            <select
              value={tokenOutSymbol}
              onChange={e => setTokenOutSymbol(e.target.value)}
              style={selectStyle}
            >
              {availableTokens.filter(t => t !== tokenInSymbol).map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        </div>
      ) : (
        /* Bridge: single token */
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Token</label>
          <select
            value={tokenSymbol}
            onChange={e => setTokenSymbol(e.target.value)}
            style={selectStyle}
          >
            {availableTokens.length === 0 && (
              <option value="">No CCIP tokens on this chain</option>
            )}
            {availableTokens.map(t => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      )}

      {/* Amount */}
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>
          {isSwapMode ? `Amount (${tokenInSymbol})` : 'Amount'}
        </label>
        <input
          type="text"
          placeholder="0.00"
          value={amount}
          onChange={e => setAmount(e.target.value)}
          style={inputStyle}
        />
      </div>

      {/* Min amount out (swap mode only) */}
      {isSwapMode && (
        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>Min Amount Out ({tokenOutSymbol})</label>
          <input
            type="text"
            placeholder="Slippage protection"
            value={minAmountOut}
            onChange={e => setMinAmountOut(e.target.value)}
            style={inputStyle}
          />
        </div>
      )}

      {/* Recipient */}
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>Recipient</label>
        <input
          type="text"
          placeholder="0x..."
          value={recipient}
          onChange={e => setRecipient(e.target.value)}
          style={inputStyle}
        />
      </div>

      {/* Quote / Fee estimate */}
      {ccipFeeEstimate && amount && (() => {
        const amtNum = parseFloat(amount) || 0
        const destChainName = destChainId
          ? (Object.values(CCIP_CHAINS) as CCIPChainConfig[]).find(c => c.chainId === destChainId)?.chainName ?? ''
          : ''

        // Swap estimate calculations (placeholder until Quoter wired)
        let estSwapOut = 0
        if (isSwapMode && amtNum > 0) {
          if (tokenInSymbol === 'ETH' || tokenInSymbol === 'WETH') {
            estSwapOut = amtNum * 2200
          } else if (tokenOutSymbol === 'ETH' || tokenOutSymbol === 'WETH') {
            estSwapOut = amtNum / 2200
          } else {
            estSwapOut = amtNum // stablecoin-to-stablecoin ~1:1
          }
        }

        // Fee calculations
        const grossAmount = isSwapMode ? estSwapOut : amtNum
        const rsendFee = grossAmount * 0.005
        const netBridged = grossAmount - rsendFee
        const outToken = isSwapMode ? tokenOutSymbol : tokenSymbol

        const row = (label: string, value: string, color: string, bold = false): React.ReactNode => (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
            <span style={{ fontFamily: C.D, fontSize: 11, color: C.sub, fontWeight: bold ? 600 : 400 }}>{label}</span>
            <span style={{ fontFamily: C.M, fontSize: 12, color, fontWeight: bold ? 600 : 400 }}>{value}</span>
          </div>
        )

        return (
          <div style={{
            padding: '14px 16px',
            borderRadius: 12,
            background: isSwapMode ? 'rgba(139,92,246,0.06)' : 'rgba(59,130,246,0.06)',
            border: `1px solid ${isSwapMode ? 'rgba(139,92,246,0.15)' : 'rgba(59,130,246,0.15)'}`,
            marginBottom: 14,
          }}>
            {/* Title */}
            <div style={{
              fontFamily: C.D, fontSize: 10, fontWeight: 700, color: C.dim,
              letterSpacing: '0.08em', textTransform: 'uppercase' as const,
              marginBottom: 10,
            }}>
              Quote
            </div>

            {/* Swap line (swap mode only) */}
            {isSwapMode && amtNum > 0 && row(
              'Swap',
              `${amtNum} ${tokenInSymbol} → ~${estSwapOut.toFixed(2)} ${tokenOutSymbol}`,
              C.purple
            )}

            {/* RSends fee */}
            {row(
              'RSends fee',
              `${rsendFee.toFixed(rsendFee < 0.01 ? 6 : 2)} ${outToken} (0.5%)`,
              C.sub
            )}

            {/* Net bridged */}
            {row(
              'Net bridged',
              `${netBridged.toFixed(netBridged < 0.01 ? 6 : 2)} ${outToken}`,
              C.text
            )}

            {/* CCIP fee */}
            {row('CCIP fee', ccipFeeEstimate, C.blue)}

            {/* Delivery */}
            {row('Delivery', '~2-5 minutes', C.green)}

            {/* Separator + Recipient receives */}
            <div style={{
              marginTop: 8, paddingTop: 8,
              borderTop: '1px solid rgba(10,10,10,0.08)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{ fontFamily: C.D, fontSize: 11, color: C.text, fontWeight: 700 }}>
                Recipient receives
              </span>
              <span style={{ fontFamily: C.M, fontSize: 13, color: C.green, fontWeight: 700 }}>
                ~{netBridged.toFixed(netBridged < 0.01 ? 6 : 2)} {outToken}
                {destChainName ? ` on ${destChainName}` : ''}
              </span>
            </div>
          </div>
        )
      })()}

      {/* Status */}
      {status === 'error' && (
        <div style={{
          padding: '10px 14px',
          borderRadius: 10,
          background: 'rgba(255,76,106,0.08)',
          border: '1px solid rgba(255,76,106,0.2)',
          marginBottom: 14,
        }}>
          <span style={{ fontFamily: C.M, fontSize: 11, color: C.red }}>{errorMsg}</span>
        </div>
      )}

      {status === 'success' && txHash && (
        <div style={{
          padding: '10px 14px',
          borderRadius: 10,
          background: 'rgba(0,214,143,0.08)',
          border: '1px solid rgba(0,214,143,0.2)',
          marginBottom: 14,
        }}>
          <span style={{ fontFamily: C.M, fontSize: 11, color: C.green }}>
            {isSwapMode ? 'Swap & Bridge initiated!' : 'Bridge initiated!'} Track on CCIP Explorer
          </span>
        </div>
      )}

      {/* Action button */}
      <button
        onClick={handleBridge}
        disabled={
          !isReady ||
          status === 'checking' || status === 'approving' || status === 'sending'
        }
        style={{
          width: '100%',
          padding: '14px 0',
          borderRadius: 14,
          border: 'none',
          background: !isReady
            ? 'rgba(10,10,10,0.08)'
            : isSwapMode
              ? 'linear-gradient(135deg, #C8512C 0%, #3B82F6 100%)'
              : 'linear-gradient(135deg, #3B82F6 0%, #C8512C 100%)',
          color: !isReady ? C.dim : '#fff',
          fontFamily: C.D,
          fontSize: 15,
          fontWeight: 700,
          cursor: !isReady ? 'not-allowed' : 'pointer',
          transition: 'all 0.2s ease',
        }}
      >
        {status === 'checking' ? 'Checking compliance...'
          : status === 'approving' ? 'Approving token...'
          : status === 'sending' ? (isSwapMode ? 'Swapping & Bridging...' : 'Bridging...')
          : status === 'pending' ? 'CCIP in transit...'
          : isSwapMode ? 'Swap & Bridge' : 'Bridge & Send'}
      </button>

      {/* Info */}
      <p style={{
        fontFamily: C.M, fontSize: 10, color: C.dim,
        textAlign: 'center', margin: '12px 0 0',
      }}>
        {isSwapMode
          ? 'Atomic swap + cross-chain bridge in 1 transaction via Uniswap V3 + Chainlink CCIP'
          : 'Cross-chain transfers typically take 5-20 minutes via Chainlink CCIP'}
      </p>
    </div>
  )
}
