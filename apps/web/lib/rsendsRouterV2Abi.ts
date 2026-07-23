/**
 * RSendsRouterV2 — the fee-less, OWNERLESS single-merchant router (mainnet
 * design: payer→merchant only, one transfer per payment).
 *
 * Deliberately absent vs the v1 ABI: every `maxFee` argument (no fee exists
 * to cap), `quoteFee` (nothing to quote), the `fee` word in PaymentMade, and
 * the whole owner surface (owner/pause/setFeeConfig/setFeeCollector — no
 * privileged role exists on this contract). The checkout forks to this ABI
 * when the intent's `onchain.routerVersion` is 2.
 *
 * Mirror of packages/contracts/src/RSendsRouterV2.sol — keep in sync.
 */
export const RSENDS_ROUTER_V2_ABI = [
  {
    type: 'function',
    name: 'pay',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [],
  },
  {
    type: 'function',
    name: 'payWithPermit',
    stateMutability: 'nonpayable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'token', type: 'address' },
      { name: 'amount', type: 'uint256' },
      { name: 'deadline', type: 'uint256' },
      { name: 'v', type: 'uint8' },
      { name: 'r', type: 'bytes32' },
      { name: 's', type: 'bytes32' },
    ],
    outputs: [],
  },
  {
    type: 'function',
    name: 'payNative',
    stateMutability: 'payable',
    inputs: [
      { name: 'invoiceId', type: 'bytes32' },
      { name: 'merchant', type: 'address' },
      { name: 'amount', type: 'uint256' },
    ],
    outputs: [],
  },
  {
    type: 'event',
    name: 'PaymentMade',
    inputs: [
      { name: 'invoiceId', type: 'bytes32', indexed: true },
      { name: 'merchant', type: 'address', indexed: true },
      { name: 'payer', type: 'address', indexed: true },
      { name: 'token', type: 'address', indexed: false },
      { name: 'amount', type: 'uint256', indexed: false },
      { name: 'blockTimestamp', type: 'uint256', indexed: false },
    ],
  },
  { type: 'error', name: 'ZeroMerchant', inputs: [] },
  { type: 'error', name: 'ZeroAmount', inputs: [] },
  { type: 'error', name: 'ZeroToken', inputs: [] },
  { type: 'error', name: 'WrongNativeValue', inputs: [] },
  { type: 'error', name: 'NativeTransferFailed', inputs: [] },
] as const
