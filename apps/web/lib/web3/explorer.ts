/**
 * lib/web3/explorer — block-explorer URLs for the hosted checkout.
 *
 * Two lookups, in order. An EVM intent carries a numeric chain id, which the
 * central registry (contractRegistry.blockExplorer) resolves exactly as it
 * always has. A watch-only intent has no chain id at all — TRON is keyed by
 * NAME everywhere in this system, deliberately, because a synthetic EVM-shaped
 * id is how a reader comes to believe TRON is an EVM chain — so the intent's
 * `chain` string is the second lookup.
 *
 * There is no fallback. This module used to answer basescan.org for anything
 * it did not recognise, which meant an unknown chain produced a link that
 * looked right, resolved, and pointed at a block explorer for a different
 * network. A caller that gets `null` renders no link, which is the honest
 * answer and the one a payer can act on.
 */

import { getRegistry } from '@/lib/contractRegistry'

/**
 * Per-explorer path templates. Etherscan-family explorers use `/tx/{hash}`;
 * tronscan is a hash-routed SPA and uses `/#/transaction/{hash}`, so the path
 * cannot be a constant shared across the map.
 */
interface ExplorerConfig {
  base: string
  tx: (hash: string) => string
  address: (address: string) => string
}

const etherscanLike = (base: string): ExplorerConfig => ({
  base,
  tx: (hash) => `${base}/tx/${hash}`,
  address: (address) => `${base}/address/${address}`,
})

const tronscanLike = (base: string): ExplorerConfig => ({
  base,
  tx: (hash) => `${base}/#/transaction/${hash}`,
  address: (address) => `${base}/#/address/${address}`,
})

/**
 * Keyed by the backend's `chain` string, case-folded. The backend stores
 * `PaymentIntent.chain` verbatim as the merchant sent it, so `TRON`, `tron`
 * and `TRON_NILE` all reach us; every backend reader folds case and so does
 * this one.
 */
const BY_CHAIN_NAME: Record<string, ExplorerConfig> = {
  tron: tronscanLike('https://tronscan.org'),
  tron_nile: tronscanLike('https://nile.tronscan.org'),
  base: etherscanLike('https://basescan.org'),
  base_sepolia: etherscanLike('https://sepolia.basescan.org'),
  ethereum: etherscanLike('https://etherscan.io'),
  eth: etherscanLike('https://etherscan.io'),
  sepolia: etherscanLike('https://sepolia.etherscan.io'),
}

function explorerFor(
  chainId: number | null,
  chain?: string | null,
): ExplorerConfig | null {
  const reg = chainId != null ? getRegistry(chainId) : null
  if (reg?.blockExplorer) return etherscanLike(reg.blockExplorer.replace(/\/$/, ''))
  if (chain) {
    const byName = BY_CHAIN_NAME[chain.toLowerCase()]
    if (byName) return byName
  }
  return null
}

export function explorerTxUrl(
  chainId: number | null,
  hash: string,
  chain?: string | null,
): string | null {
  return explorerFor(chainId, chain)?.tx(hash) ?? null
}

export function explorerAddressUrl(
  chainId: number | null,
  address: string,
  chain?: string | null,
): string | null {
  return explorerFor(chainId, chain)?.address(address) ?? null
}
