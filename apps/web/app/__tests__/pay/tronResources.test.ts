/**
 * Resource maths, where the failure mode is asking a payer to sign a
 * transaction that cannot execute.
 *
 * The centrepiece is `treats_absent_resource_fields_as_zero`. tronweb declares
 * every field of AccountResourceMessage as a non-optional number, but TronGrid
 * omits zero-valued fields — so an account with no energy has no EnergyLimit
 * key at all. Read as a number that is `undefined`, and `undefined - 0` is NaN,
 * which compares false against every threshold and quietly passes the check it
 * should have failed.
 */
import {
  FEE_LIMIT_CEILING_SUN,
  FEE_LIMIT_MARGIN,
  SIGNATURE_OVERHEAD_BYTES,
  bandwidthFor,
  estimateTransferEnergy,
  feeLimitFor,
  quoteResources,
  readResourcePrices,
  usdtBalanceOf,
} from '@/lib/web3/tron/tronResources'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'

const NILE = tronNetworkFor('tron_nile')!
const PAYER = 'TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb'
const MERCHANT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'

const PRICES = { energyFee: 210, bandwidthFee: 1000 }

describe('absent means none, never unknown', () => {
  it('treats absent resource fields as zero', () => {
    // Exactly what TronGrid returns for a fresh account: an object with the
    // zero-valued keys simply missing.
    const quote = quoteResources({
      energyNeeded: 30_000,
      rawDataHex: 'ab'.repeat(200),
      resources: {},
      balanceSun: 0,
      prices: PRICES,
    })

    expect(quote.energyAvailable).toBe(0)
    expect(quote.bandwidthAvailable).toBe(0)
    // NaN would make this false and wave the payment through.
    expect(Number.isNaN(quote.costSun)).toBe(false)
    expect(quote.costSun).toBeGreaterThan(0)
    expect(quote.covered).toBe(false)
  })

  it('never reports negative headroom when usage exceeds the limit', () => {
    const quote = quoteResources({
      energyNeeded: 10,
      rawDataHex: 'ab',
      resources: { EnergyLimit: 5, EnergyUsed: 50, freeNetLimit: 1, freeNetUsed: 9 },
      balanceSun: 10 ** 9,
      prices: PRICES,
    })
    expect(quote.energyAvailable).toBe(0)
    expect(quote.bandwidthAvailable).toBe(0)
  })
})

describe('shortfalls are priced across both budgets', () => {
  it('counts bandwidth shortfall, not only energy', () => {
    // A payer with plenty of staked energy and no bandwidth still burns TRX.
    // Pricing only energy would report this payment as free.
    const quote = quoteResources({
      energyNeeded: 30_000,
      rawDataHex: 'ab'.repeat(150),
      resources: { EnergyLimit: 1_000_000, EnergyUsed: 0 },
      balanceSun: 10 ** 9,
      prices: PRICES,
    })

    expect(quote.energyAvailable).toBeGreaterThan(quote.energyNeeded)
    expect(quote.bandwidthAvailable).toBe(0)
    expect(quote.costSun).toBe(quote.bandwidthNeeded * PRICES.bandwidthFee)
    expect(quote.costSun).toBeGreaterThan(0)
  })

  it('charges nothing when staked resources cover both', () => {
    const quote = quoteResources({
      energyNeeded: 30_000,
      rawDataHex: 'ab'.repeat(150),
      resources: {
        EnergyLimit: 1_000_000,
        EnergyUsed: 0,
        freeNetLimit: 5_000,
        freeNetUsed: 0,
      },
      balanceSun: 0,
      prices: PRICES,
    })
    expect(quote.costSun).toBe(0)
    // And zero TRX is fine when nothing has to be burned.
    expect(quote.covered).toBe(true)
  })

  it('adds free and staked bandwidth together', () => {
    const quote = quoteResources({
      energyNeeded: 0,
      rawDataHex: 'ab'.repeat(150),
      resources: {
        freeNetLimit: 100,
        freeNetUsed: 40,
        NetLimit: 500,
        NetUsed: 100,
      },
      balanceSun: 0,
      prices: PRICES,
    })
    expect(quote.bandwidthAvailable).toBe(60 + 400)
  })

  it('measures bandwidth on the signed size, not the unsigned bytes', () => {
    const hex = 'ab'.repeat(200)
    expect(bandwidthFor(hex)).toBe(200 + SIGNATURE_OVERHEAD_BYTES)
  })
})

