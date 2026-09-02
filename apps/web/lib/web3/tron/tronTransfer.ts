/**
 * lib/web3/tron/tronTransfer — build, sign and broadcast a TRC-20 transfer.
 * ONE implementation, for every wallet.
 *
 * This is the architectural centre of the TRON checkout. TronLink and
 * WalletConnect differ only in how a session is established; from the moment
 * there is a connected `Adapter`, they run through here identically. There is
 * no wallet-specific transaction code anywhere in this app, and
 * `app/__tests__/pay/tronTransfer.test.ts` pins that by driving two different
 * adapters through `payWithWallet` and comparing what reached the builder.
 *
 * That this can be one path is not a hope, it is a type-level fact. The base
 * `Adapter` declares `signTransaction(transaction: Transaction):
 * Promise<SignedTransaction>` as ABSTRACT — so every adapter has the same
 * signature — and it re-exports both of those types straight from tronweb:
 *
 *     export type { Transaction, SignedTransaction } from 'tronweb/lib/esm/types/Transaction'
 *
 * so what `triggerSmartContract` returns, what a wallet signs, and what
 * `sendRawTransaction` accepts are the same nominal types, with no cast
 * anywhere in the chain below.
 *
 * WHY THE TRONWEB IMPORT IS TYPE-ONLY. `import type` is erased at compile time,
 * so this module adds nothing to the bundle and jest never loads tronweb (which
 * drags in ethers, axios and google-protobuf). The runtime instance is created
 * by `tronClient.ts`, which dynamic-imports the package inside the TRON branch
 * so the EVM route's bundle is byte-unchanged.
 */

import type { Adapter } from '@tronweb3/tronwallet-abstract-adapter'
import type { TronWeb } from 'tronweb'
import { parseUnits } from 'viem'

import { isTronAddress } from '../tronAddress'
import type { TronNetworkConfig } from './tronNetwork'

/**
 * The TRC-20 entry point. Written out rather than assembled, because this exact
 * string is what the node hashes to pick the function — a typo would build a
 * call to a selector no contract implements, which fails only on chain.
 */
export const TRANSFER_SELECTOR = 'transfer(address,uint256)'

export interface TransferRequest {
  network: TronNetworkConfig
  /**
   * The connected wallet, which becomes the transaction's `owner_address`.
   *
   * Required, and passed explicitly, because tronweb otherwise defaults
   * `issuerAddress` to `this.tronWeb.defaultAddress.hex` — and our client is
   * built with a host and no private key, so that value is `false`. The
   * transaction would carry no valid owner and be rejected by the node.
   */
  payer: string
  /** The address the transfer will credit. Must equal `intentRecipient`. */
  recipient: string
  /**
   * The recipient as it arrived from the backend, carried separately so the two
   * can be compared immediately before construction. They are the same value in
   * normal operation; keeping both is what makes the guard below meaningful
   * rather than a comparison of a variable with itself.
   */
  intentRecipient: string
  /** Integer base units, as a decimal string. Never a number. */
  amountBaseUnits: string
  feeLimit: number
}

/**
 * A decimal token amount to integer base units, as a string.
 *
 * viem's `parseUnits` is pure string math over BigInt, which is the whole
 * point: `amount_exact` arrives as a string precisely so no float ever touches
 * it, and re-introducing one here would defeat the backend's care. The matcher
 * compares the settled value to `to_base_units(intent.amount, decimals)`
 * exactly, so a single unit of drift is an unmatched payment.
 *
 * Excess precision throws rather than truncating. Truncating would underpay by
 * a hair and produce a settlement the matcher cannot bind — money at the
 * merchant with nothing to reconcile it against. The backend refuses the same
 * case at create time with AMOUNT_PRECISION_EXCEEDED.
 */
export function toBaseUnits(amount: string, decimals: number): string {
  const [, fraction = ''] = amount.split('.')
  if (fraction.length > decimals) {
    throw new Error(
      `amount ${amount} has more precision than the token's ${decimals} decimals`,
    )
  }
  return parseUnits(amount, decimals).toString()
}

/**
 * Build the unsigned transfer.
 *
 * The recipient checks run BEFORE anything is constructed, and they are the
 * last line of defence on the one value that decides where the money goes. The
 * address is never normalised on the way through: base58check is case
 * sensitive, so folding a T-address does not tidy it, it changes which account
 * it names — and TRON is watch-only here, with no contract in the path to
 * reject a wrong payee for us.
 */
export async function buildTransfer(tronWeb: TronWeb, req: TransferRequest) {
  if (req.recipient !== req.intentRecipient) {
    throw new Error(
      'refusing to build: recipient does not match the recipient on the payment intent',
    )
  }
  if (!isTronAddress(req.recipient) || !tronWeb.isAddress(req.recipient)) {
    throw new Error(`refusing to build: ${req.recipient} is not a TRON address`)
  }

  const built = await tronWeb.transactionBuilder.triggerSmartContract(
    req.network.usdt.address,
    TRANSFER_SELECTOR,
    // callValue 0 — a TRC-20 transfer moves no TRX. Anything else would send
    // the payer's TRX to the token contract on top of the payment.
    { feeLimit: req.feeLimit, callValue: 0 },
    [
      { type: 'address', value: req.recipient },
      { type: 'uint256', value: req.amountBaseUnits },
    ],
    req.payer,
  )

  if (!built?.result?.result || !built.transaction) {
    // `message` is hex-encoded revert text when the node has one to give.
    throw new Error(
      `the node refused to build the transfer${
        built?.result?.message ? `: ${built.result.message}` : ''
      }`,
    )
  }
  return built.transaction
}

/**
 * Hand the signed transaction to the node and return its id.
 *
 * A refusal throws. It must never resolve with something hash-shaped, because
 * the checkout treats a returned id as "the payer's money is in flight" and
 * moves to the processing screen — saying that when the node rejected the
 * transaction would be the worst lie this flow can tell.
 */
export async function broadcast(tronWeb: TronWeb, signed: Awaited<ReturnType<Adapter['signTransaction']>>) {
  const receipt = await tronWeb.trx.sendRawTransaction(signed)
  if (!receipt?.result) {
    throw new Error(
      `the node rejected the transfer: ${receipt?.code ?? 'unknown'}${
        receipt?.message ? ` ${receipt.message}` : ''
      }`,
    )
  }
  return receipt.txid
}

/**
 * The whole path, for any wallet: build → sign → broadcast → transaction id.
 *
 * `wallet` is the abstract `Adapter`, never a concrete adapter type. That is
 * what makes this function wallet-agnostic, and narrowing the parameter to a
 * specific adapter is the change that would break the architecture.
 */
export async function payWithWallet(
  tronWeb: TronWeb,
  wallet: Adapter,
  req: TransferRequest,
): Promise<string> {
  const unsigned = await buildTransfer(tronWeb, req)
  const signed = await wallet.signTransaction(unsigned)
  return broadcast(tronWeb, signed)
}
