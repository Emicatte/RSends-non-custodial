/**
 * `lib/web3/tron/tronNetwork.ts` is a MIRROR of backend constants, and this is
 * what makes it one.
 *
 * Three different sources of truth live in the backend and none of them is
 * served over HTTP, so the checkout cannot read any of them at runtime:
 *
 *   - the USDT contract and its decimals   -> app/token_registry.json
 *   - the chain id of each TRON network    -> app/services/tron_chain_identity.py
 *                                             (last 4 bytes of the genesis blockID)
 *   - which hosts the browser may call     -> apps/web/next.config.mjs (CSP)
 *
 * Each is read here, off disk, at test time. A wrong contract address sends a
 * payer's USDT to the wrong token on the right chain; a wrong chain id lets a
 * mainnet wallet look correct on a Nile invoice; a host missing from the CSP
 * makes the whole flow fail in the browser with a console error and no UI. All
 * three are silent in unit tests that mock the network, so they are asserted
 * against the real files instead.
 */
import fs from 'fs'
import path from 'path'

import { chainIdNetworkMap } from '@tronweb3/tronwallet-adapter-tronlink'

import {
  TRON_NETWORKS,
  tronNetworkFor,
  tronTokenFor,
} from '@/lib/web3/tron/tronNetwork'

const REPO = path.resolve(__dirname, '../../../../..')
const REGISTRY_PATH = path.join(
  REPO,
  'services/backend/app/token_registry.json',
)
const CHAIN_IDENTITY_PATH = path.join(
  REPO,
  'services/backend/app/services/tron_chain_identity.py',
)
const NEXT_CONFIG_PATH = path.join(REPO, 'apps/web/next.config.mjs')

interface RegistryToken {
  address: string
  decimals: number
  enabled: boolean
}
interface RegistryChain {
  name: string
  settlement?: string
  tokens: Record<string, RegistryToken>
}

function registryChain(name: string): RegistryChain {
  const raw = JSON.parse(fs.readFileSync(REGISTRY_PATH, 'utf8')) as Record<
    string,
    unknown
  >
  const found = Object.entries(raw)
    .filter(([key]) => key !== '_comment')
    .map(([, chain]) => chain as RegistryChain)
    .find((c) => c.name === name)
  if (!found) throw new Error(`chain "${name}" is not in ${REGISTRY_PATH}`)
  return found
}

/**
 * The pinned genesis blockID for a network, read from the Python. `network` is
 * the backend's key ("mainnet" / "nile"), not the registry chain name.
 */
function genesisBlockId(network: 'MAINNET' | 'NILE'): string {
  const src = fs.readFileSync(CHAIN_IDENTITY_PATH, 'utf8')
  const match = new RegExp(
    `TRON_${network}_GENESIS_BLOCK_ID\\s*=\\s*\\(\\s*"([0-9a-f]{64})"`,
  ).exec(src)
  if (!match) {
    throw new Error(
      `could not read TRON_${network}_GENESIS_BLOCK_ID from ${CHAIN_IDENTITY_PATH} — ` +
        'if the constant was renamed or reformatted, fix this reader rather than deleting the assertion',
    )
  }
  return match[1]
}

