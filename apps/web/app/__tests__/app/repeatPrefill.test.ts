/**
 * Repeat-payment prefill resolver — the fail-closed gate.
 *
 * `resolveRepeatPrefill` turns an existing payments-list row into initial values
 * for the EXISTING creation modal, or refuses and names the field that failed.
 * It never returns partial data and never falls back to a default.
 *
 * The split case is the load-bearing one: the list stores `share_bps`, the modal
 * takes AMOUNTS. The resolver converts bps → amounts with `onchainAmounts` and
 * then re-derives bps with `amountsToSharesBps` — the same function creation
 * uses — and refuses unless the re-derived vector is bit-identical to the stored
 * one. That is what makes "a repeat reproduces the source split exactly" a
 * proven property rather than an assumed one.
 */
import { resolveRepeatPrefill } from '@/lib/repeatPrefill'
import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'

const WALLET = '0xabc0000000000000000000000000000000000001'
const A = '0x1111111111111111111111111111111111111111'
const B = '0x2222222222222222222222222222222222222222'
const C = '0x3333333333333333333333333333333333333333'
// Real base58check addresses (the same ones lib/tronAddress.test.ts proves
// valid). Mixed case is the point: base58 omits `0 O I l`, so lowercasing a
// T-address does not merely change it — it can leave the alphabet entirely.
const T_RECIPIENT = 'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8'
const T_WALLET = 'TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn'

// The org's two payout addresses, one per address family. A record rather than
// a bare string: the family of the ROW decides which one is the fallback, and
// passing "the settlement wallet" without saying which family it belongs to is
// exactly how a TRON repeat used to be checked against the EVM column.
const WALLETS = { evm: WALLET, tron: T_WALLET }

function row(overrides: Partial<OrgPaymentRecord> = {}): OrgPaymentRecord {
  return {
    intent_id: 'pi_src',
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'paid',
    recipient: A,
    tx_hash: null,
    matched_tx_hash: null,
    created_at: '2026-08-01T10:00:00Z',
    expires_at: '2026-08-01T11:00:00Z',
    ...overrides,
  }
}

/** A TRON Nile row: the other family, the other token, the other wallet. */
function tronRow(overrides: Partial<OrgPaymentRecord> = {}): OrgPaymentRecord {
  return row({
    chain: 'tron_nile',
    currency: 'USDT',
    recipient: T_RECIPIENT,
    ...overrides,
  })
}

it('resolves a single-recipient row into chain, amount, token and recipient', () => {
  const result = resolveRepeatPrefill(row(), WALLETS)

  expect(result).toEqual({
    ok: true,
    values: { amount: '100', chain: 'base_sepolia', token: 'USDC', recipient: A },
  })
})

it('carries an implicit settlement-wallet recipient as an empty override', () => {
  // A pre-gate row with no stored recipient settled to the org wallet. The
  // faithful repeat is "no override" — the modal resolves it the same way a
  // manual create does.
  const result = resolveRepeatPrefill(row({ recipient: null }), WALLETS)

  expect(result).toEqual({
    ok: true,
    values: { amount: '100', chain: 'base_sepolia', token: 'USDC', recipient: '' },
  })
})

it('repeats a TRON row onto TRON Nile with its base58 recipient intact', () => {
  const result = resolveRepeatPrefill(tronRow(), WALLETS)

  expect(result).toEqual({
    ok: true,
    values: {
      amount: '100',
      chain: 'tron_nile',
      token: 'USDT',
      // Character-for-character, case included. A `.toLowerCase()` anywhere on
      // this path would produce a string that is not a TRON address at all.
      recipient: T_RECIPIENT,
    },
  })
})

it('resolves a TRON row with no recipient against the org TRON payout address', () => {
  const result = resolveRepeatPrefill(tronRow({ recipient: null }), WALLETS)

  expect(result).toEqual({
    ok: true,
    values: { amount: '100', chain: 'tron_nile', token: 'USDT', recipient: '' },
  })
})

it('refuses a TRON row with no recipient when only the EVM wallet is set', () => {
  // The EVM settlement wallet is NOT a fallback for TRON — the server refuses
  // that with SETTLEMENT_WALLET_TRON_MISSING, and opening a prefilled modal
  // that cannot submit would be a lie told one screen earlier.
  expect(
    resolveRepeatPrefill(tronRow({ recipient: null }), { evm: WALLET, tron: null }),
  ).toEqual({ ok: false, field: 'recipientTron' })
})

it('refuses an EVM address as the recipient of a TRON row', () => {
  expect(resolveRepeatPrefill(tronRow({ recipient: A }), WALLETS)).toEqual({
    ok: false,
    field: 'recipient',
  })
})

it('refuses a TRON address as the recipient of a Base Sepolia row', () => {
  expect(resolveRepeatPrefill(row({ recipient: T_RECIPIENT }), WALLETS)).toEqual({
    ok: false,
    field: 'recipient',
  })
})

it('refuses a chain the create form does not offer', () => {
  // `base` is mainnet: a real registry chain, but not one /app can create on.
  expect(resolveRepeatPrefill(row({ chain: 'base' }), WALLETS)).toEqual({
    ok: false,
    field: 'chain',
  })
})

