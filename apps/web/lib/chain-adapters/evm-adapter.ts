/**
 * lib/chain-adapters/evm-adapter.ts — EVM ChainAdapter implementation
 *
 * Wraps existing wagmi/viem logic behind the universal ChainAdapter interface.
 * Delegates to existing functions from contractRegistry, addresses, and chains config.
 */

import { createPublicClient, http, type PublicClient, type Abi } from 'viem'
import type {
  FeeRouterCapableAdapter,
  UniversalBalance,
  UniversalToken,
} from './types'
import { getChain } from '../../src/config/chains'
import { CONTRACT_ADDRESSES } from '../../src/constants/addresses'
import type { SupportedChainId } from '../../src/types/chain'
import { isFeeRouterAvailable, getFeeRouterAddress } from '../contractRegistry'

// ── Cached public clients (one per chain) ─────────────────────────────────

const clientCache = new Map<number, PublicClient>()

function getPublicClient(chainId: number): PublicClient {
  const cached = clientCache.get(chainId)
  if (cached) return cached

  const chain = getChain(chainId)
  if (!chain) throw new Error(`Chain ${chainId} not configured`)

  const client = createPublicClient({
    transport: http(chain.rpcUrls.default),
  })
  clientCache.set(chainId, client)
  return client
}

// ── ERC-20 balanceOf ABI (minimal) ────────────────────────────────────────

const ERC20_BALANCE_ABI = [
  {
    name: 'balanceOf',
    type: 'function',
    stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }],
    outputs: [{ name: '', type: 'uint256' }],
  },
] as const

// ── QuoterV2 ABI (from useSwapQuote.ts) ───────────────────────────────────

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

const FEE_TIERS = [100, 500, 3000, 10000] as const

// ── Adapter factory ───────────────────────────────────────────────────────

