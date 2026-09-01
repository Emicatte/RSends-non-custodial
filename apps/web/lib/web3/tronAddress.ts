/**
 * lib/web3/tronAddress.ts — TRON base58check address validation, client-side.
 *
 * A deliberate MIRROR of the server validator in
 * `services/backend/app/security/input_validator.py` (`_tron_decode` /
 * `is_tron_address`). The server stays the authority: nothing here relaxes a
 * check it makes, and a value this file accepts is still validated again on
 * PATCH.
 *
 * WHY A SECOND CHECKSUM EXISTS AT ALL. The Python decoder's docstring says a
 * second decoder is a second checksum implementation, and it is right — so the
 * scope here is kept as narrow as the warning demands. This module only ever
 * ANSWERS A BOOLEAN. It never decodes an address for a caller, never converts
 * between the base58 and hex forms, never normalizes, and nothing downstream
 * consumes anything but its yes/no. A subtly-wrong implementation can therefore
 * only ever reject a good address (visible immediately, on the merchant's own
 * screen) — it cannot mint a payload that credits an address nobody controls.
 *
 * The alternative was a shape-only regex, and it is worse where it counts: a
 * single mistyped character passes the shape and fails the checksum, and the
 * settlement form funnels every server rejection into "Couldn't save. Try
 * again." A merchant would be told to retry a payout address that will never be
 * accepted, with no hint that the problem is one wrong letter.
 *
 * Stdlib + viem only. `sha256` comes from viem, already a direct dependency of
 * this app and already imported by the settings form — no new package, and no
 * phantom dependency on the hoisted-but-undeclared bs58check / @scure/base.
 */

import { sha256 } from 'viem'

// base58's alphabet omits `0 O I l`. That is why lowercasing a T-address does
// not merely change it — it can produce characters that are not base58 at all.
const B58_ALPHABET =
  '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

// 'T' + 33 base58 chars. Mirrors `_TRON_ADDR_RE`.
const TRON_SHAPE = /^T[1-9A-HJ-NP-Za-km-z]{33}$/

// The payload byte every mainnet T-address decodes to (`_TRON_MAINNET_PREFIX`).
const MAINNET_PREFIX = 0x41

/**
 * TRON's analogue of the EVM zero address: `0x41` + 20 zero bytes,
 * base58check-encoded. Its checksum is VALID, so `isTronAddress` accepts it and
 * only an explicit comparison rejects it — exactly as on the server
 * (`TRON_ZERO_ADDRESS` in input_validator.py). Comparing the string is exact:
 * base58check is canonical, so precisely one string encodes that payload.
 */
export const TRON_ZERO_ADDRESS = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb'

/**
 * Shape only, no checksum. Used to tell "you pasted a TRON address into the EVM
 * field" apart from "that is not an address" — so the error can name the chain
 * the merchant probably meant. Never use this to accept a payout address.
 */
export function looksLikeTronAddress(address: string): boolean {
  return TRON_SHAPE.test(address)
}

/**
 * True iff `address` is a valid TRON **mainnet** base58check address.
 *
 * Full checksum verification, not a shape check: a single mistyped character
 * changes the payload and fails the double-SHA256 tail. That matters because
 * this is a payout address — a bad checksum means funds sent nowhere, and TRON
 * is a watch-only chain here, with no contract in the path to reject it for us.
 */
export function isTronAddress(address: string): boolean {
  if (!TRON_SHAPE.test(address)) return false

  let n = 0n
  for (const ch of address) {
    n = n * 58n + BigInt(B58_ALPHABET.indexOf(ch)) // regex already fenced the alphabet
  }
  // Would not fit the 25-byte base58check envelope. Mirrors `bit_length() > 200`.
  if (n >= 1n << 200n) return false

  const raw = new Uint8Array(25) // 25 bytes = 200 bits, so the value fits exactly
  for (let i = 24; i >= 0; i--) {
    raw[i] = Number(n & 0xffn)
    n >>= 8n
  }

  if (raw[0] !== MAINNET_PREFIX) return false

  const checksum = sha256(sha256(raw.subarray(0, 21), 'bytes'), 'bytes')
  return (
    checksum[0] === raw[21] &&
    checksum[1] === raw[22] &&
    checksum[2] === raw[23] &&
    checksum[3] === raw[24]
  )
}
