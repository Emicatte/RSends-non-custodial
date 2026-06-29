import {
  encodeEventTopics, encodeAbiParameters, zeroAddress, getAddress, type TransactionReceipt,
} from 'viem'
import { parsePaymentReceipt } from '@/lib/web3/receipt'
import { FEE_COLLECTOR } from '@/lib/web3/payTokens'
import { RSENDS_ROUTER_ABI } from '@/lib/rsendsRouterAbi'

const MERCHANT = '0x758A37F88D684e31D5a698514142f02A1bDD2c04'

// Real logs from the known-good Base Sepolia tx 0x082cc24a… (block 43365757):
//   Transfer payer→merchant  1.000000 USDC (0x0f4240)
//   Transfer payer→feeColl   0.150000 USDC (0x0249f0)
//   PaymentMade(invoiceId, merchant, payer, USDC, 1e6, 0.15e6, ts)
const REAL_TX_LOGS = [
  {
    address: '0x036cbd53842c5426634e7929541ec2318f3dcf7e',
    topics: [
      '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
      '0x0000000000000000000000000e056ce14d1d56f799588f4760e5c39d47f14b82',
      '0x000000000000000000000000758a37f88d684e31d5a698514142f02a1bdd2c04',
    ],
    data: '0x00000000000000000000000000000000000000000000000000000000000f4240',
  },
  {
    address: '0x036cbd53842c5426634e7929541ec2318f3dcf7e',
    topics: [
      '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
      '0x0000000000000000000000000e056ce14d1d56f799588f4760e5c39d47f14b82',
      '0x0000000000000000000000000e056ce14d1d56f799588f4760e5c39d47f14b82',
    ],
    data: '0x00000000000000000000000000000000000000000000000000000000000249f0',
  },
  {
    address: '0x2ec353815f2cd382628d0d399f8d80959c1758ca',
    topics: [
      '0xab7ccb7fe7da5e22a3f0005fe67aa4652cd87b623e108b54088210d0deb04947',
      '0x4b118d3424d9f6be29dbd649980307e58955559e49a537935bd09f0c3cce7369',
      '0x000000000000000000000000758a37f88d684e31d5a698514142f02a1bdd2c04',
      '0x0000000000000000000000000e056ce14d1d56f799588f4760e5c39d47f14b82',
    ],
    data:
      '0x000000000000000000000000036cbd53842c5426634e7929541ec2318f3dcf7e' +
      '00000000000000000000000000000000000000000000000000000000000f4240' +
      '00000000000000000000000000000000000000000000000000000000000249f0' +
      '000000000000000000000000000000000000000000000000000000006a3ec9da',
  },
]

function fixtureReceipt(logs: unknown[]): TransactionReceipt {
  return { logs } as unknown as TransactionReceipt
}

describe('parsePaymentReceipt — ERC-20 (real tx 0x082cc24a)', () => {
  const parsed = parsePaymentReceipt(fixtureReceipt(REAL_TX_LOGS), FEE_COLLECTOR)

  it('decodes the PaymentMade event', () => {
    expect(parsed).not.toBeNull()
    expect(parsed!.paymentMade.amount).toBe(1000000n)
    expect(parsed!.paymentMade.fee).toBe(150000n)
    expect(parsed!.paymentMade.merchant).toBe(getAddress(MERCHANT))
    expect(parsed!.paymentMade.token).toBe(getAddress('0x036CbD53842c5426634e7929541eC2318f3dCF7e'))
  })

  it('extracts principal → merchant', () => {
    expect(parsed!.principalTransfer?.value).toBe(1000000n)
    expect(parsed!.principalTransfer?.to).toBe(getAddress(MERCHANT))
  })

  it('extracts fee → feeCollector', () => {
    expect(parsed!.feeTransfer?.value).toBe(150000n)
    expect(parsed!.feeTransfer?.to).toBe(FEE_COLLECTOR)
  })
})

describe('parsePaymentReceipt — native ETH (no Transfer logs)', () => {
  const topics = encodeEventTopics({
    abi: RSENDS_ROUTER_ABI,
    eventName: 'PaymentMade',
    args: {
      invoiceId: `0x${'11'.repeat(32)}` as `0x${string}`,
      merchant: getAddress(MERCHANT),
      payer: getAddress('0x0e056Ce14D1D56f799588f4760E5C39d47f14B82'),
    },
  })
  const data = encodeAbiParameters(
    [{ type: 'address' }, { type: 'uint256' }, { type: 'uint256' }, { type: 'uint256' }],
    [zeroAddress, 10n ** 15n, 0n, 1_000_000n],
  )
  const parsed = parsePaymentReceipt(
    fixtureReceipt([{ address: '0x2ec353815f2cd382628d0d399f8d80959c1758ca', topics, data }]),
    FEE_COLLECTOR,
  )

  it('decodes PaymentMade with no transfer legs', () => {
    expect(parsed).not.toBeNull()
    expect(parsed!.paymentMade.token).toBe(zeroAddress)
    expect(parsed!.paymentMade.amount).toBe(10n ** 15n)
    expect(parsed!.principalTransfer).toBeUndefined()
    expect(parsed!.feeTransfer).toBeUndefined()
  })
})

describe('parsePaymentReceipt — no PaymentMade', () => {
  it('returns null', () => {
    expect(parsePaymentReceipt(fixtureReceipt([]), FEE_COLLECTOR)).toBeNull()
  })
})
