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
import { type ChainFamily, chainFor, decimalsFor } from '@/lib/createChains'
import { isTronAddress } from '@/lib/web3/tronAddress'
import {
  amountToBase,
  amountsToSharesBps,
  formatBase,
  onchainAmounts,
} from '@/lib/splitShares'

// The terms a row must meet to be repeatable are READ OFF the one chain/token
// table in lib/createChains.ts — the whole of it, not one entry — so the prefill
// gate and the create form cannot disagree about which networks are offerable,
// which tokens each enables, or how many decimals they carry. That table is
// itself pinned against the backend registry by createChainsRegistry.test.ts,
// which is what keeps this a mirror rather than a second source of truth.
//
// Repeat was Base Sepolia only until the network selector's chains reached it
// (PR #103 offered TRON in the create form and left Repeat behind). The
// consequence was a merchant reading "this network is no longer available" on a
// tron_nile row whose network works perfectly well — a refusal that named the
// wrong thing. Everything family-dependent below now routes on
// `chainFor(row.chain).family`.

const SPLIT_MIN = 2
const SPLIT_MAX = 20

/** The org's payout address per address family: `settlement_wallet` (EVM) and
 * `settlement_wallet_tron`. A record, not a single string, because the family
 * of the ROW decides which column is the implicit recipient — and the two are
 * never fallbacks for each other (the server refuses that with
 * SETTLEMENT_WALLET_TRON_MISSING). Total over `ChainFamily` on purpose: a third
 * family cannot be added without every caller being made to answer for it. */
export type SettlementWallets = Record<ChainFamily, string | null>

/** Initial values for CreatePaymentModal. Amounts are decimal strings in the
 * token's units — the form's own input format — never base units. */
export interface CreatePrefill {
  amount: string
  /** The network to open the form on — the source row's own, now that more than
   * one is offerable. Without it a TRON repeat would open on the default chain
   * carrying a T-address the form then (correctly) rejects. */
  chain: string
  token: string
  /** Single-payee override. '' means "use the org's payout address for this
   * chain" — the EVM settlement wallet or the TRON one, whichever the chain's
   * family points at — which is how the source intent itself resolved when it
   * stored no recipient. */
  recipient?: string
  /** Split legs in position order. The modal's last row auto-balances, so the
   * final amount is advisory there — it is supplied for completeness. */
  splitLegs?: { address: string; amount: string }[]
}

export type PrefillFailure =
  | 'chain'
  | 'token'
  | 'amount'
  | 'recipient'
  /** The row settles implicitly to a TRON payout address the org has not set.
   * Its own failure rather than a flavour of `recipient`, because the remedy is
   * a specific Settings field the merchant may not know exists — and creating
   * the request by hand would fail in exactly the same way. */
  | 'recipientTron'
  | 'split'

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
  wallets: SettlementWallets,
): PrefillResult {
  // 1. Chain. Offerable at all? /app is test-locked, so a mainnet row (or a
  //    chain the registry has dropped) has no network the form can target. The
  //    definition found here decides every family-dependent branch below.
  const chainDef = chainFor((row.chain ?? '').toLowerCase())
  if (!chainDef) return fail('chain')

  // 2. Token — must be enabled ON THIS CHAIN. Keyed by (chain, token), never a
  //    union across chains: USDT is a real create token on TRON Nile and still
  //    not offerable on Base Sepolia, and a union would quietly accept it.
  const token = row.currency
  const decimals = decimalsFor(chainDef.chain, token)
  if (decimals == null) return fail('token')

  // 3. Amount. Rejects float-repr artifacts, exponent notation and any
  //    precision the token cannot represent — never rounds to fit.
  const amount = String(row.amount)
  const totalBase = amountToBase(amount, decimals)
  if (totalBase == null) return fail('amount')

  // 4. Split, when the source had one.
  const legs = row.split
  if (legs && legs.length > 0) {
    // Gated, not assumed empty. A chain with no split router cannot have a
    // legitimate split row, and everything below this line is EVM-shaped —
    // viem `isAddress`, lowercase de-duplication, and the contract remainder
    // rule of a router TRON does not have. It must never run on base58.
    if (!chainDef.splitAvailable) return fail('split')
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
        chain: chainDef.chain,
        token,
        splitLegs: ordered.map((leg, i) => ({
          address: leg.address,
          amount: formatBase(amounts[i], decimals),
        })),
      },
    }
  }

  // 5. Single payee. A stored recipient is an explicit override and must be a
  //    valid address IN THIS CHAIN'S FAMILY — `isTronAddress` is the same
  //    base58check mirror the create form and the Settings payout field use, so
  //    there is one validator per family and not a fourth written here. The
  //    address is carried through verbatim: a T-address that lost its case
  //    would no longer be an address at all.
  const addressValidForChain = (addr: string) =>
    chainDef.family === 'tron' ? isTronAddress(addr) : isAddress(addr)
  if (row.recipient != null) {
    if (!addressValidForChain(row.recipient)) return fail('recipient')
    return {
      ok: true,
      values: { amount, chain: chainDef.chain, token, recipient: row.recipient },
    }
  }
  // No stored recipient: the source settled implicitly to the org's payout
  // address FOR THIS FAMILY, and is reproducible only while that column is set.
  if (!wallets[chainDef.family]) {
    return fail(chainDef.family === 'tron' ? 'recipientTron' : 'recipient')
  }
  return { ok: true, values: { amount, chain: chainDef.chain, token, recipient: '' } }
}
