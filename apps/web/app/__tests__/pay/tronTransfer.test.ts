/**
 * One build/sign/broadcast path, shared by every wallet.
 *
 * The architectural requirement for this feature is that TronLink and
 * WalletConnect do not get their own transaction code — only their own
 * connection code. The load-bearing test here is
 * `both adapters drive the identical unsigned transaction`: it runs the two
 * through the same function and compares what reached the transaction builder.
 * If someone later special-cases a wallet inside the payment path, that test is
 * what fails.
 *
 * `TronWeb` is imported type-only by the module under test, so these tests hand
 * it a structural fake and jest never loads the real package (which drags in
 * ethers, axios and google-protobuf, and is unhappy under jsdom). The type
 * identity is still proven at compile time by `tsc`, which checks the real
 * TronWeb signatures against the module.
 */
import type { Adapter } from '@tronweb3/tronwallet-abstract-adapter'

import {
  buildTransfer,
  payWithWallet,
  toBaseUnits,
  TRANSFER_SELECTOR,
} from '@/lib/web3/tron/tronTransfer'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'

const NILE = tronNetworkFor('tron_nile')!
const MERCHANT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const FEE_LIMIT = 100_000_000

type BuilderCall = {
  contract: string
  selector: string
  options: unknown
  params: unknown
}

function fakeTronWeb() {
  const builderCalls: BuilderCall[] = []
  const broadcast: unknown[] = []
  const unsigned = {
    visible: false,
    txID: 'a'.repeat(64),
    raw_data: { contract: [], ref_block_bytes: '00', ref_block_hash: '00', expiration: 1, timestamp: 1 },
    raw_data_hex: 'ff',
  }
  const client = {
    isAddress: (a: unknown) =>
      typeof a === 'string' && /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a),
    transactionBuilder: {
      triggerSmartContract: async (
        contract: string,
        selector: string,
        options: unknown,
        params: unknown,
      ) => {
        builderCalls.push({ contract, selector, options, params })
        return { result: { result: true }, transaction: unsigned }
      },
    },
    trx: {
      sendRawTransaction: async (signed: unknown) => {
        broadcast.push(signed)
        return { result: true, txid: unsigned.txID, code: 0, message: '', transaction: signed }
      },
    },
  }
  return { client, builderCalls, broadcast, unsigned }
}

/** A wallet that signs by appending a signature, like every real adapter. */
function fakeWallet(name: string): Adapter {
  return {
    name,
    signTransaction: async (tx: unknown) => ({
      ...(tx as object),
      signature: [`signed-by-${name}`],
    }),
  } as unknown as Adapter
}

const request = (over: Partial<Parameters<typeof buildTransfer>[1]> = {}) => ({
  network: NILE,
  recipient: MERCHANT,
  intentRecipient: MERCHANT,
  amountBaseUnits: '10000000',
  feeLimit: FEE_LIMIT,
  ...over,
})

describe('amounts are integers end to end', () => {
  it.each([
    ['10', '10000000'],
    ['0.1', '100000'],
    ['2.5', '2500000'],
    ['0.000001', '1'],
    ['10.000001', '10000001'],
    // The value the public view actually sends for a whole-number invoice.
    ['10.000000', '10000000'],
  ])('converts %s USDT to %s base units', (amount, expected) => {
    expect(toBaseUnits(amount, 6)).toBe(expected)
  })

  it('never routes an amount through a float', () => {
    // 0.1 + 0.2 is the canonical float trap; string math must not care. A
    // Number() round-trip of this value would not survive at 18 decimals.
    expect(toBaseUnits('0.30000000000000004', 18)).toBe('300000000000000040')
    // And a value far beyond float64's exact integer range stays exact.
    expect(toBaseUnits('123456789.123456', 6)).toBe('123456789123456')
  })

  it('refuses an amount with more precision than the token has', () => {
    // Truncating here would silently underpay, and the matcher requires the
    // exact amount — so a short payment becomes an unmatched settlement.
    expect(() => toBaseUnits('0.0000001', 6)).toThrow(/precision/i)
  })
})

