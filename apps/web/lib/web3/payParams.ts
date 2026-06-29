/**
 * lib/web3/payParams.ts — pure parse / validate / serialize for the /pay route.
 *
 * Turns the public payment-request query (`?token=&amount=&to=&ref=`) into a
 * typed PaymentRequest, and builds shareable links from the generator. No React,
 * no network, no wallet — pure functions so they're trivially testable.
 *
 * `invoiceId` is derived deterministically (never random) so the same link always
 * yields the same bytes32 across renders. The contract does not enforce invoiceId
 * uniqueness — it's an event tag — so a stable derivation is correct and avoids
 * re-render instability in the checkout.
 */
import {
  getAddress, isAddress, parseUnits, stringToHex, keccak256, type Address, type Hex,
} from 'viem'
import { getPayToken, type PayToken } from './payTokens'

export interface PaymentRequest {
  token: PayToken
  amountHuman: string
  amountBaseUnits: bigint
  merchant: Address
  ref?: string
  invoiceId: Hex
}

export interface PayParamsInput {
  token?: string | null
  amount?: string | null
  to?: string | null
  ref?: string | null
}

export type ParseResult =
  | { ok: true; request: PaymentRequest }
  | { ok: false; error: string }

/**
 * bytes32 invoice id from a human ref:
 *   - ≤ 31 UTF-8 bytes → right-padded ascii (legible in BaseScan),
 *   - longer           → keccak256 hash.
 */
export function encodeRef(ref: string): Hex {
  const r = ref.trim()
  const byteLen = new TextEncoder().encode(r).length
  if (byteLen === 0) throw new Error('encodeRef: empty ref')
  if (byteLen <= 31) return stringToHex(r, { size: 32 })
  return keccak256(stringToHex(r))
}

/** Deterministic invoiceId: encodeRef(ref) when present, else a stable hash of the request. */
export function deriveInvoiceId(
  ref: string | undefined,
  merchant: Address,
  token: Address,
  amountBaseUnits: bigint,
): Hex {
  if (ref) return encodeRef(ref)
  return keccak256(
    stringToHex(`rsends:${merchant.toLowerCase()}:${token.toLowerCase()}:${amountBaseUnits.toString()}`),
  )
}

export function parsePayParams(input: PayParamsInput): ParseResult {
  const tokenQ = input.token?.trim()
  if (!tokenQ) return { ok: false, error: 'Missing token.' }
  const token = getPayToken(tokenQ)
  if (!token) return { ok: false, error: `Unknown token "${tokenQ}".` }
  if (!token.enabled) return { ok: false, error: `${token.symbol} isn't available on this network yet.` }

  const toQ = input.to?.trim()
  if (!toQ || !isAddress(toQ)) return { ok: false, error: 'Missing or invalid merchant address.' }
  const merchant = getAddress(toQ)

  const amountQ = input.amount?.trim()
  if (!amountQ) return { ok: false, error: 'Missing amount.' }
  if (!/^\d+(\.\d+)?$/.test(amountQ)) return { ok: false, error: 'Invalid amount.' }
  let amountBaseUnits: bigint
  try {
    amountBaseUnits = parseUnits(amountQ, token.decimals)
  } catch {
    return { ok: false, error: 'Invalid amount.' }
  }
  if (amountBaseUnits <= 0n) return { ok: false, error: 'Amount must be greater than zero.' }
  const min = parseUnits(token.minAmount, token.decimals)
  if (amountBaseUnits < min) {
    return { ok: false, error: `Minimum amount is ${token.minAmount} ${token.symbol}.` }
  }

  const ref = input.ref?.trim() || undefined
  return {
    ok: true,
    request: {
      token,
      amountHuman: amountQ,
      amountBaseUnits,
      merchant,
      ref,
      invoiceId: deriveInvoiceId(ref, merchant, token.address, amountBaseUnits),
    },
  }
}

/** Build a shareable /pay link from generator inputs. `base` may be '' (relative) or an origin. */
export function buildPayUrl(
  input: { token: string; amount: string; to: string; ref?: string },
  base = '',
): string {
  const p = new URLSearchParams()
  p.set('token', input.token)
  p.set('amount', input.amount)
  p.set('to', input.to)
  if (input.ref && input.ref.trim()) p.set('ref', input.ref.trim())
  return `${base.replace(/\/$/, '')}/pay?${p.toString()}`
}