function connectSrc(): string {
  const src = fs.readFileSync(NEXT_CONFIG_PATH, 'utf8')
  const match = /connect-src[^`]*/.exec(src)
  if (!match) throw new Error(`no connect-src directive in ${NEXT_CONFIG_PATH}`)
  return match[0]
}

it('reads every backend source from the expected path', () => {
  // Guards the relative paths themselves: a moved file would otherwise make
  // every assertion below throw for a reason unrelated to drift.
  expect(fs.existsSync(REGISTRY_PATH)).toBe(true)
  expect(fs.existsSync(CHAIN_IDENTITY_PATH)).toBe(true)
  expect(fs.existsSync(NEXT_CONFIG_PATH)).toBe(true)
})

it('declares exactly the watch-only TRON chains the registry knows', () => {
  expect(TRON_NETWORKS.map((n) => n.chain).sort()).toEqual([
    'tron',
    'tron_nile',
  ])
  for (const network of TRON_NETWORKS) {
    expect(registryChain(network.chain).settlement).toBe('watch_only')
  }
})

it.each([
  ['tron', 'MAINNET'],
  ['tron_nile', 'NILE'],
] as const)(
  '%s carries the chain id derived from the backend’s pinned genesis blockID',
  (chain, network) => {
    // A TRON chain id IS the last four bytes of the genesis blockID. Deriving
    // it here rather than hardcoding a second copy means a change to the
    // backend's pinned hash cannot leave this file quietly disagreeing.
    const expected = `0x${genesisBlockId(network).slice(-8)}`
    const declared = tronNetworkFor(chain)!

    expect(declared.chainId).toBe(expected)
    // CAIP-2 is the same value with the namespace, and it is what a
    // WalletConnect session account is prefixed with.
    expect(declared.caip2).toBe(`tron:${expected}`)
  },
)

it('declares chain ids the wallet adapter agrees are TRON networks', () => {
  // The adapter matches a wallet's reported chain id against its own map. A
  // chain id of ours that is not a key there could never match a connected
  // wallet, so the mismatch must fail here rather than as an unexplainable
  // permanent wrong_network on a payer's screen.
  for (const network of TRON_NETWORKS) {
    expect(Object.keys(chainIdNetworkMap)).toContain(network.chainId)
  }
})

it.each(['tron', 'tron_nile'])(
  '%s carries the registry’s USDT contract and decimals, byte-identical',
  (chain) => {
    const registry = registryChain(chain).tokens.USDT
    const declared = tronNetworkFor(chain)!.usdt

    expect(registry.enabled).toBe(true)
    // Byte-identical, case included: base58check is case-sensitive, so a
    // folded contract address is a different address, not a formatting choice.
    expect(declared.address).toBe(registry.address)
    expect(declared.decimals).toBe(registry.decimals)
    expect(tronTokenFor(chain, 'USDT')).toEqual(declared)
  },
)

it('never lets the two networks share a contract, a chain id or a node', () => {
  // The failure this guards is a copy-paste when a third network is added:
  // Nile inheriting mainnet's USDT address would send testnet payers at a
  // mainnet contract, and the amount/recipient checks would all still pass.
  const [mainnet, nile] = TRON_NETWORKS
  expect(mainnet.usdt.address).not.toBe(nile.usdt.address)
  expect(mainnet.chainId).not.toBe(nile.chainId)
  expect(mainnet.fullHost).not.toBe(nile.fullHost)
})

it('only reaches nodes the CSP actually allows', () => {
  // Without this the flow dies in the browser and nowhere else: every unit
  // test mocks the network, so a host missing from connect-src is invisible
  // until a real payer's console fills with blocked requests.
  const directive = connectSrc()
  for (const network of TRON_NETWORKS) {
    expect(directive).toContain(network.fullHost)
  }
})

it('resolves the chain case-insensitively and refuses everything else', () => {
  // `chain` reaches the wire exactly as the merchant sent it, so TRON and
  // TRON_NILE are both real inputs — the same fold `chainFamily` performs.
  expect(tronNetworkFor('TRON')?.chain).toBe('tron')
  expect(tronNetworkFor('TRON_NILE')?.chain).toBe('tron_nile')

  // Null rather than a default. Defaulting to either network would point a
  // payer's wallet at the other one's USDT contract.
  expect(tronNetworkFor('base_sepolia')).toBeNull()
  expect(tronNetworkFor('tron_shasta')).toBeNull()
  expect(tronNetworkFor(null)).toBeNull()
  expect(tronNetworkFor(undefined)).toBeNull()

  // A token the chain does not offer is null, not a silent fallback to USDT.
  expect(tronTokenFor('tron_nile', 'USDC')).toBeNull()
  expect(tronTokenFor('base_sepolia', 'USDT')).toBeNull()
})
