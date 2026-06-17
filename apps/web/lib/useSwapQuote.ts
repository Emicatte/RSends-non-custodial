
import { useState, useEffect, useRef } from 'react'
import { usePublicClient } from 'wagmi'
import { formatUnits, parseUnits, parseEther, type Abi } from 'viem'
import { getRegistry, type TokenConfig } from './contractRegistry'

// ── QuoterV2 per chain — indirizzi diversi su ogni rete ───────────────────
function getQuoterAddress(chainId: number): `0x${string}` {
  switch (chainId) {
    case 8453:     // Base Mainnet
    case 84532:    // Base Sepolia
      return '0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a'
    case 1:        // Ethereum Mainnet
      return '0x61fFE014bA17989E743c5F6cB21bF9697530B21e'
    default:
      return '0x61fFE014bA17989E743c5F6cB21bF9697530B21e'
  }
}

const QUOTER_V2_ABI: Abi = [
  {
    name: 'quoteExactInputSingle',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      {
        name: 'params',
        type: 'tuple',
        components: [
          { name: 'tokenIn',           type: 'address' },
          { name: 'tokenOut',          type: 'address' },
          { name: 'amountIn',          type: 'uint256' },
          { name: 'fee',               type: 'uint24'  },
          { name: 'sqrtPriceLimitX96', type: 'uint160' },
        ],
      },
    ],
    outputs: [
      { name: 'amountOut',               type: 'uint256' },
      { name: 'sqrtPriceX96After',       type: 'uint160' },
      { name: 'initializedTicksCrossed', type: 'uint32'  },
      { name: 'gasEstimate',             type: 'uint256' },
    ],
  },
]

// Tutti i tier Uniswap V3 — testati in parallelo
const FEE_TIERS = [100, 500, 3000, 10000] as const

export type QuoteStatus =
  | 'idle'
  | 'loading'
  | 'success'
  | 'error_liquidity'
  | 'error_network'
  | 'error_same_token'
  | 'error_amount'

export interface SwapQuote {
  status:        QuoteStatus
  amountOut:     bigint
  amountOutFmt:  string
  netAmountOut:  bigint
  netAmountFmt:  string
  feeAmount:     bigint
  feeFmt:        string
  minAmountOut:  bigint
  poolFee:       number    // tier con il miglior output
  gasEstimate?:  bigint
  errorMessage?: string
}

const DEFAULT_SLIPPAGE_BPS = 50

function calcSplit(amount: bigint, feeBps: number) {
  const fee = (amount * BigInt(feeBps)) / 10_000n
  return { net: amount - fee, fee }
}

function applySlippage(amount: bigint, slippageBps: number): bigint {
  return (amount * BigInt(10_000 - slippageBps)) / 10_000n
}

// Risolve ETH nativo → indirizzo WETH della chain corrente
function resolveAddr(token: TokenConfig, weth: `0x${string}`): `0x${string}` {
  if (token.isNative || token.address === '0x0000000000000000000000000000000000000000') {
    return weth
  }
  return token.address
}

// Risultato di un singolo tentativo di quote su un tier
interface TierResult {
  fee:         number
  amountOut:   bigint
  gasEstimate: bigint
}

