/**
 * lib/web3/tron/tronResources — can this payer actually afford to send this?
 *
 * TRON does not charge gas the way an EVM chain does. A transaction consumes
 * ENERGY (for contract execution) and BANDWIDTH (for its serialized bytes).
 * Each can be covered by staked resources the account already holds, and
 * whatever is not covered is burned as TRX. So "do they have enough TRX" is not
 * a balance comparison — it is a shortfall calculation across two independent
 * budgets, and getting it wrong means asking a payer to sign a transaction that
 * cannot execute. The wallet will happily sign it, the node will accept it, and
 * it will fail on chain having burned the fee.
 *
 * The single most dangerous detail here is that TRONGRID OMITS ZERO-VALUED
 * FIELDS from `getAccountResources`, while tronweb's `AccountResourceMessage`
 * declares every field as a non-optional `number`. The type lies. An account
 * with no energy has no `EnergyLimit` key at all, so anything that reads it as
 * a number gets `undefined` — and `undefined - 0` is `NaN`, which compares
 * false against every threshold and silently passes the check it was supposed
 * to fail. Every read below is therefore coalesced to zero, and that is what
 * `?? 0` means everywhere in this file: absent means none, never unknown.
 */

import type { TronWeb } from 'tronweb'

import { TRANSFER_SELECTOR } from './tronTransfer'
import type { TronNetworkConfig } from './tronNetwork'

/**
 * The estimate reflects the chain's state at estimation time, and that state
 * moves: a transfer to an address holding no USDT costs roughly twice one to an
 * address that already holds some, because the token contract has to allocate a
 * new balance slot. The recipient's balance can change between our estimate and
 * the payer's signature. 1.5x absorbs that without writing a blank cheque.
 */
export const FEE_LIMIT_MARGIN = 1.5

/**
 * 100 TRX. A TRC-20 transfer costs single-digit to low-tens of TRX even in the
 * expensive first-transfer case, so this is a hard stop rather than a working
 * value: whatever goes wrong with an estimate, the payer can never be asked to
 * authorise more than this.
 */
export const FEE_LIMIT_CEILING_SUN = 100_000_000

/**
 * Bandwidth is charged on the SIGNED transaction, but `raw_data_hex` measures
 * the unsigned one. 65 bytes of signature plus protobuf field overhead is the
 * difference. Slightly generous on purpose — under-estimating bandwidth is what
 * produces a surprise TRX burn.
 */
export const SIGNATURE_OVERHEAD_BYTES = 67

/**
 * java-tron charges a flat allowance for the execution result on top of the
 * serialized transaction:
 *
 *   bytesSize = trx.toBuilder().clearRet().build().getSerializedSize()
 *   if (dynamicPropertiesStore.supportVM()) bytesSize += Constant.MAX_RESULT_SIZE_IN_TX
 *
 * — `chainbase/src/main/java/org/tron/core/db/BandwidthProcessor.java`, added
 * once per contract (only shielded transfers are exempt) whenever the VM is
 * supported, which it is on both mainnet and Nile. A TRC-20 transfer carries
 * one contract, so it is a flat 64 bytes. Omitting it under-prices every
 * payment by 0.064 TRX at the current bandwidth fee — small, but it is the
 * surprise-burn this module exists to prevent.
 */
export const MAX_RESULT_SIZE_IN_TX = 64

/** Sun per TRX, for display. */
export const SUN_PER_TRX = 1_000_000

export interface ResourcePrices {
  /** Sun per unit of energy. */
  energyFee: number
  /** Sun per byte of bandwidth. */
  bandwidthFee: number
}

export interface ResourceQuote {
  energyNeeded: number
  energyAvailable: number
  bandwidthNeeded: number
  bandwidthAvailable: number
  /** TRX (in sun) that will actually be burned, after free resources. */
  costSun: number
  balanceSun: number
  /** False → do not request a signature. */
  covered: boolean
  /** What to pass as `feeLimit` when building the real transfer. */
  feeLimit: number
}

/**
 * The payer's USDT balance, in base units.
 *
 * A constant call, so it costs nothing and needs no signature. `issuerAddress`
 * is the payer because the contract reads `msg.sender` for nothing here but the
 * node still wants an owner for the simulated call.
 */
export async function usdtBalanceOf(
  tronWeb: TronWeb,
  network: TronNetworkConfig,
  payer: string,
): Promise<bigint> {
  const res = await tronWeb.transactionBuilder.triggerConstantContract(
    network.usdt.address,
    'balanceOf(address)',
    {},
    [{ type: 'address', value: payer }],
    payer,
  )
  const word = res?.constant_result?.[0]
  if (!res?.result?.result || typeof word !== 'string') {
    throw new Error('could not read the USDT balance')
  }
  return BigInt(`0x${word}`)
}

