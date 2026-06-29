/**
 * lib/web3/receipt.ts — parse an RSendsRouter payment receipt client-side.
 *
 * Decodes the settlement `PaymentMade` event plus the two ERC-20 `Transfer` logs
 * so the confirmed UI can prove what actually happened on-chain:
 *   principal → merchant   and   fee → feeCollector
 * (native ETH has no Transfer logs — the legs are undefined and the UI falls back
 * to the PaymentMade amount/fee).
 */
import {
  parseEventLogs, getAddress, erc20Abi, type TransactionReceipt, type Address, type Hex,
} from 'viem'
import { RSENDS_ROUTER_ABI } from '@/lib/rsendsRouterAbi'

export interface PaymentMadeArgs {
  invoiceId: Hex
  merchant: Address
  payer: Address
  token: Address
  amount: bigint
  fee: bigint
  blockTimestamp: bigint
}

export interface TransferLeg {
  from: Address
  to: Address
  value: bigint
}

export interface ParsedPayment {
  paymentMade: PaymentMadeArgs
  /** payer → merchant (ERC-20 only). */
  principalTransfer?: TransferLeg
  /** payer → feeCollector (ERC-20 only; absent when fee is 0 or native). */
  feeTransfer?: TransferLeg
}

export function parsePaymentReceipt(
  receipt: TransactionReceipt,
  feeCollector: Address,
): ParsedPayment | null {
  const events = parseEventLogs({
    abi: RSENDS_ROUTER_ABI,
    eventName: 'PaymentMade',
    logs: receipt.logs,
  })
  const pm = events[0]
  if (!pm) return null
  const paymentMade = pm.args as unknown as PaymentMadeArgs

  const transfers = parseEventLogs({ abi: erc20Abi, eventName: 'Transfer', logs: receipt.logs })
  const fc = getAddress(feeCollector)
  const merchant = getAddress(paymentMade.merchant)

  let principalTransfer: TransferLeg | undefined
  let feeTransfer: TransferLeg | undefined
  for (const t of transfers) {
    const args = t.args as { from: Address; to: Address; value: bigint }
    const to = getAddress(args.to)
    const leg: TransferLeg = { from: getAddress(args.from), to, value: args.value }
    if (to === fc) feeTransfer = leg
    else if (to === merchant) principalTransfer = leg
  }

  return { paymentMade, principalTransfer, feeTransfer }
}
