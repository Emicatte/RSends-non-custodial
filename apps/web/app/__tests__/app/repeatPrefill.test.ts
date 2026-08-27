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

it('resolves a single-recipient row into amount, token and recipient', () => {
  const result = resolveRepeatPrefill(row(), WALLET)

  expect(result).toEqual({
    ok: true,
    values: { amount: '100', token: 'USDC', recipient: A },
  })
})

it('carries an implicit settlement-wallet recipient as an empty override', () => {
  // A pre-gate row with no stored recipient settled to the org wallet. The
  // faithful repeat is "no override" — the modal resolves it the same way a
  // manual create does.
  const result = resolveRepeatPrefill(row({ recipient: null }), WALLET)

  expect(result).toEqual({
    ok: true,
    values: { amount: '100', token: 'USDC', recipient: '' },
  })
})

it('refuses a row whose chain is not the create chain', () => {
  expect(resolveRepeatPrefill(row({ chain: 'base' }), WALLET)).toEqual({
    ok: false,
    field: 'chain',
  })
})

it('refuses a token the create form can no longer offer', () => {
  // USDT passes the backend's currency allowlist but is not enabled here.
  expect(resolveRepeatPrefill(row({ currency: 'USDT' }), WALLET)).toEqual({
    ok: false,
    field: 'token',
  })
})

it('refuses an amount with more precision than the token has decimals', () => {
  // USDC is 6dp; a 9dp amount cannot be reproduced exactly, so it is refused
  // rather than silently rounded.
  expect(resolveRepeatPrefill(row({ amount: 0.0000001 }), WALLET)).toEqual({
    ok: false,
    field: 'amount',
  })
})

it('refuses a malformed recipient instead of dropping it', () => {
  expect(resolveRepeatPrefill(row({ recipient: '0xnope' }), WALLET)).toEqual({
    ok: false,
    field: 'recipient',
  })
})

it('refuses an implicit recipient when the org has no settlement wallet', () => {
  // Nothing to resolve to: no stored recipient, no split, no org wallet.
  expect(resolveRepeatPrefill(row({ recipient: null }), null)).toEqual({
    ok: false,
    field: 'recipient',
  })
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
    WALLET,
  )

  expect(result).toEqual({
    ok: true,
    values: {
      amount: '100',
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
    WALLET,
  )

  expect(result).toEqual({
    ok: true,
    values: {
      amount: '100',
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
    WALLET,
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
    WALLET,
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
    WALLET,
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
    WALLET,
  )

  expect(result).toEqual({ ok: false, field: 'split' })
})
