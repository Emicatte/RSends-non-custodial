'use client'

import { useBalance, useReadContract } from 'wagmi'
import { erc20Abi, formatUnits } from 'viem'
import type { TokenInfo } from '../tokens/tokenRegistry'

/**
 * Hook che ritorna il balance di un token per il wallet connesso.
 * Per ETH nativo: usa useBalance di wagmi
 * Per ERC-20: usa useReadContract con balanceOf
 */
export function useTokenBalance(
  token: TokenInfo | null,
  address?: `0x${string}`,
) {
  const isNative = token?.isNative ?? true
  const tokenAddress = token?.address as `0x${string}` | undefined
  const decimals = token?.decimals ?? 18

  // Native ETH balance
  const {
    data: nativeData,
    isLoading: nativeLoading,
    refetch: refetchNative,
  } = useBalance({
    address,
    chainId: token?.chainId,
    query: { enabled: !!address && !!token && isNative },
  })

  // ERC-20 balance via balanceOf
  const {
    data: erc20Raw,
    isLoading: erc20Loading,
    refetch: refetchErc20,
  } = useReadContract({
    address: tokenAddress,
    abi: erc20Abi,
    functionName: 'balanceOf',
    args: address ? [address] : undefined,
    chainId: token?.chainId,
    query: { enabled: !!address && !!token && !isNative && !!tokenAddress },
  })

  const balance: bigint = isNative
    ? (nativeData?.value ?? 0n)
    : ((erc20Raw as bigint) ?? 0n)

  const formatted = formatUnits(balance, decimals)
  const isLoading = isNative ? nativeLoading : erc20Loading
  const refetch = isNative ? refetchNative : refetchErc20

  return { balance, formatted, isLoading, refetch }
}
