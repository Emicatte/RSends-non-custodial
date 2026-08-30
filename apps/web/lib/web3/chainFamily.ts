/**
 * lib/web3/chainFamily — which payment flow an intent belongs to.
 *
 * The checkout has two flows now, and the one thing that must NOT decide
 * between them is `onchain === null`. That value has two meanings: on a router
 * chain it means the intent is unpayable (a missing chain id, an unconfigured
 * router, a malformed field that failed to normalize), and on a watch-only
 * chain it is the normal, expected shape — there is no contract to call
 * because the payer sends the token straight to `recipient`. Conflating them
 * loses the ability to tell a valid TRON invoice from a broken EVM one, and
 * the two need opposite screens: instructions, or a retrying skeleton.
 *
 * So the family comes from `chain`. This mirrors the normative rule in
 * docs/INTEGRATION_CONTRACT.md: "Branch on `chain`, not on `onchain == null`."
 */

import type { PaymentIntent } from './paymentIntent'

export type ChainFamily = 'evm' | 'tron'

/**
 * The watch-only TRON networks, by the backend's registry key. Both are keyed
 * by NAME rather than a chain id — a non-EVM chain has no EVM chain id and
 * must not be given a synthetic one.
 */
const TRON_CHAINS = new Set(['tron', 'tron_nile'])

/**
 * `PaymentIntent.chain` is stored verbatim as the merchant sent it, so `TRON`,
 * `tron` and `TRON_NILE` all reach the wire. Fold, exactly as every backend
 * reader does.
 *
 * An absent or unrecognised chain is `evm`: that is what this checkout has
 * always assumed (`normalizeIntent` defaults a missing chain to Base), and it
 * keeps the fallback pointing at the flow that can still report a problem
 * rather than at one that would render payment instructions for a chain we
 * know nothing about.
 */
export function chainFamily(chain: string | null | undefined): ChainFamily {
  return TRON_CHAINS.has((chain ?? '').toLowerCase()) ? 'tron' : 'evm'
}

export type PayFlow = 'tron_instructions' | 'evm_wallet'

export function payFlowFor(intent: PaymentIntent): PayFlow {
  return chainFamily(intent.raw.chain) === 'tron'
    ? 'tron_instructions'
    : 'evm_wallet'
}
