/**
 * lib/chain-adapters/registry.ts — Global adapter registry
 *
 * Manages registration and lookup of ChainAdapter instances.
 * Key format: 'evm:8453', 'solana:mainnet-beta', 'tron:mainnet'
 */

import type { ChainAdapter, ChainFamily } from './types'

/** Global registry of chain adapters */
const adapterRegistry = new Map<string, ChainAdapter>()

/**
 * Generate a unique key for a chain.
 * EVM: 'evm:8453', Solana: 'solana:mainnet-beta', Tron: 'tron:mainnet'
 */
function makeKey(family: ChainFamily, chainId: number | string): string {
  return `${family}:${chainId}`
}

/** Register an adapter */
export function registerAdapter(adapter: ChainAdapter): void {
  const key = makeKey(adapter.family, adapter.chainId)
  adapterRegistry.set(key, adapter)
}

/** Get adapter for a specific chain */
export function getAdapter(family: ChainFamily, chainId: number | string): ChainAdapter | null {
  return adapterRegistry.get(makeKey(family, chainId)) ?? null
}

/** Get all registered adapters */
export function getAllAdapters(): ChainAdapter[] {
  return Array.from(adapterRegistry.values())
}

/** Get adapters filtered by chain family */
export function getAdaptersByFamily(family: ChainFamily): ChainAdapter[] {
  return getAllAdapters().filter(a => a.family === family)
}

/** Check if a chain is supported (has a registered adapter) */
export function isChainSupported(family: ChainFamily, chainId: number | string): boolean {
  return adapterRegistry.has(makeKey(family, chainId))
}
