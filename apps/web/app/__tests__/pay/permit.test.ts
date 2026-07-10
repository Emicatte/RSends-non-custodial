/**
 * lib/web3/permit — EIP-2612 permit helpers extracted from the hosted
 * checkout: typed-data builder (exact struct the wallet signs), signature
 * split (v = 27 + yParity, verified against viem's parseSignature on a real
 * 65-byte signature), and the 1-hour deadline.
 */
import { serializeSignature } from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import {
  EIP2612_ABI,
  buildPermitTypedData,
  permitDeadline,
  splitPermitSignature,
} from '@/lib/web3/permit'

const OWNER = '0x1111111111111111111111111111111111111111' as const
const SPENDER = '0x2Ec353815F2Cd382628d0D399F8d80959C1758CA' as const
const TOKEN = '0x036CbD53842c5426634e7929541eC2318f3dCF7e' as const

describe('buildPermitTypedData', () => {
  it('builds the exact EIP-712 struct the token verifies', () => {
    const typed = buildPermitTypedData({
      tokenName: 'USDC',
      version: '2',
      chainId: 84532,
      token: TOKEN,
      owner: OWNER,
      spender: SPENDER,
      value: 50_600_000n,
      nonce: 7n,
      deadline: 1_800_000_000n,
    })
    expect(typed).toEqual({
      domain: {
        name: 'USDC',
        version: '2',
        chainId: 84532,
        verifyingContract: TOKEN,
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
        owner: OWNER,
        spender: SPENDER,
        value: 50_600_000n,
        nonce: 7n,
        deadline: 1_800_000_000n,
      },
    })
  })
})

describe('splitPermitSignature', () => {
  it('splits a real signature into v/r/s with v = 27 + yParity', async () => {
    const account = privateKeyToAccount(
      '0x0123456789012345678901234567890123456789012345678901234567890123',
    )
    const typed = buildPermitTypedData({
      tokenName: 'USDC',
      version: '2',
      chainId: 84532,
      token: TOKEN,
      owner: account.address,
      spender: SPENDER,
      value: 1n,
      nonce: 0n,
      deadline: 1_800_000_000n,
    })
    const signature = await account.signTypedData(typed)

    const { v, r, s } = splitPermitSignature(signature)
    expect(v === 27 || v === 28).toBe(true)
    expect(r).toMatch(/^0x[0-9a-f]{64}$/)
    expect(s).toMatch(/^0x[0-9a-f]{64}$/)
    // Round-trip: v/r/s reassemble to the original signature bytes.
    expect(
      serializeSignature({ r, s, yParity: v - 27 }),
    ).toBe(signature)
  })
})

describe('permitDeadline', () => {
  it('is one hour from the given clock, in seconds, as bigint', () => {
    expect(permitDeadline(1_800_000_000_000)).toBe(1_800_003_600n)
  })
})

describe('EIP2612_ABI', () => {
  it('exposes the nonces and name reads the permit flow needs', () => {
    const names = EIP2612_ABI.map((f) => f.name)
    expect(names).toEqual(['nonces', 'name'])
  })
})
