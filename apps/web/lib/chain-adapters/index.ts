/**
 * lib/chain-adapters/index.ts — Public API
 *
 * Re-exports adapter types, registry, and factory functions.
 */

export * from './types'
export * from './registry'
export { createEVMAdapter } from './evm-adapter'
export { createSolanaAdapter } from './solana-adapter'
export { createTronAdapter } from './tron-adapter'