export function useSwapQuote({
  chainId,
  tokenIn,
  tokenOut,
  amountIn,
  feeBps = 50,
  slippageBps = DEFAULT_SLIPPAGE_BPS,
  debounceMs = 600,
}: {
  chainId:      number
  tokenIn:      TokenConfig | null
  tokenOut:     TokenConfig | null
  amountIn:     string
  feeBps?:      number
  slippageBps?: number
  debounceMs?:  number
}) {
  const publicClient = usePublicClient({ chainId })
  const [quote, setQuote] = useState<SwapQuote | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // Reset se dati mancanti
    if (!tokenIn || !tokenOut || !amountIn || Number(amountIn) <= 0) {
      setQuote(null); return
    }

    // Stesso token → nessuno swap necessario
    if (tokenIn.address === tokenOut.address) {
      setQuote({
        status: 'error_same_token', amountOut: 0n, amountOutFmt: '0',
        netAmountOut: 0n, netAmountFmt: '0', feeAmount: 0n, feeFmt: '0',
        minAmountOut: 0n, poolFee: 500,
        errorMessage: 'Token di input e output uguali.',
      })
      return
    }

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(async () => {
      setQuote(prev => prev
        ? { ...prev, status: 'loading' }
        : { status: 'loading', amountOut: 0n, amountOutFmt: '…', netAmountOut: 0n, netAmountFmt: '…', feeAmount: 0n, feeFmt: '0', minAmountOut: 0n, poolFee: 500 }
      )

      const registry = getRegistry(chainId)
      if (!registry || !publicClient) {
        setQuote({ status: 'error_network', amountOut: 0n, amountOutFmt: '0', netAmountOut: 0n, netAmountFmt: '0', feeAmount: 0n, feeFmt: '0', minAmountOut: 0n, poolFee: 500, errorMessage: 'Rete non supportata.' })
        return
      }

      // Converti amount → wei
      let amountInWei: bigint
      try {
        amountInWei = tokenIn.isNative ? parseEther(amountIn) : parseUnits(amountIn, tokenIn.decimals)
      } catch {
        setQuote({ status: 'error_amount', amountOut: 0n, amountOutFmt: '0', netAmountOut: 0n, netAmountFmt: '0', feeAmount: 0n, feeFmt: '0', minAmountOut: 0n, poolFee: 500, errorMessage: 'Importo non valido.' })
        return
      }

      // Risolvi ETH → WETH
      const addrIn  = resolveAddr(tokenIn,  registry.weth)
      const addrOut = resolveAddr(tokenOut, registry.weth)

      // Quoter corretto per la chain
      const quoterAddress = getQuoterAddress(chainId)

      // ── Promise.allSettled — testa TUTTI i tier in parallelo ────────────
      const tierErrors: { fee: number; reason: string }[] = []

      const tierPromises = FEE_TIERS.map(async (fee): Promise<TierResult | null> => {
        try {
          const result = await publicClient.simulateContract({
            address:      quoterAddress,
            abi:          QUOTER_V2_ABI,
            functionName: 'quoteExactInputSingle',
            args: [{
              tokenIn:           addrIn,
              tokenOut:          addrOut,
              amountIn:          amountInWei,
              fee,
              sqrtPriceLimitX96: 0n,
            }],
          })

          const [amountOut, , , gasEstimate] = result.result as [bigint, bigint, number, bigint]

          if (amountOut > 0n) {
            return { fee, amountOut, gasEstimate }
          }
          tierErrors.push({ fee, reason: 'amountOut = 0 (pool vuota)' })
          return null
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          // Classifica l'errore
          let reason = 'sconosciuto'
          if (msg.includes('NP') || msg.includes('No pool'))           reason = 'pool non esiste'
          else if (msg.includes('SPL') || msg.includes('price'))       reason = 'price limit'
          else if (msg.includes('IIA') || msg.includes('amount'))      reason = 'importo insufficiente per la pool'
          else if (msg.includes('execution reverted'))                 reason = 'revert (pool inesistente o senza liquidità)'
          else                                                         reason = msg.slice(0, 80)
          tierErrors.push({ fee, reason })
          return null
        }
      })

      const settled = await Promise.allSettled(tierPromises)

      // Raccogli tutti i risultati validi
      const validResults: TierResult[] = settled
        .filter((r): r is PromiseFulfilledResult<TierResult | null> =>
          r.status === 'fulfilled' && r.value !== null
        )
        .map(r => r.value!)

      // ── Log dettagliato di ogni tier ───────────────────────────────────
      console.log(`[useSwapQuote] ${tokenIn.symbol}→${tokenOut.symbol} on chain ${chainId}`)
      console.log(`  Quoter: ${quoterAddress}`)
      console.log(`  addrIn: ${addrIn} | addrOut: ${addrOut}`)
      console.log(`  amountIn: ${amountInWei.toString()} (${amountIn} ${tokenIn.symbol})`)
      console.log(`  Risultati: ${validResults.length}/${FEE_TIERS.length} tier OK`)
      for (const t of validResults) {
        console.log(`    ✅ tier ${t.fee}: amountOut=${formatUnits(t.amountOut, tokenOut.decimals)}`)
      }
      for (const e of tierErrors) {
        console.log(`    ❌ tier ${e.fee}: ${e.reason}`)
      }

      // ── Nessun tier ha risposto → error_liquidity ──────────────────────
      if (validResults.length === 0) {
        // Determina se il problema è "pool non esiste" vs "liquidità insufficiente"
        const allPoolMissing = tierErrors.every(e =>
          e.reason.includes('non esiste') || e.reason.includes('revert')
        )

        const errorMessage = allPoolMissing
          ? `Nessuna pool Uniswap V3 esiste per ${tokenIn.symbol}/${tokenOut.symbol} su questa rete. Prova a scambiare con USDC o EURC che hanno le pool più liquide.`
          : `Liquidità insufficiente per ${tokenIn.symbol}/${tokenOut.symbol}. Riduci l'importo o prova USDC come token di destinazione.`

        setQuote({
          status: 'error_liquidity',
          amountOut: 0n, amountOutFmt: '0',
          netAmountOut: 0n, netAmountFmt: '0',
          feeAmount: 0n, feeFmt: '0',
          minAmountOut: 0n,
          poolFee: 500,
          errorMessage,
        })
        return
      }

      const best = validResults.reduce((a, b) => a.amountOut > b.amountOut ? a : b)
      console.log(`  → Best tier: ${best.fee} → ${formatUnits(best.amountOut, tokenOut.decimals)} ${tokenOut.symbol}`)

      const { net, fee: gatewayFee } = calcSplit(best.amountOut, feeBps)
      const minAmountOut = applySlippage(net, slippageBps)
      const dec = tokenOut.decimals

      setQuote({
        status:       'success',
        amountOut:    best.amountOut,
        amountOutFmt: parseFloat(formatUnits(best.amountOut, dec)).toFixed(dec > 8 ? 6 : dec),
        netAmountOut: net,
        netAmountFmt: parseFloat(formatUnits(net, dec)).toFixed(dec > 8 ? 6 : dec),
        feeAmount:    gatewayFee,
        feeFmt:       parseFloat(formatUnits(gatewayFee, dec)).toFixed(dec > 8 ? 8 : dec),
        minAmountOut,
        poolFee:      best.fee,       // tier con miglior output → usato da writeContract
        gasEstimate:  best.gasEstimate,
      })

    }, debounceMs)

    return () => { if (timerRef.current) clearTimeout(timerRef.current) }

  }, [chainId, tokenIn?.address, tokenOut?.address, amountIn, feeBps, slippageBps])

  return quote
}

// ── Direct transfer quote (nessuno swap) ──────────────────────────────────
export function useDirectQuote(amount: string, decimals: number, feeBps = 50) {
  if (!amount || Number(amount) <= 0) return null
  try {
    const raw = parseUnits(amount, decimals)
    const fee = (raw * BigInt(feeBps)) / 10_000n
    const net = raw - fee
    return {
      raw, net, fee,
      netFmt: parseFloat(formatUnits(net, decimals)).toFixed(6),
      feeFmt: parseFloat(formatUnits(fee, decimals)).toFixed(8),
    }
  } catch { return null }
}