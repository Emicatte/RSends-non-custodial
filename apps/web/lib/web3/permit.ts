/**
 * lib/web3/permit — EIP-2612 permit helpers for the hosted checkout.
 *
 * Permit capability is STATIC policy from the token registry, surfaced on
 * the intent as onchain.permitType ("eip2612" → permit flow, else
 * approve()+pay()). No runtime introspection. The EIP-712 domain version
 * also comes from the registry (Circle tokens = "2"). Extracted verbatim
 * from the previous monolithic /pay/[intentId] page so the typed data and
 * signature split are unit-testable.
 */

import { parseSignature, type Hex } from 'viem'

export const EIP2612_ABI = [
  { type: 'function', name: 'nonces', stateMutability: 'view',
    inputs: [{ name: 'owner', type: 'address' }], outputs: [{ name: '', type: 'uint256' }] },
  { type: 'function', name: 'name', stateMutability: 'view',
    inputs: [], outputs: [{ name: '', type: 'string' }] },
] as const

export interface PermitParams {
  tokenName: string
  version: string
  chainId: number
  token: `0x${string}`
  owner: `0x${string}`
  spender: `0x${string}`
  /** permit covers amount + fee (the payer's total) */
  value: bigint
  nonce: bigint
  deadline: bigint
}

export function buildPermitTypedData(params: PermitParams) {
  return {
    domain: {
      name: params.tokenName,
      version: params.version,
      chainId: params.chainId,
      verifyingContract: params.token,
    },
    types: {
      Permit: [
        { name: 'owner', type: 'address' },
        { name: 'spender', type: 'address' },
        { name: 'value', type: 'uint256' },
        { name: 'nonce', type: 'uint256' },
        { name: 'deadline', type: 'uint256' },
      ],
    },
    primaryType: 'Permit',
    message: {
      owner: params.owner,
      spender: params.spender,
      value: params.value,
      nonce: params.nonce,
      deadline: params.deadline,
    },
  } as const
}

export function splitPermitSignature(signature: Hex): {
  v: number
  r: Hex
  s: Hex
} {
  const { r, s, yParity } = parseSignature(signature)
  return { v: 27 + yParity, r, s }
}

/** Permit validity window: one hour from `nowMs`, in seconds. */
export function permitDeadline(nowMs: number): bigint {
  return BigInt(Math.floor(nowMs / 1000) + 3600)
}
