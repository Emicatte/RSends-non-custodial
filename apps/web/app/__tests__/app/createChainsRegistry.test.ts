/**
 * `lib/createChains.ts` is a MIRROR of the backend token registry, and this is
 * what makes it one.
 *
 * `services/backend/app/token_registry.json` is the single source of truth for
 * per-chain token policy, and it has no HTTP surface — no endpoint serves it to
 * the browser — so the create form cannot read it at runtime. It is read here
 * instead, off disk, at test time: if the two ever disagree about which tokens
 * are enabled, how many decimals they carry, or which address family a chain
 * speaks, this fails rather than the merchant meeting a 400 UNSUPPORTED_TOKEN
 * with a form that offered the token.
 *
 * The one thing NOT derived from the JSON is which chains are offered at all:
 * that comes from `intent_service._TESTNET_CHAINS` (a Python set, and /app is
 * hard-locked to `environment=test`), so it is asserted explicitly below.
 */
import fs from 'fs'
import path from 'path'

import { CREATE_CHAINS, DEFAULT_CREATE_CHAIN, chainFor, decimalsFor } from '@/lib/createChains'

interface RegistryToken {
  decimals: number
  enabled: boolean
}
interface RegistryChain {
  name: string
  addressFormat?: string
  settlement?: string
  tokens: Record<string, RegistryToken>
}

const REGISTRY_PATH = path.resolve(
  __dirname,
  '../../../../../services/backend/app/token_registry.json',
)

function loadRegistry(): RegistryChain[] {
  const raw = JSON.parse(fs.readFileSync(REGISTRY_PATH, 'utf8')) as Record<string, unknown>
  return Object.entries(raw)
    .filter(([key]) => key !== '_comment')
    .map(([, chain]) => chain as RegistryChain)
}

function registryChain(name: string): RegistryChain {
  const found = loadRegistry().find((c) => c.name === name)
  if (!found) throw new Error(`chain "${name}" is not in ${REGISTRY_PATH}`)
  return found
}

/** `{symbol: decimals}` for the chain's ENABLED tokens only. A token present
 * but `enabled: false` (Base's bridged USDT, say) must never be offered. */
function enabledTokens(chain: RegistryChain): Record<string, number> {
  return Object.fromEntries(
    Object.entries(chain.tokens)
      .filter(([, tok]) => tok.enabled)
      .map(([symbol, tok]) => [symbol, tok.decimals]),
  )
}

it('reads the backend registry from the expected path', () => {
  // Guards the relative path itself: a moved file would otherwise make every
  // assertion below throw for a reason that has nothing to do with drift.
  expect(fs.existsSync(REGISTRY_PATH)).toBe(true)
})

it('offers exactly the testnet chains the backend can create on', () => {
  // intent_service._TESTNET_CHAINS = {base_sepolia, sepolia, tron_nile}
  // ∩ token_registry.json = {base_sepolia, tron_nile}. `sepolia` has no
  // registry entry (400 UNSUPPORTED_CHAIN); every mainnet chain is 400
  // TESTNET_ONLY on the test-locked /app session.
  expect(CREATE_CHAINS.map((c) => c.chain).sort()).toEqual(['base_sepolia', 'tron_nile'])
  expect(chainFor(DEFAULT_CREATE_CHAIN)).toBeDefined()
})

it.each(['base_sepolia', 'tron_nile'])(
  '%s offers exactly the tokens the registry enables, with the registry decimals',
  (name) => {
    const declared = chainFor(name)!
    const expected = enabledTokens(registryChain(name))

    // Compared as a MAP, not a sequence: order in `createChains` is display
    // order (USDC first so it stays the default), which the registry does not
    // and should not constrain.
    expect(
      Object.fromEntries(declared.tokens.map((t) => [t.symbol, t.decimals])),
    ).toEqual(expected)

    for (const [symbol, decimals] of Object.entries(expected)) {
      expect(decimalsFor(name, symbol)).toBe(decimals)
    }
  },
)

it.each(['base_sepolia', 'tron_nile'])('%s declares the registry address family', (name) => {
  const chain = registryChain(name)
  const declared = chainFor(name)!
  // base58check is what makes a chain TRON-family here — the same field
  // `router_registry.chain_address_format` reads, and the same distinction the
  // server's RECIPIENT_CHAIN_MISMATCH gate makes.
  expect(declared.family).toBe(chain.addressFormat === 'base58check' ? 'tron' : 'evm')
})

it.each(['base_sepolia', 'tron_nile'])('%s never offers split on a watch-only chain', (name) => {
  const chain = registryChain(name)
  const declared = chainFor(name)!
  // A watch-only chain has no EVM chain id, so `split_router_address_for`
  // returns None and any split intent is a 422 SPLIT_UNAVAILABLE.
  if (chain.settlement === 'watch_only') {
    expect(declared.splitAvailable).toBe(false)
  }
})

it('never offers a token the registry has disabled', () => {
  // Regression shape for the real trap: Base carries USDT and DAI entries that
  // are `enabled: false`, so "the chain lists the symbol" is not the test.
  for (const declared of CREATE_CHAINS) {
    const chain = registryChain(declared.chain)
    for (const tok of declared.tokens) {
      expect(chain.tokens[tok.symbol]?.enabled).toBe(true)
    }
  }
})
