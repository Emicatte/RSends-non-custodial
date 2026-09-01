/**
 * lib/web3/tronAddress — the client-side base58check mirror.
 *
 * This file is the containment for the fact that a second checksum
 * implementation now exists: every vector below was run through the server's
 * `is_tron_address` (services/backend/app/security/input_validator.py) on the
 * same commit, and the expectations are what Python answered — not what this
 * implementation happens to do.
 *
 * The two that carry the weight are the single-character mutation (which a
 * shape regex accepts and only a checksum rejects) and the lowercased address
 * (which proves case-folding destroys a T-address rather than merely changing
 * it).
 */

import {
  isTronAddress,
  looksLikeTronAddress,
  TRON_ZERO_ADDRESS,
} from '@/lib/web3/tronAddress'

// Real TRC-20 contract addresses, already used elsewhere in this repo.
const USDT_TRC20 = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const USDC_TRC20 = 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8'

describe('isTronAddress', () => {
  it('accepts real mainnet T-addresses', () => {
    expect(isTronAddress(USDT_TRC20)).toBe(true)
    expect(isTronAddress(USDC_TRC20)).toBe(true)
    expect(isTronAddress('TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn')).toBe(true)
  })

  it('accepts the zero address — its checksum IS valid', () => {
    // Which is exactly why the caller must reject it by an explicit compare:
    // no amount of decoding will catch it.
    expect(isTronAddress(TRON_ZERO_ADDRESS)).toBe(true)
  })

  it('rejects a one-character mutation that the shape regex accepts', () => {
    const typo = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u' // …6t → …6u
    expect(looksLikeTronAddress(typo)).toBe(true) // shape says yes
    expect(isTronAddress(typo)).toBe(false) // checksum says no
  })

  it('rejects a lowercased T-address — folding case destroys it', () => {
    expect(isTronAddress(USDT_TRC20.toLowerCase())).toBe(false)
  })

  it('rejects an EVM address, an empty string, and non-base58 characters', () => {
    expect(isTronAddress('0x' + 'a'.repeat(40))).toBe(false)
    expect(isTronAddress('')).toBe(false)
    // `0 O I l` are not in the base58 alphabet.
    expect(isTronAddress('T0OIl' + USDT_TRC20.slice(5))).toBe(false)
  })

  it('rejects a T-address of the wrong length', () => {
    expect(isTronAddress(USDT_TRC20.slice(0, -1))).toBe(false)
    expect(isTronAddress(USDT_TRC20 + 'a')).toBe(false)
  })
})

describe('looksLikeTronAddress', () => {
  it('is shape-only, so it must never be used to accept a payout address', () => {
    expect(looksLikeTronAddress('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u')).toBe(true)
    expect(isTronAddress('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u')).toBe(false)
  })

  it('does not fire on an EVM address or on arbitrary T-words', () => {
    expect(looksLikeTronAddress('0x' + 'a'.repeat(40))).toBe(false)
    expect(looksLikeTronAddress('Tomato')).toBe(false)
  })
})
