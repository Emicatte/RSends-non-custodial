/**
 * lib/web3/explorer — explorer URLs for the hosted checkout. EVM intents
 * resolve through the numeric chain registry; watch-only intents have no chain
 * id at all and resolve by chain NAME.
 *
 * The behaviour worth defending is the absence of a fallback. This module used
 * to answer basescan.org for anything it did not recognise, which produced a
 * link that resolved, looked right, and pointed at the wrong network.
 */
import { explorerAddressUrl, explorerTxUrl } from '@/lib/web3/explorer'

const HASH = '0x' + 'ab'.repeat(32)
const ROUTER = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA'
// TRON hashes are 64 hex characters with no 0x prefix.
const TRON_HASH = 'cd'.repeat(32)
const TRON_ADDRESS = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'

describe('explorer links', () => {
  it('builds tx links from the central chain config', () => {
    expect(explorerTxUrl(84532, HASH)).toBe(
      `https://sepolia.basescan.org/tx/${HASH}`,
    )
    expect(explorerTxUrl(8453, HASH)).toBe(`https://basescan.org/tx/${HASH}`)
  })

  it('builds address links (View contract)', () => {
    expect(explorerAddressUrl(84532, ROUTER)).toBe(
      `https://sepolia.basescan.org/address/${ROUTER}`,
    )
  })
})

describe('watch-only chains, which have no chain id', () => {
  it('sends TRON to tronscan, on tronscan URL shapes', () => {
    // Not /tx/ and /address/: tronscan is hash-routed.
    expect(explorerTxUrl(null, TRON_HASH, 'tron')).toBe(
      `https://tronscan.org/#/transaction/${TRON_HASH}`,
    )
    expect(explorerAddressUrl(null, TRON_ADDRESS, 'tron')).toBe(
      `https://tronscan.org/#/address/${TRON_ADDRESS}`,
    )
  })

  it('sends Nile to the Nile explorer, never to mainnet tronscan', () => {
    expect(explorerTxUrl(null, TRON_HASH, 'tron_nile')).toBe(
      `https://nile.tronscan.org/#/transaction/${TRON_HASH}`,
    )
    expect(explorerAddressUrl(null, TRON_ADDRESS, 'tron_nile')).toBe(
      `https://nile.tronscan.org/#/address/${TRON_ADDRESS}`,
    )
  })

  it('folds case, because the backend stores `chain` as the merchant sent it', () => {
    for (const chain of ['TRON', 'tron', 'TrOn']) {
      expect(explorerTxUrl(null, TRON_HASH, chain)).toBe(
        `https://tronscan.org/#/transaction/${TRON_HASH}`,
      )
    }
    expect(explorerTxUrl(null, TRON_HASH, 'TRON_NILE')).toBe(
      `https://nile.tronscan.org/#/transaction/${TRON_HASH}`,
    )
  })

  it('never sends a TRON value to basescan', () => {
    const urls = [
      explorerTxUrl(null, TRON_HASH, 'tron'),
      explorerTxUrl(null, TRON_HASH, 'tron_nile'),
      explorerAddressUrl(null, TRON_ADDRESS, 'tron'),
      explorerAddressUrl(null, TRON_ADDRESS, 'tron_nile'),
    ]
    for (const url of urls) {
      expect(url).not.toBeNull()
      expect(url).not.toContain('basescan')
    }
  })
})

describe('the closed fallback', () => {
  it('returns null for an unknown chain id and an unknown name', () => {
    expect(explorerTxUrl(999999, HASH)).toBeNull()
    expect(explorerTxUrl(null, HASH)).toBeNull()
    expect(explorerTxUrl(null, HASH, 'solana')).toBeNull()
    expect(explorerAddressUrl(null, ROUTER, 'shasta')).toBeNull()
  })

  it('resolves a known EVM chain by name when the id is missing', () => {
    // The path that used to reach basescan by accident now reaches it on
    // purpose, and only when the intent actually says base.
    expect(explorerTxUrl(null, HASH, 'base')).toBe(
      `https://basescan.org/tx/${HASH}`,
    )
    expect(explorerTxUrl(null, HASH, 'base_sepolia')).toBe(
      `https://sepolia.basescan.org/tx/${HASH}`,
    )
  })

  it('prefers the numeric registry over the name', () => {
    expect(explorerTxUrl(8453, HASH, 'base_sepolia')).toBe(
      `https://basescan.org/tx/${HASH}`,
    )
  })
})
