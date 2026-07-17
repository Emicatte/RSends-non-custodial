/**
 * lib/rsendsSplitRouterAbi.ts — RSendsSplitRouter ABI (non-custodial split checkout)
 *
 * Minimal ABI for the ownerless, FEE-LESS split router: one payer transaction
 * fans the principal out to 2..20 recipients by basis points (sum must be
 * EXACTLY 10000 or the tx reverts — all-or-nothing, funds go payer →
 * recipient[i] direct, the contract never holds balance and has NO owner,
 * pause, whitelist or fee). Deployed alongside RSendsRouter, which handles
 * single-recipient payments unchanged.
 *
 * The payer passes ONLY total + sharesBps: the contract recomputes per-leg
 * amounts (floor division, remainder → recipients[0]) so what lands on-chain
 * is the deterministic split of what was signed — never client-side amounts.
 *
 * Exposed entrypoints:
 *   - paySplit(invoiceId, token, totalAmount, recipients, sharesBps)        → ERC20, needs prior approve(totalAmount)
 *   - paySplitWithPermit(…, deadline, v, r, s)                              → ERC2612 one-tx
 *   - paySplitNative(invoiceId, totalAmount, recipients, sharesBps) payable → native ETH (value = totalAmount)
 *   - SplitPaymentMade event (aggregate recipients/amounts vectors)         → indexed by the backend indexer
 *
 * `as const` keeps the tuple shape so wagmi can infer argument types.
 */

export const RSENDS_SPLIT_ROUTER_ABI = [
  // ── Split with a pre-approved ERC20 allowance ────────────────────────────
  {
    type: 'function',
    name: 'paySplit',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'token', type: 'address' },
      { name: 'totalAmount', type: 'uint256' },
      { name: 'recipients', type: 'address[]' },
      { name: 'sharesBps', type: 'uint16[]' },
    ],
    outputs: [],
  },
  // ── One-transaction split via EIP-2612 permit on totalAmount ─────────────
  {
    type: 'function',
    name: 'paySplitWithPermit',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'token', type: 'address' },
      { name: 'totalAmount', type: 'uint256' },
      { name: 'recipients', type: 'address[]' },
      { name: 'sharesBps', type: 'uint16[]' },
      { name: 'deadline', type: 'uint256' },
      { name: 'v', type: 'uint8' },
      { name: 'r', type: 'bytes32' },
      { name: 's', type: 'bytes32' },
    ],
    outputs: [],
  },
  // ── Native ETH split (value must equal totalAmount) ──────────────────────
  {
    type: 'function',
    name: 'paySplitNative',
    stateMutability: 'payable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'totalAmount', type: 'uint256' },
      { name: 'recipients', type: 'address[]' },
      { name: 'sharesBps', type: 'uint16[]' },
    ],
    outputs: [],
  },
  // ── Aggregate settlement event (one per split payment) ───────────────────
  {
    type: 'event',
    name: 'SplitPaymentMade',
    inputs: [
      { name: 'invoiceId', type: 'bytes32', indexed: true },
      { name: 'payer', type: 'address', indexed: true },
      { name: 'token', type: 'address', indexed: false },
      { name: 'totalAmount', type: 'uint256', indexed: false },
      { name: 'recipients', type: 'address[]', indexed: false },
      { name: 'amounts', type: 'uint256[]', indexed: false },
      { name: 'blockTimestamp', type: 'uint256', indexed: false },
    ],
  },
] as const
