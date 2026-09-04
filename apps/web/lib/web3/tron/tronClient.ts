/**
 * lib/web3/tron/tronClient — the read/build TronWeb instance, loaded lazily.
 *
 * WHY THE IMPORT IS DYNAMIC. tronweb pulls ethers, axios and google-protobuf;
 * measured as a static import it is a second full crypto stack next to viem on
 * the checkout route. The EVM checkout must not pay for a dependency only the
 * TRON branch uses, and `/pay` is the most latency-sensitive page in the
 * product, so the package is fetched only once an intent is known to be TRON.
 *
 * The instance carries NO private key and never will. It is used for exactly
 * four read/build operations — `triggerSmartContract` (build the unsigned
 * transfer), `triggerConstantContract` (balance and energy estimation),
 * `getChainParameters` (the energy price) and `sendRawTransaction` (hand the
 * wallet's signed transaction to the node) — none of which can move funds. All
 * signing happens in the payer's wallet. Passing a `privateKey` here would make
 * the platform custodial, which is the one thing this codebase never does.
 */

import type { TronWeb } from 'tronweb'

import type { TronNetworkConfig } from './tronNetwork'

/**
 * One instance per host. A checkout only ever talks to a single network, so
 * this is a cache of one in practice; keying by host keeps it correct if a page
 * ever renders two intents, and makes the memo obviously safe.
 */
const clients = new Map<string, Promise<TronWeb>>()

export function getTronClient(network: TronNetworkConfig): Promise<TronWeb> {
  const cached = clients.get(network.fullHost)
  if (cached) return cached

  const client = import('tronweb').then(
    ({ TronWeb: Ctor }) => new Ctor({ fullHost: network.fullHost }),
  )
  clients.set(network.fullHost, client)
  return client
}

/** Test seam: drop the memo so a suite cannot leak an instance between cases. */
export function resetTronClients(): void {
  clients.clear()
}
