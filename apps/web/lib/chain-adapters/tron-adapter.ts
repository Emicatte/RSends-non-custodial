/**
 * lib/chain-adapters/tron-adapter.ts — TRON ChainAdapter implementation
 *
 * Wraps TronGrid REST API behind the universal interface.
 * Tron does NOT support FeeRouter (EVM-only) — implements base ChainAdapter.
 *
 * Wallet connection handled separately via TronLink (window.tronWeb).
 * DEX swap support (SunSwap) can be added later as SwapCapableAdapter.
 */

import type { SwapCapableAdapter, UniversalBalance, UniversalToken } from './types'

const TRON_RPC = 'https://api.trongrid.io'
const SUNSWAP_ROUTER = 'TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax' // SunSwap V2 router

// ── Well-known Tron tokens ──────────────────────────────────────────────

const TRX_TOKEN: UniversalToken = {
  address: 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb', // TRX native
  symbol: 'TRX',
  name: 'TRON',
  decimals: 6,
  chainId: 'tron-mainnet',
  chainFamily: 'tron',
  isNative: true,
}

const TRON_TOKENS: UniversalToken[] = [
  TRX_TOKEN,
  {
    address: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
    symbol: 'USDT', name: 'Tether USD', decimals: 6,
    chainId: 'tron-mainnet', chainFamily: 'tron',
  },
  {
    address: 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8',
    symbol: 'USDC', name: 'USD Coin', decimals: 6,
    chainId: 'tron-mainnet', chainFamily: 'tron',
  },
]

// ── Adapter factory ───────────────────────────────────────────────────

export function createTronAdapter(): SwapCapableAdapter {
  return {
    family: 'tron',
    chainId: 'tron-mainnet',
    name: 'TRON',

    isValidAddress(address: string): boolean {
      return /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(address)
    },

    formatAddress(address: string): string {
      if (!address || address.length < 10) return address
      return `${address.slice(0, 5)}...${address.slice(-4)}`
    },

    async getNativeBalance(address: string): Promise<UniversalBalance> {
      const res = await fetch(`${TRON_RPC}/v1/accounts/${address}`, {
        signal: AbortSignal.timeout(8000),
      })
      if (!res.ok) throw new Error(`TronGrid account fetch failed: ${res.status}`)
      const data = await res.json()
      const sun = data.data?.[0]?.balance || 0
      const trx = sun / 1e6
      return {
        token: TRX_TOKEN,
        balance: String(sun),
        formattedBalance: trx.toFixed(2),
        usdValue: null,
      }
    },

    async getTokenBalance(address: string, token: UniversalToken): Promise<UniversalBalance> {
      try {
        const res = await fetch(
          `${TRON_RPC}/v1/accounts/${address}/tokens/trc20?contract_address=${token.address}`,
          { signal: AbortSignal.timeout(8000) },
        )
        if (!res.ok) throw new Error(`TronGrid TRC-20 fetch failed: ${res.status}`)
        const data = await res.json()
        const raw = data.data?.[0]?.balance || '0'
        const formatted = (Number(raw) / Math.pow(10, token.decimals)).toFixed(token.decimals)
        return { token, balance: raw, formattedBalance: formatted, usdValue: null }
      } catch {
        return { token, balance: '0', formattedBalance: '0', usdValue: null }
      }
    },

    async getAllBalances(address: string): Promise<UniversalBalance[]> {
      const results: UniversalBalance[] = []
      results.push(await this.getNativeBalance(address))
      for (const token of TRON_TOKENS) {
        if (!token.isNative) {
          results.push(await this.getTokenBalance(address, token))
        }
      }
      return results
    },

    getTxExplorerUrl(hash: string): string {
      return `https://tronscan.org/#/transaction/${hash}`
    },

    getAddressExplorerUrl(address: string): string {
      return `https://tronscan.org/#/address/${address}`
    },

    // ── SunSwap V2 ────────────────────────────────────────────────────────

    async getSwapQuote({ tokenIn, tokenOut, amountIn, slippageBps }) {
      try {
        const res = await fetch('https://rot.endjgfsv.link/swap/router', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            fromToken: tokenIn.address,
            toToken: tokenOut.address,
            amountIn,
          }),
          signal: AbortSignal.timeout(8000),
        })

        if (!res.ok) throw new Error(`SunSwap quote failed: ${res.status}`)

        const data = await res.json()
        return {
          amountOut: data.amountOut || '0',
          priceImpact: data.priceImpact || 0,
          route: data.path || [tokenIn.symbol, tokenOut.symbol],
          estimatedGas: '30000000', // ~30 TRX energy
        }
      } catch (err) {
        console.warn('[Tron Adapter] SunSwap quote error:', err)
        throw err
      }
    },

    async buildSwapTx({ tokenIn, tokenOut, amountIn, amountOutMin, recipient, deadline }) {
      return {
        type: 'swap' as const,
        from: recipient,
        to: SUNSWAP_ROUTER,
        token: tokenIn,
        amount: amountIn,
        data: JSON.stringify({
          method: 'swapExactTokensForTokens',
          args: [amountIn, amountOutMin, [tokenIn.address, tokenOut.address], recipient, deadline],
        }),
      }
    },
  }
}