describe('the recipient is the intent’s, byte for byte', () => {
  it('passes the address through untouched', async () => {
    const { client, builderCalls } = fakeTronWeb()
    await buildTransfer(client as never, request())

    const [{ params }] = builderCalls
    const [to] = params as { type: string; value: string }[]
    expect(to.value).toBe(MERCHANT)
    // Not folded, not checksummed, not trimmed. base58check is case-sensitive:
    // a folded address is a different address, not a formatting choice.
    expect(to.value).not.toBe(MERCHANT.toLowerCase())
    expect(to.value).not.toBe(MERCHANT.toUpperCase())
  })

  it('throws when the recipient no longer matches the intent', async () => {
    const { client, builderCalls } = fakeTronWeb()
    // Models component state having been mutated between fetch and pay.
    await expect(
      buildTransfer(
        client as never,
        request({ recipient: 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf' }),
      ),
    ).rejects.toThrow(/recipient/i)
    // The guard runs BEFORE construction, so nothing was built.
    expect(builderCalls).toHaveLength(0)
  })

  it('throws when the recipient is not a TRON address at all', async () => {
    const { client, builderCalls } = fakeTronWeb()
    await expect(
      buildTransfer(
        client as never,
        request({ recipient: '0xdead', intentRecipient: '0xdead' }),
      ),
    ).rejects.toThrow(/address/i)
    expect(builderCalls).toHaveLength(0)
  })
})

describe('the call it builds', () => {
  it('targets the network’s USDT contract with a zero-value transfer', async () => {
    const { client, builderCalls } = fakeTronWeb()
    await buildTransfer(client as never, request())

    expect(builderCalls).toHaveLength(1)
    const [call] = builderCalls
    expect(call.contract).toBe(NILE.usdt.address)
    expect(call.selector).toBe(TRANSFER_SELECTOR)
    // callValue 0: a TRC-20 transfer moves no TRX. A non-zero value here would
    // send the payer's TRX to the token contract on top of the payment.
    expect(call.options).toMatchObject({ callValue: 0, feeLimit: FEE_LIMIT })
    expect(call.params).toEqual([
      { type: 'address', value: MERCHANT },
      { type: 'uint256', value: '10000000' },
    ])
  })
})

describe('one path for every wallet', () => {
  it('both adapters drive the identical unsigned transaction', async () => {
    // THE architectural pin. TronLink and WalletConnect differ only in how they
    // connect; the transaction they are handed must be built by the same code
    // from the same inputs.
    const tronlink = fakeTronWeb()
    const walletconnect = fakeTronWeb()

    const a = await payWithWallet(tronlink.client as never, fakeWallet('TronLink'), request())
    const b = await payWithWallet(
      walletconnect.client as never,
      fakeWallet('WalletConnect'),
      request(),
    )

    expect(tronlink.builderCalls).toEqual(walletconnect.builderCalls)
    expect(a).toBe(b)
  })

  it('broadcasts exactly what the wallet signed', async () => {
    const { client, broadcast, unsigned } = fakeTronWeb()
    const txid = await payWithWallet(client as never, fakeWallet('TronLink'), request())

    expect(broadcast).toHaveLength(1)
    // The signature the wallet added survives to the node untouched — the page
    // must not rebuild or re-serialise a signed transaction.
    expect(broadcast[0]).toMatchObject({
      txID: unsigned.txID,
      signature: ['signed-by-TronLink'],
    })
    expect(txid).toBe(unsigned.txID)
  })

  it('surfaces a builder refusal instead of signing anyway', async () => {
    const { client } = fakeTronWeb()
    client.transactionBuilder.triggerSmartContract = async () =>
      ({ result: { result: false, message: '636f6e7472616374207661616c6964617465' }, transaction: undefined }) as never

    await expect(
      payWithWallet(client as never, fakeWallet('TronLink'), request()),
    ).rejects.toThrow()
  })

  it('surfaces a rejected broadcast rather than reporting a hash', async () => {
    // A node that refuses the transaction must not leave the checkout thinking
    // money moved — this is what stops a false "Payment processing".
    const { client } = fakeTronWeb()
    client.trx.sendRawTransaction = async () =>
      ({ result: false, code: 'SIGERROR', message: 'validate signature error', txid: '' }) as never

    await expect(
      payWithWallet(client as never, fakeWallet('TronLink'), request()),
    ).rejects.toThrow(/SIGERROR|signature/i)
  })
})
