/**
 * lib/web3/tron/tronNetwork — what the checkout needs to know about a TRON
 * network, and nothing else.
 *
 * WHY THIS TABLE EXISTS. On a router chain the backend hands the checkout an
 * `onchain` block carrying the token address, decimals and chain id. On a
 * watch-only chain it does not: `build_onchain_payment` returns None for TRON,
 * so `PublicPaymentIntentResponse.onchain` is null and the payer's page learns
 * only `chain`, `currency`, `recipient` and `amount_exact`. To build a TRC-20
 * transfer the page also needs the USDT contract, its decimals, a node to talk
 * to and the chain id to check the wallet against — none of which are on the
 * wire.
 *
 * So this is a MIRROR, in the same sense and with the same safeguard as
 * `lib/createChains.ts`: `services/backend/app/token_registry.json` has no HTTP
 * surface, so the values are duplicated here and
 * `app/__tests__/pay/tronNetwork.test.ts` reads that JSON off disk and fails if
 * the two ever disagree about the contract address or the decimals. Do not edit
 * a contract or a decimals value without the registry saying so; the test is
 * what makes this a mirror rather than a second source of truth.
 *
 * THE CHAIN IDS ARE NOT ARBITRARY. A TRON chain id is the last four bytes of
 * that network's genesis blockID, which the backend pins byte-for-byte in
 * `app/services/tron_chain_identity.py` and proves against every node at boot.
 * The same test derives these two constants from those genesis hashes rather
 * than trusting the literals below, and separately asserts they are exactly the
 * keys of the wallet adapter's own `chainIdNetworkMap` — so a drift in the
 * backend, in this file, or in the package is caught in one place.
 */

/** A token the checkout can pay with on a TRON network. */
export interface TronTokenConfig {
  symbol: string
  /** base58check contract address, verbatim from the registry. Never folded. */
  address: string
  /** Base-unit decimals. The amount conversion reads this, never a literal 6. */
  decimals: number
}

export interface TronNetworkConfig {
  /** The backend registry key, lowercase — the value `intent.raw.chain` folds to. */
  chain: string
  /** Display name. A proper noun, so never translated. */
  label: string
  /**
   * The chain id a TRON wallet reports, in the exact form the adapters use:
   * a lowercase `0x` + 8 hex digits string. Compared as a STRING against
   * `Network.chainId`; never parsed to a number, and never compared against
   * `NetworkType`, whose `Unknown` value collapses every custom node.
   */
  chainId: string
  /** CAIP-2 id. WalletConnect session accounts are `${caip2}:${address}`. */
  caip2: string
  /** TronGrid host for building, estimating and broadcasting. Must be in the
   * `connect-src` allowlist in next.config.mjs or the browser blocks it. */
  fullHost: string
  usdt: TronTokenConfig
}

const MAINNET: TronNetworkConfig = {
  chain: 'tron',
  label: 'TRON',
  chainId: '0x2b6653dc',
  caip2: 'tron:0x2b6653dc',
  fullHost: 'https://api.trongrid.io',
  usdt: {
    symbol: 'USDT',
    address: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
    decimals: 6,
  },
}

const NILE: TronNetworkConfig = {
  chain: 'tron_nile',
  label: 'TRON Nile',
  chainId: '0xcd8690dc',
  caip2: 'tron:0xcd8690dc',
  fullHost: 'https://nile.trongrid.io',
  usdt: {
    symbol: 'USDT',
    // The address the nileex.io faucet dispenses. The registry's own comment
    // warns to re-check it against the faucet, not against a block explorer.
    address: 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf',
    decimals: 6,
  },
}

export const TRON_NETWORKS: TronNetworkConfig[] = [MAINNET, NILE]

/**
 * The network for an intent's `chain`, or null when the chain is not a TRON
 * network this checkout can pay on.
 *
 * Null is meaningful and must not be papered over with a default: defaulting to
 * mainnet would point a Nile payer's wallet at the mainnet USDT contract, and
 * defaulting to Nile would do the reverse. Callers render "payment details are
 * not available" instead, which is the same thing the page already does when
 * `recipient` or `amount_exact` is missing.
 *
 * Folded exactly as `chainFamily` folds, and as every backend reader does:
 * `TRON`, `tron` and `TRON_NILE` all reach the wire.
 */
export function tronNetworkFor(
  chain: string | null | undefined,
): TronNetworkConfig | null {
  const key = (chain ?? '').toLowerCase()
  return TRON_NETWORKS.find((n) => n.chain === key) ?? null
}

/**
 * The token config for (chain, symbol), or null when that chain does not offer
 * that token. Scope is USDT-only today, so this exists to keep the symbol
 * comparison in one place rather than to promise a second token.
 */
export function tronTokenFor(
  chain: string | null | undefined,
  symbol: string | null | undefined,
): TronTokenConfig | null {
  const network = tronNetworkFor(chain)
  if (!network) return null
  return network.usdt.symbol === (symbol ?? '').toUpperCase()
    ? network.usdt
    : null
}