describe('fee limit', () => {
  it('is the estimate times the margin', () => {
    expect(feeLimitFor(10_000, PRICES)).toBe(
      Math.ceil(10_000 * PRICES.energyFee * FEE_LIMIT_MARGIN),
    )
  })

  it('never exceeds the ceiling, however wrong the estimate is', () => {
    // A runaway estimate must not become a runaway authorisation.
    expect(feeLimitFor(50_000_000, PRICES)).toBe(FEE_LIMIT_CEILING_SUN)
    expect(feeLimitFor(Number.MAX_SAFE_INTEGER, PRICES)).toBe(FEE_LIMIT_CEILING_SUN)
  })
})

describe('chain reads', () => {
  it('reads prices as parameter keys', async () => {
    const tronWeb = {
      trx: {
        getChainParameters: async () => [
          { key: 'getEnergyFee', value: 420 },
          { key: 'getTransactionFee', value: 1000 },
          { key: 'getCreateAccountFee', value: 100000 },
        ],
      },
    }
    await expect(readResourcePrices(tronWeb as never)).resolves.toEqual({
      energyFee: 420,
      bandwidthFee: 1000,
    })
  })

  it('throws rather than defaulting when a price is missing', async () => {
    // A hardcoded fallback would under-price the transaction and let a payer
    // sign something that cannot execute.
    const tronWeb = {
      trx: { getChainParameters: async () => [{ key: 'getTransactionFee', value: 1000 }] },
    }
    await expect(readResourcePrices(tronWeb as never)).rejects.toThrow(/getEnergyFee/)
  })

  it('decodes the USDT balance from the constant call', async () => {
    const tronWeb = {
      transactionBuilder: {
        triggerConstantContract: async () => ({
          result: { result: true },
          constant_result: ['0000000000000000000000000000000000000000000000000000000000989680'],
        }),
      },
    }
    // 0x989680 = 10_000_000 = 10 USDT at 6 decimals.
    await expect(usdtBalanceOf(tronWeb as never, NILE, PAYER)).resolves.toBe(10_000_000n)
  })

  it('estimates energy against the exact transfer being paid', async () => {
    let seen: unknown
    const tronWeb = {
      transactionBuilder: {
        triggerConstantContract: async (
          contract: string,
          selector: string,
          _o: unknown,
          params: unknown,
          issuer: string,
        ) => {
          seen = { contract, selector, params, issuer }
          return { result: { result: true }, energy_required: 31_895 }
        },
      },
    }

    const energy = await estimateTransferEnergy(
      tronWeb as never,
      NILE,
      PAYER,
      MERCHANT,
      '10000000',
    )

    expect(energy).toBe(31_895)
    // The simulation must be the payment, not a generic transfer: energy cost
    // depends on the recipient's current balance slot.
    expect(seen).toEqual({
      contract: NILE.usdt.address,
      selector: 'transfer(address,uint256)',
      params: [
        { type: 'address', value: MERCHANT },
        { type: 'uint256', value: '10000000' },
      ],
      issuer: PAYER,
    })
  })

  it('surfaces a rejected simulation instead of inventing a fee', async () => {
    const tronWeb = {
      transactionBuilder: {
        triggerConstantContract: async () => ({
          result: { result: false, message: 'REVERT opcode executed' },
        }),
      },
    }
    await expect(
      estimateTransferEnergy(tronWeb as never, NILE, PAYER, MERCHANT, '10000000'),
    ).rejects.toThrow(/estimate/i)
  })
})
