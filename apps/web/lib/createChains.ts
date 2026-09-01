// The chains and tokens the /app create-payment form may offer, and nothing
// else. ONE table, read by both the create modal and the repeat-prefill gate.
//
// WHY THIS SET. /app is hard-locked to `environment=test` — `useOrgPayments`
// never sends the param and the session route defaults it — so the offerable
// chains are exactly the backend's testnet chains that the token registry also
// knows about:
//
//   intent_service._TESTNET_CHAINS = {base_sepolia, sepolia, tron_nile}
//     ∩ token_registry.json          = {base_sepolia, tron_nile}
//
// `sepolia` is a testnet chain with no registry entry, so `chain_is_supported`
// is false and creating on it is a 400 UNSUPPORTED_CHAIN. Every mainnet chain
// (base, ethereum, tron) is a 400 TESTNET_ONLY on a test session AND a 403
// mainnet_activation_required at the chain-access guard. Offering one here
// would be offering a request the server refuses to create.
//
// WHY THE TOKENS ARE WHAT THEY ARE. `services/backend/app/token_registry.json`
// is the single source of truth for per-chain token policy, and it has no HTTP
// surface — nothing serves it to the browser. So this table is a mirror, and
// `app/__tests__/app/createChainsRegistry.test.ts` reads that JSON off disk and
// fails if the two ever disagree about which tokens are enabled or how many
// decimals they carry. Do not edit the symbols or decimals below without the
// registry saying so; the test is what makes this a mirror rather than a
// second source of truth.

/** A chain's address family. Decides which validator a recipient goes through
 * and which of the org's two settlement wallets is the payout address. */
export type ChainFamily = 'evm' | 'tron'

export interface CreateToken {
  symbol: string
  /** Base-unit decimals, from the registry. Drives the amount-scale gate. */
  decimals: number
}

export interface CreateChain {
  /** The wire value sent as `chain` on the create request. */
  chain: string
  /** Display name. A proper noun in every locale, so never translated —
   * exactly as the label it replaces was hardcoded in the modal. */
  label: string
  family: ChainFamily
  /** Display order; `tokens[0]` is the default selection for this chain. */
  tokens: CreateToken[]
  /** Whether a split intent can exist here. TRON has no RSendsSplitRouter (it
   * has no EVM chain id at all), so a split intent 422s SPLIT_UNAVAILABLE. */
  splitAvailable: boolean
}

export const CREATE_CHAINS: CreateChain[] = [
  {
    chain: 'base_sepolia',
    label: 'Base Sepolia',
    family: 'evm',
    // USDC first so it stays the default token, unchanged from before the
    // network selector existed. The registry lists ETH first; order here is
    // presentation, and the parity test compares sets, not sequences.
    tokens: [
      { symbol: 'USDC', decimals: 6 },
      { symbol: 'ETH', decimals: 18 },
    ],
    splitAvailable: true,
  },
  {
    chain: 'tron_nile',
    label: 'TRON Nile',
    family: 'tron',
    tokens: [{ symbol: 'USDT', decimals: 6 }],
    splitAvailable: false,
  },
]

/** The chain a freshly-opened create form starts on. */
export const DEFAULT_CREATE_CHAIN = 'base_sepolia'

export function chainFor(chain: string): CreateChain | undefined {
  return CREATE_CHAINS.find((c) => c.chain === chain)
}

/** Base-unit decimals for (chain, token), or undefined when the token is not
 * enabled on that chain. Undefined is meaningful: it is how a stale token
 * selection is detected after a network change. */
export function decimalsFor(chain: string, token: string): number | undefined {
  return chainFor(chain)?.tokens.find((t) => t.symbol === token)?.decimals
}
