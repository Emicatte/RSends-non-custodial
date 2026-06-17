'use client'

import { useMemo } from 'react'
import { useBalance, useReadContracts } from 'wagmi'
import { erc20Abi, formatUnits } from 'viem'
import { getTokensForChain, type TokenInfo } from '../tokens/tokenRegistry'
import { useTokenPrices } from './useTokenPrices'

export interface TokenBalance {
  token: TokenInfo
  balance: bigint
  formatted: string       // "1,200.50"
  eurValue: number | null // 1200.50
}

/**
 * Fetcha i balance di tutti i token supportati per una chain.
 * Usa multicall di wagmi per efficienza (1 RPC call per tutti i balance ERC-20).
 */
export function useMultiTokenBalances(chainId: number, address?: `0x${string}`) {
  const tokens = useMemo(() => getTokensForChain(chainId), [chainId])
  const nativeToken = useMemo(() => tokens.find(t => t.isNative), [tokens])
  const erc20Tokens = useMemo(() => tokens.filter(t => !t.isNative), [tokens])

  const { prices, isLoading: pricesLoading } = useTokenPrices()

  // Native ETH balance
  const {
    data: nativeData,
    isLoading: nativeLoading,
  } = useBalance({
    address,
    chainId,
    query: { enabled: !!address },
  })

  // ERC-20 balances via multicall (single RPC call)
  const {
    data: erc20Data,
    isLoading: erc20Loading,
  } = useReadContracts({
    contracts: erc20Tokens.map(t => ({
      address: t.address as `0x${string}`,
      abi: erc20Abi,
      functionName: 'balanceOf' as const,
      args: address ? [address] : undefined,
      chainId,
    })),
    query: { enabled: !!address && erc20Tokens.length > 0 },
  })

  const balances: TokenBalance[] = useMemo(() => {
    const result: TokenBalance[] = []

    // Native token
    if (nativeToken) {
      const bal = nativeData?.value ?? 0n
      const fmtRaw = parseFloat(formatUnits(bal, nativeToken.decimals))
      const price = prices[nativeToken.coingeckoId]?.eur ?? null
      result.push({
        token: nativeToken,
        balance: bal,
        formatted: fmtToken(fmtRaw, nativeToken.symbol),
        eurValue: price !== null ? fmtRaw * price : null,
      })
    }

    // ERC-20 tokens
    erc20Tokens.forEach((token, i) => {
      const raw = erc20Data?.[i]
      const bal = (raw?.status === 'success' ? (raw.result as bigint) : 0n)
      const fmtRaw = parseFloat(formatUnits(bal, token.decimals))
      const price = prices[token.coingeckoId]?.eur ?? null
      result.push({
        token,
        balance: bal,
        formatted: fmtToken(fmtRaw, token.symbol),
        eurValue: price !== null ? fmtRaw * price : null,
      })
    })

    return result
  }, [nativeToken, nativeData, erc20Tokens, erc20Data, prices])

  const totalEur = useMemo(() => {
    let sum = 0
    let allNull = true
    for (const b of balances) {
      if (b.eurValue !== null) {
        sum += b.eurValue
        allNull = false
      }
    }
    return allNull ? null : sum
  }, [balances])

  const isLoading = nativeLoading || erc20Loading || pricesLoading

  return { balances, totalEur, isLoading }
}

// ── Formatting helper ──────────────────────────────────────────────────
function fmtToken(value: number, symbol: string): string {
  if (['USDC', 'USDT', 'DAI', 'EURC'].includes(symbol)) {
    return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  if (['cbBTC', 'WBTC'].includes(symbol)) {
    return value.toLocaleString('en-US', { minimumFractionDigits: 6, maximumFractionDigits: 6 })
  }
  return value.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 })
}