export function createEVMAdapter(chainId: number): FeeRouterCapableAdapter {
  const chain = getChain(chainId)
  if (!chain) throw new Error(`Unsupported EVM chain: ${chainId}`)

  const contracts = CONTRACT_ADDRESSES[chainId as SupportedChainId]

  return {
    family: 'evm',
    chainId,
    name: chain.name,

    isValidAddress(address: string): boolean {
      return /^0x[0-9a-fA-F]{40}$/.test(address)
    },

    formatAddress(address: string): string {
      if (!address || address.length < 12) return address
      return `${address.slice(0, 6)}...${address.slice(-4)}`
    },

    // ── TODO 1: getNativeBalance ────────────────────────────────────────

    async getNativeBalance(address: string): Promise<UniversalBalance> {
      const client = getPublicClient(chainId)
      const balance = await client.getBalance({
        address: address as `0x${string}`,
      })

      const native = chain.nativeCurrency
      const formatted = (Number(balance) / Math.pow(10, native.decimals)).toFixed(6)

      return {
        token: {
          address: '0x0000000000000000000000000000000000000000',
          symbol: native.symbol,
          name: native.name,
          decimals: native.decimals,
          chainId,
          chainFamily: 'evm',
          isNative: true,
        },
        balance: balance.toString(),
        formattedBalance: formatted,
        usdValue: null,
      }
    },

    // ── TODO 2: getTokenBalance ─────────────────────────────────────────

    async getTokenBalance(address: string, token: UniversalToken): Promise<UniversalBalance> {
      const client = getPublicClient(chainId)

      try {
        const balance = await client.readContract({
          address: token.address as `0x${string}`,
          abi: ERC20_BALANCE_ABI,
          functionName: 'balanceOf',
          args: [address as `0x${string}`],
        }) as bigint

        const formatted = (Number(balance) / Math.pow(10, token.decimals)).toFixed(
          token.decimals <= 8 ? token.decimals : 6
        )

        return {
          token,
          balance: balance.toString(),
          formattedBalance: formatted,
          usdValue: null,
        }
      } catch (err) {
        console.warn(`[EVM Adapter] Failed to read balance for ${token.symbol} on chain ${chainId}:`, err)
        return { token, balance: '0', formattedBalance: '0', usdValue: null }
      }
    },

    // ── TODO 3: getAllBalances ───────────────────────────────────────────

    async getAllBalances(address: string): Promise<UniversalBalance[]> {
      const results: UniversalBalance[] = []

      // 1. Native balance
      results.push(await this.getNativeBalance(address))

      // 2. Known tokens from CONTRACT_ADDRESSES (WETH + WBTC if available)
      if (!contracts) return results

      const knownTokens: { address: string; symbol: string; name: string; decimals: number }[] = []

      if (contracts.weth) {
        knownTokens.push({
          address: contracts.weth,
          symbol: `W${chain.nativeCurrency.symbol}`,
          name: `Wrapped ${chain.nativeCurrency.name}`,
          decimals: 18,
        })
      }
      if (contracts.wbtc) {
        knownTokens.push({
          address: contracts.wbtc,
          symbol: 'WBTC', name: 'Wrapped BTC', decimals: 8,
        })
      }

      // Fetch in parallel with per-token error handling
      const tokenBalances = await Promise.allSettled(
        knownTokens.map(t =>
          this.getTokenBalance(address, {
            ...t,
            chainId,
            chainFamily: 'evm',
          } as UniversalToken)
        )
      )

      for (const result of tokenBalances) {
        if (result.status === 'fulfilled') {
          results.push(result.value)
        }
      }

      return results
    },

    getTxExplorerUrl(hash: string): string {
      const explorer = chain.blockExplorers?.[0]?.url ?? 'https://etherscan.io'
      return `${explorer}/tx/${hash}`
    },

    getAddressExplorerUrl(address: string): string {
      const explorer = chain.blockExplorers?.[0]?.url ?? 'https://etherscan.io'
      return `${explorer}/address/${address}`
    },

    // ── TODO 4: getSwapQuote ────────────────────────────────────────────

    async getSwapQuote({ tokenIn, tokenOut, amountIn, slippageBps }) {
      const client = getPublicClient(chainId)
      if (!contracts) throw new Error(`No Uniswap V3 contracts on chain ${chainId}`)

      // Resolve native → WETH (same pattern as useSwapQuote.ts resolveAddr)
      const weth = contracts.weth as `0x${string}`
      const addrIn = (tokenIn.isNative || tokenIn.address === '0x0000000000000000000000000000000000000000')
        ? weth : tokenIn.address as `0x${string}`
      const addrOut = (tokenOut.isNative || tokenOut.address === '0x0000000000000000000000000000000000000000')
        ? weth : tokenOut.address as `0x${string}`

      // Parallel quotes across all fee tiers (mirrors useSwapQuote.ts)
      const tierPromises = FEE_TIERS.map(async (fee) => {
        try {
          const result = await client.simulateContract({
            address: contracts.uniswapV3Quoter as `0x${string}`,
            abi: QUOTER_V2_ABI,
            functionName: 'quoteExactInputSingle',
            args: [{
              tokenIn: addrIn,
              tokenOut: addrOut,
              amountIn: BigInt(amountIn),
              fee,
              sqrtPriceLimitX96: 0n,
            }],
          })
          const [amountOut, , , gasEstimate] = result.result as [bigint, bigint, number, bigint]
          if (amountOut > 0n) return { fee, amountOut, gasEstimate }
          return null
        } catch {
          return null
        }
      })

      const settled = await Promise.allSettled(tierPromises)
      const validResults = settled
        .filter((r): r is PromiseFulfilledResult<{ fee: typeof FEE_TIERS[number]; amountOut: bigint; gasEstimate: bigint }> =>
          r.status === 'fulfilled' && r.value !== null
        )
        .map(r => r.value!)

      if (validResults.length === 0) throw new Error('No liquidity found for this pair')

      const best = validResults.reduce((a, b) => a.amountOut > b.amountOut ? a : b)

      return {
        amountOut: best.amountOut.toString(),
        priceImpact: 0,
        route: [tokenIn.symbol, tokenOut.symbol],
        estimatedGas: best.gasEstimate.toString(),
      }
    },

    // ── TODO 5a: buildSwapTx ────────────────────────────────────────────

    async buildSwapTx({ tokenIn, tokenOut, amountIn, amountOutMin, recipient, deadline }) {
      if (!contracts) throw new Error(`No Uniswap V3 on chain ${chainId}`)

      return {
        type: 'swap' as const,
        from: recipient,
        to: contracts.uniswapV3Router,
        token: tokenIn,
        amount: amountIn,
        data: JSON.stringify({
          functionName: 'exactInputSingle',
          args: {
            tokenIn: tokenIn.address,
            tokenOut: tokenOut.address,
            fee: 3000,
            recipient,
            deadline: BigInt(deadline).toString(),
            amountIn,
            amountOutMinimum: amountOutMin,
            sqrtPriceLimitX96: '0',
          },
        }),
      }
    },

    // ── TODO 5b: buildFeeRouterTx ───────────────────────────────────────

    async buildFeeRouterTx({ recipient, token, amount, oracleSignature, deadline, nonce }) {
      if (!isFeeRouterAvailable(chainId)) {
        throw new Error(`FeeRouter not deployed on chain ${chainId}`)
      }
      const feeRouterAddr = getFeeRouterAddress(chainId)!

      // Pattern from TransferForm.tsx execDirect (lines 591-618)
      const isNative = token.isNative || token.address === '0x0000000000000000000000000000000000000000'
      const functionName = isNative ? 'transferETHWithOracle' : 'transferWithOracle'

      return {
        type: 'transfer' as const,
        from: '',
        to: feeRouterAddr,
        token,
        amount,
        data: JSON.stringify({
          functionName,
          args: isNative
            ? [recipient, nonce, deadline, oracleSignature]
            : [token.address, amount, recipient, nonce, deadline, oracleSignature],
          value: isNative ? amount : undefined,
        }),
      }
    },
  }
}
