/**
 * lib/web3/explorer — block-explorer URLs for the hosted checkout, sourced
 * from the central per-chain registry (contractRegistry.blockExplorer).
 * Base explorer as the conservative fallback for unknown chain ids.
 */

import { getRegistry } from '@/lib/contractRegistry'

const FALLBACK_EXPLORER = 'https://basescan.org'

function explorerBase(chainId: number | null): string {
  const reg = chainId != null ? getRegistry(chainId) : null
  return (reg?.blockExplorer ?? FALLBACK_EXPLORER).replace(/\/$/, '')
}

export function explorerTxUrl(chainId: number | null, hash: string): string {
  return `${explorerBase(chainId)}/tx/${hash}`
}

export function explorerAddressUrl(
  chainId: number | null,
  address: string,
): string {
  return `${explorerBase(chainId)}/address/${address}`
}
