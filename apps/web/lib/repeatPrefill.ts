// Repeat a payment request: turn an existing payments-list row into initial
// values for the EXISTING creation modal — or refuse, naming the field that
// failed. Pure (no React), so the gate is unit-testable on its own.
//
// FAIL-CLOSED by construction. A repeat that silently fell back to a default
// would issue a payment request the merchant did not configure, to a recipient
// they did not choose. Every branch below either resolves exactly or refuses;
// there is no partial result.

import { isAddress } from 'viem'
import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'
import {
  amountToBase,
  amountsToSharesBps,
  formatBase,
  onchainAmounts,
} from '@/lib/splitShares'

// The create flow is hard-locked to test: Base Sepolia is the only settleable
// testnet (USDC + ETH are the enabled tokens there). No chain picker, no live.
// Lives here rather than in the modal so the prefill gate and the create form
// read ONE registry — a row is offered for repeat on exactly the terms the
// create form can honour.
export const CREATE_CHAIN = 'base_sepolia'
export const CREATE_TOKENS = ['USDC', 'ETH'] as const
// Base-unit decimals for the create tokens. The backend chain registry
// (SUPPORTED_CHAINS → router_registry) is the SSOT; payTokens.ts covers
// only the /pay-side ERC-20s and deliberately has no native ETH entry.
export const CREATE_TOKEN_DECIMALS: Record<string, number> = { USDC: 6, ETH: 18 }

const SPLIT_MIN = 2
const SPLIT_MAX = 20

/** Initial values for CreatePaymentModal. Amounts are decimal strings in the
 * token's units — the form's own input format — never base units. */
export interface CreatePrefill {
  amount: string
  token: string
  /** Single-payee override. '' means "use the org settlement wallet", which is
   * how the source intent itself resolved when it stored no recipient. */
  recipient?: string
  /** Split legs in position order. The modal's last row auto-balances, so the
   * final amount is advisory there — it is supplied for completeness. */
  splitLegs?: { address: string; amount: string }[]
}

export type PrefillFailure = 'chain' | 'token' | 'amount' | 'recipient' | 'split'

export type PrefillResult =
  | { ok: true; values: CreatePrefill }
  | { ok: false; field: PrefillFailure }

const fail = (field: PrefillFailure): PrefillResult => ({ ok: false, field })

/**
 * Resolve a source row into create-form values, or refuse.
 *
 * The split branch is the load-bearing one. Storage is `share_bps`; the modal
 * takes AMOUNTS. We convert with `onchainAmounts` (the contract mirror) and then
 * re-derive with `amountsToSharesBps` — the very function the create form uses —
 * and refuse unless the round-trip is bit-identical. The stored breakdown is
 * never trusted: it is re-proven against the creation math at prefill time.
 *
 * The per-leg `label` is dropped: the create form has no label field, so
 * carrying it would produce a request the merchant could not have typed.
 */
export function resolveRepeatPrefill(
  row: OrgPaymentRecord,
  settlementWallet: string | null,
): PrefillResult {
  // 1. Chain. /app is test-locked; a row from any other chain has no router
  //    the create form could target.
  if ((row.chain ?? '').toLowerCase() !== CREATE_CHAIN) return fail('chain')

  // 2. Token — must still be one the form offers.
  const token = row.currency
  if (!(CREATE_TOKENS as readonly string[]).includes(token)) return fail('token')
  const decimals = CREATE_TOKEN_DECIMALS[token]
  if (decimals == null) return fail('token')

  // 3. Amount. Rejects float-repr artifacts, exponent notation and any
  //    precision the token cannot represent — never rounds to fit.
  const amount = String(row.amount)
  const totalBase = amountToBase(amount, decimals)
  if (totalBase == null) return fail('amount')

  // 4. Split, when the source had one.
  const legs = row.split
  if (legs && legs.length > 0) {
    if (legs.length < SPLIT_MIN || legs.length > SPLIT_MAX) return fail('split')

    // Position is the on-chain leg order and leg 0 carries the contract's
    // remainder — reconstruct by it rather than trusting array order.
    const ordered = [...legs].sort((a, b) => a.position - b.position)
    if (ordered.some((leg, i) => leg.position !== i)) return fail('split')

    const addrs = ordered.map((leg) => leg.address)
    if (!addrs.every((a) => isAddress(a))) return fail('split')
    if (new Set(addrs.map((a) => a.toLowerCase())).size !== addrs.length) {
      return fail('split')
    }

    const bps = ordered.map((leg) => leg.share_bps)
    if (bps.some((b) => !Number.isInteger(b) || b < 1)) return fail('split')
    if (bps.reduce((acc, b) => acc + b, 0) !== 10000) return fail('split')

    const amounts = onchainAmounts(totalBase, bps)
    if (amounts.some((a) => a <= 0n)) return fail('split')
    // The proof: these amounts must re-derive to the stored shares exactly.
    const rederived = amountsToSharesBps(amounts, totalBase)
    if (rederived == null) return fail('split')
    if (rederived.length !== bps.length) return fail('split')
    if (rederived.some((b, i) => b !== bps[i])) return fail('split')

    return {
      ok: true,
      values: {
        amount,
        token,
        splitLegs: ordered.map((leg, i) => ({
          address: leg.address,
          amount: formatBase(amounts[i], decimals),
        })),
      },
    }
  }

  // 5. Single payee. A stored recipient is an explicit override and must be a
  //    valid address. No stored recipient means the source settled implicitly to
  //    the org wallet — reproducible only if the org still has one.
  if (row.recipient != null) {
    if (!isAddress(row.recipient)) return fail('recipient')
    return { ok: true, values: { amount, token, recipient: row.recipient } }
  }
  if (!settlementWallet) return fail('recipient')
  return { ok: true, values: { amount, token, recipient: '' } }
}
