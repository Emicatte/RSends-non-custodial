/**
 * lib/chain-adapters/solana-adapter.ts — Solana ChainAdapter implementation
 *
 * Wraps @solana/web3.js + Jupiter Aggregator behind the universal interface.
 * Solana does NOT support FeeRouter (EVM-only) — implements SwapCapableAdapter.
 */

import { Connection, PublicKey, clusterApiUrl } from '@solana/web3.js'
import type { SwapCapableAdapter, UniversalBalance, UniversalToken } from './types'

const SOLANA_RPC = process.env.NEXT_PUBLIC_SOLANA_RPC || clusterApiUrl('mainnet-beta')
const JUPITER_API = 'https://quote-api.jup.ag/v6'

// ── Well-known Solana tokens ──────────────────────────────────────────────

const SOL_TOKEN: UniversalToken = {
  address: 'So11111111111111111111111111111111111111112', // Wrapped SOL mint
  symbol: 'SOL',
  name: 'Solana',
  decimals: 9,
  chainId: 'mainnet-beta',
  chainFamily: 'solana',
  isNative: true,
}

const SOLANA_TOKENS: UniversalToken[] = [
  SOL_TOKEN,
  {
    address: 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    chainId: 'mainnet-beta', chainFamily: 'solana',
  },
  {
    address: 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    chainId: 'mainnet-beta', chainFamily: 'solana',
  },
  {
    address: '3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh',
    symbol: 'WBTC', name: 'Wrapped BTC (Wormhole)', decimals: 8,
    chainId: 'mainnet-beta', chainFamily: 'solana',
  },
]

// ── Jupiter quote cache (rate-limit protection) ───────────────────────────

const quoteCache = new Map<string, { data: any; ts: number }>()
const CACHE_TTL_MS = 10_000 // 10s

function getCacheKey(inputMint: string, outputMint: string, amount: string): string {
  return `${inputMint}:${outputMint}:${amount}`
}

async function fetchJupiterQuote(inputMint: string, outputMint: string, amount: string, slippageBps: number) {
  const cacheKey = getCacheKey(inputMint, outputMint, amount)
  const cached = quoteCache.get(cacheKey)
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) return cached.data

  const params = new URLSearchParams({
    inputMint,
    outputMint,
    amount,
    slippageBps: String(slippageBps),
  })

  const res = await fetch(`${JUPITER_API}/quote?${params}`, {
    signal: AbortSignal.timeout(8000),
  })
  if (!res.ok) throw new Error(`Jupiter quote failed: ${res.status}`)
  const data = await res.json()

  quoteCache.set(cacheKey, { data, ts: Date.now() })
  return data
}

// ── Adapter factory ───────────────────────────────────────────────────────

export function createSolanaAdapter(): SwapCapableAdapter {
  const connection = new Connection(SOLANA_RPC, 'confirmed')

  return {
    family: 'solana',
    chainId: 'mainnet-beta',
    name: 'Solana',

    isValidAddress(address: string): boolean {
      try {
        new PublicKey(address)
        return true
      } catch {
        return false
      }
    },

    formatAddress(address: string): string {
      if (!address || address.length < 10) return address
      return `${address.slice(0, 4)}...${address.slice(-4)}`
    },

    async getNativeBalance(address: string): Promise<UniversalBalance> {
      const pubkey = new PublicKey(address)
      const lamports = await connection.getBalance(pubkey)
      const sol = lamports / 1e9
      return {
        token: SOL_TOKEN,
        balance: String(lamports),
        formattedBalance: sol.toFixed(4),
        usdValue: null, // Price fetched separately
      }
    },

    async getTokenBalance(address: string, token: UniversalToken): Promise<UniversalBalance> {
      const pubkey = new PublicKey(address)
      const mint = new PublicKey(token.address)

      try {
        const accounts = await connection.getParsedTokenAccountsByOwner(pubkey, { mint })
        if (accounts.value.length === 0) {
          return { token, balance: '0', formattedBalance: '0', usdValue: null }
        }
        const info = accounts.value[0].account.data.parsed.info
        const amount = info.tokenAmount.amount as string
        const formatted = (info.tokenAmount.uiAmountString as string) || '0'
        return { token, balance: amount, formattedBalance: formatted, usdValue: null }
      } catch {
        return { token, balance: '0', formattedBalance: '0', usdValue: null }
      }
    },

    async getAllBalances(address: string): Promise<UniversalBalance[]> {
      const results: UniversalBalance[] = []
      // Native SOL
      results.push(await this.getNativeBalance(address))
      // SPL tokens
      for (const token of SOLANA_TOKENS) {
        if (!token.isNative) {
          results.push(await this.getTokenBalance(address, token))
        }
      }
      return results
    },

    getTxExplorerUrl(hash: string): string {
      return `https://solscan.io/tx/${hash}`
    },

    getAddressExplorerUrl(address: string): string {
      return `https://solscan.io/account/${address}`
    },

    async getSwapQuote({ tokenIn, tokenOut, amountIn, slippageBps }) {
      const data = await fetchJupiterQuote(tokenIn.address, tokenOut.address, amountIn, slippageBps)

      return {
        amountOut: data.outAmount as string,
        priceImpact: (data.priceImpactPct as number) || 0,
        route: (data.routePlan as any[])?.map((r: any) => r.swapInfo?.label as string) || [],
        estimatedGas: '5000', // Solana compute units, not EVM gas
      }
    },

    async buildSwapTx({ tokenIn, tokenOut, amountIn, amountOutMin: _amountOutMin, recipient }) {
      const quote = await fetchJupiterQuote(tokenIn.address, tokenOut.address, amountIn, 50)

      const swapRes = await fetch(`${JUPITER_API}/swap`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          quoteResponse: quote,
          userPublicKey: recipient,
        }),
        signal: AbortSignal.timeout(8000),
      })
      if (!swapRes.ok) throw new Error(`Jupiter swap failed: ${swapRes.status}`)
      const swap = await swapRes.json()

      return {
        type: 'swap' as const,
        from: recipient,
        to: '',  // Jupiter handles routing internally
        token: tokenIn,
        amount: amountIn,
        data: swap.swapTransaction as string, // Base64 encoded versioned transaction
      }
    },
  }
}