/**
 * Energy the transfer will consume, simulated against the chain's current
 * state. This is the same call the transfer itself makes, so the estimate is
 * for the exact payment rather than a generic transfer.
 */
export async function estimateTransferEnergy(
  tronWeb: TronWeb,
  network: TronNetworkConfig,
  payer: string,
  recipient: string,
  amountBaseUnits: string,
): Promise<number> {
  const res = await tronWeb.transactionBuilder.triggerConstantContract(
    network.usdt.address,
    TRANSFER_SELECTOR,
    {},
    [
      { type: 'address', value: recipient },
      { type: 'uint256', value: amountBaseUnits },
    ],
    payer,
  )
  if (!res?.result?.result) {
    // The simulation itself was rejected. Balance is checked before this runs,
    // so the usual causes are already excluded and guessing a number here would
    // hide a real problem behind a plausible fee.
    throw new Error(
      `could not estimate the network fee${res?.result?.message ? `: ${res.result.message}` : ''}`,
    )
  }
  return res.energy_required ?? res.energy_used ?? 0
}

/**
 * Current resource prices from the chain, read as KEYS of `getChainParameters`.
 *
 * There is no `getEnergyFee()` method — it is a parameter name — and
 * `getEnergyPrices()` returns a `"timestamp:price,…"` history string rather
 * than a number. Both are easy to reach for and neither does what its name
 * suggests.
 *
 * A missing parameter throws rather than defaulting. A hardcoded fallback would
 * silently under-price the transaction and let a payer sign something that
 * cannot execute, which is precisely the failure this module exists to prevent.
 */
export async function readResourcePrices(tronWeb: TronWeb): Promise<ResourcePrices> {
  const params = await tronWeb.trx.getChainParameters()
  const find = (key: string): number => {
    const found = params?.find((p) => p?.key === key)
    if (!found || typeof found.value !== 'number') {
      throw new Error(`chain parameter ${key} is unavailable`)
    }
    return found.value
  }
  return { energyFee: find('getEnergyFee'), bandwidthFee: find('getTransactionFee') }
}

/** Bandwidth the signed transaction will consume, in bytes. */
export function bandwidthFor(rawDataHex: string): number {
  return (
    Math.ceil(rawDataHex.length / 2) +
    SIGNATURE_OVERHEAD_BYTES +
    MAX_RESULT_SIZE_IN_TX
  )
}

/** feeLimit from an energy estimate: margin applied, ceiling enforced. */
export function feeLimitFor(energyNeeded: number, prices: ResourcePrices): number {
  const raw = Math.ceil(energyNeeded * prices.energyFee * FEE_LIMIT_MARGIN)
  return Math.min(raw, FEE_LIMIT_CEILING_SUN)
}

/**
 * Put it together: what the payer has, what this costs, and whether to let them
 * sign.
 *
 * `resources` is typed as tronweb declares it but read as TronGrid actually
 * sends it — see the module docstring. Every field is optional in practice.
 */
export function quoteResources(args: {
  energyNeeded: number
  rawDataHex: string
  resources: Partial<Record<string, number>>
  balanceSun: number
  prices: ResourcePrices
}): ResourceQuote {
  const { energyNeeded, rawDataHex, resources: r, balanceSun, prices } = args

  const energyAvailable = Math.max(0, (r.EnergyLimit ?? 0) - (r.EnergyUsed ?? 0))
  const freeBandwidth = Math.max(0, (r.freeNetLimit ?? 0) - (r.freeNetUsed ?? 0))
  const stakedBandwidth = Math.max(0, (r.NetLimit ?? 0) - (r.NetUsed ?? 0))
  const bandwidthAvailable = freeBandwidth + stakedBandwidth
  const bandwidthNeeded = bandwidthFor(rawDataHex)

  const energyShortfall = Math.max(0, energyNeeded - energyAvailable)
  const bandwidthShortfall = Math.max(0, bandwidthNeeded - bandwidthAvailable)

  // Both budgets are burned in TRX independently; a payer with plenty of energy
  // and no bandwidth still pays, which is why bandwidth is not an afterthought.
  const costSun =
    energyShortfall * prices.energyFee + bandwidthShortfall * prices.bandwidthFee

  return {
    energyNeeded,
    energyAvailable,
    bandwidthNeeded,
    bandwidthAvailable,
    costSun,
    balanceSun,
    covered: balanceSun >= costSun,
    feeLimit: feeLimitFor(energyNeeded, prices),
  }
}