it('refuses a token the create form can no longer offer', () => {
  // USDT passes the backend's currency allowlist but is not enabled here.
  expect(resolveRepeatPrefill(row({ currency: 'USDT' }), WALLETS)).toEqual({
    ok: false,
    field: 'token',
  })
})

it('refuses a token enabled on another chain but not on this row', () => {
  // The token check is keyed by (chain, token), never a union across chains:
  // USDC exists on Base Sepolia and USDT on TRON Nile, and neither crosses.
  expect(resolveRepeatPrefill(tronRow({ currency: 'USDC' }), WALLETS)).toEqual({
    ok: false,
    field: 'token',
  })
})

it('refuses an amount with more precision than the token has decimals', () => {
  // USDC is 6dp; a 9dp amount cannot be reproduced exactly, so it is refused
  // rather than silently rounded.
  expect(resolveRepeatPrefill(row({ amount: 0.0000001 }), WALLETS)).toEqual({
    ok: false,
    field: 'amount',
  })
})

it('refuses a malformed recipient instead of dropping it', () => {
  expect(resolveRepeatPrefill(row({ recipient: '0xnope' }), WALLETS)).toEqual({
    ok: false,
    field: 'recipient',
  })
})

it('refuses an implicit recipient when the org has no settlement wallet', () => {
  // Nothing to resolve to: no stored recipient, no split, no EVM org wallet —
  // and the TRON payout address is not a fallback in that direction either.
  expect(
    resolveRepeatPrefill(row({ recipient: null }), { evm: null, tron: T_WALLET }),
  ).toEqual({ ok: false, field: 'recipient' })
})

it('refuses a split on a chain that has no split router', () => {
  // TRON has no RSendsSplitRouter, so no TRON row can legitimately carry legs.
  // The branch is GATED rather than assumed unreachable: the split body below
  // is EVM-shaped throughout, and it must never run on a base58 address.
  const result = resolveRepeatPrefill(
    tronRow({
      recipient: null,
      split: [
        { address: T_RECIPIENT, share_bps: 5000, position: 0 },
        { address: T_WALLET, share_bps: 5000, position: 1 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({ ok: false, field: 'split' })
})

it('converts a split row into per-leg amounts that sum to the total', () => {
  const result = resolveRepeatPrefill(
    row({
      recipient: null,
      split: [
        { address: A, share_bps: 2500, position: 0 },
        { address: B, share_bps: 7500, position: 1 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({
    ok: true,
    values: {
      amount: '100',
      chain: 'base_sepolia',
      token: 'USDC',
      splitLegs: [
        { address: A, amount: '25' },
        { address: B, amount: '75' },
      ],
    },
  })
})

it('reads legs in position order, not array order', () => {
  const result = resolveRepeatPrefill(
    row({
      recipient: null,
      split: [
        { address: B, share_bps: 7500, position: 1 },
        { address: A, share_bps: 2500, position: 0 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({
    ok: true,
    values: {
      amount: '100',
      chain: 'base_sepolia',
      token: 'USDC',
      splitLegs: [
        { address: A, amount: '25' },
        { address: B, amount: '75' },
      ],
    },
  })
})

it('round-trips a non-even split bit-identically through the creation math', () => {
  // 3333/3333/3334 on 10 USDC — the case where floor-then-round could drift.
  const stored = [
    { address: A, share_bps: 3333, position: 0 },
    { address: B, share_bps: 3333, position: 1 },
    { address: C, share_bps: 3334, position: 2 },
  ]
  const result = resolveRepeatPrefill(
    row({ amount: 10, recipient: null, split: stored }),
    WALLETS,
  )

  expect(result.ok).toBe(true)
  if (!result.ok) return
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { amountToBase, amountsToSharesBps } = require('@/lib/splitShares')
  const legs = result.values.splitLegs!
  const amounts = legs.map((l) => amountToBase(l.amount, 6))
  expect(amountsToSharesBps(amounts, amountToBase('10', 6))).toEqual([
    3333, 3333, 3334,
  ])
})

it('refuses a split whose stored shares do not sum to 10000 bps', () => {
  const result = resolveRepeatPrefill(
    row({
      recipient: null,
      split: [
        { address: A, share_bps: 2500, position: 0 },
        { address: B, share_bps: 7000, position: 1 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({ ok: false, field: 'split' })
})

it('refuses a split with a duplicate address', () => {
  const result = resolveRepeatPrefill(
    row({
      recipient: null,
      split: [
        { address: A, share_bps: 5000, position: 0 },
        { address: A, share_bps: 5000, position: 1 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({ ok: false, field: 'split' })
})

it('refuses a split that cannot be re-derived at this amount', () => {
  // 1 bps of 0.001 USDC (1000 base units) floors to 0 — the leg cannot be
  // represented as an amount that rounds back to its stored share.
  const result = resolveRepeatPrefill(
    row({
      amount: 0.001,
      recipient: null,
      split: [
        { address: A, share_bps: 9999, position: 0 },
        { address: B, share_bps: 1, position: 1 },
      ],
    }),
    WALLETS,
  )

  expect(result).toEqual({ ok: false, field: 'split' })
})
