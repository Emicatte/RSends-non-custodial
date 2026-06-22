/**
 * lib/rsendsRouterAbi.ts — RSendsRouter ABI (non-custodial checkout)
 *
 * Minimal ABI for the non-custodial payment router used by the payer
 * checkout page (app/pay/[intentId]/page.tsx). The payer calls this
 * contract directly so funds settle straight to the merchant — RSends
 * never custodies the funds.
 *
 * Exposed entrypoints (each pay fn takes maxFee — the payer's fee ceiling;
 * the tx reverts FeeTooHigh if quoteFee(token, amount) > maxFee):
 *   - pay(invoiceId, merchant, token, amount, maxFee)        → ERC20, needs prior approve()
 *   - payWithPermit(invoiceId, merchant, token, amount,      → ERC2612 one-tx
 *                   maxFee, deadline, v, r, s)
 *   - payNative(invoiceId, merchant, amount, maxFee) payable → native ETH (token == address(0))
 *   - quoteFee(token, amount) view                           → fee in token base units
 *   - PaymentMade event (incl. fee)                          → indexed by the backend indexer
 *
 * `as const` keeps the tuple shape so wagmi can infer function argument
 * and return types from this object.
 */

export const RSENDS_ROUTER_ABI = [
  // ── Pay with a pre-approved ERC20 allowance ──────────────────────────────
  {
    type: 'function',
    name: 'pay',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
      { name: 'maxFee', type: 'uint256' },
    ],
    outputs: [],
  },
  // ── Pay an ERC2612 permit token in a single tx ───────────────────────────
  {
    type: 'function',
    name: 'payWithPermit',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
      { name: 'maxFee', type: 'uint256' },
      { name: 'deadline', type: 'uint256' },
      { name: 'v', type: 'uint8' },
      { name: 'r', type: 'bytes32' },
      { name: 's', type: 'bytes32' },
    ],
    outputs: [],
  },
  // ── Pay native ETH (token == address(0)) ─────────────────────────────────
  {
    type: 'function',
    name: 'payNative',
    stateMutability: 'payable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'amount', type: 'uint256' },
      { name: 'maxFee', type: 'uint256' },
    ],
    outputs: [],
  },
  // ── Fee quote (token base units) — frontend reads this when the intent
  //    payload doesn't carry the fee (feeUnavailable) ─────────────────────────
  {
    type: 'function',
    name: 'quoteFee',
    stateMutability: 'view',
    inputs: [
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [{ name: 'fee', type: 'uint256' }],
  },
  // ── Settlement event — indexer flips the intent to "paid" on this ─────────
  {
    type: 'event',
    name: 'PaymentMade',
    anonymous: false,
    inputs: [
      { name: 'invoiceId', type: 'bytes32', indexed: true },
      { name: 'merchant', type: 'address', indexed: true },
      { name: 'payer', type: 'address', indexed: true },
      { name: 'token', type: 'address', indexed: false },
      { name: 'amount', type: 'uint256', indexed: false },
      { name: 'fee', type: 'uint256', indexed: false },
      { name: 'blockTimestamp', type: 'uint256', indexed: false },
    ],
  },
] as const
