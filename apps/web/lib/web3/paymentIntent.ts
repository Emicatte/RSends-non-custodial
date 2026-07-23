/**
 * lib/web3/paymentIntent — hosted-checkout intent model.
 *
 * Normalizes the payload of GET /api/pay/{intentId} (the public, allowlisted
 * payment-intent view) into a stable shape, building a typed OnChainIntent
 * when the non-custodial on-chain fields are present. Extracted verbatim from
 * the previous monolithic /pay/[intentId] page so the logic is unit-testable.
 *
 * `terminalKind` is the page-level gate: terminal intents render a status
 * card INSTEAD of any wallet UI. Post-settlement statuses without dedicated
 * payer copy (review, refunded, partial, overpaid) map to the already-paid
 * view — from the payer's perspective the payment left their wallet and was
 * observed on-chain; anything after that is between merchant and RSends.
 */

import { getAddress, zeroAddress, type Hex } from 'viem'

export interface RawPaymentIntent {
  intent_id?: string
  reference_id?: string
  status: string
  expires_at: string
  amount?: number | string
  currency?: string
  chain?: string
  matched_tx_hash?: string | null
  tx_hash?: string | null
  metadata?: Record<string, unknown> | null
  // Public limited view: the backend derives the display name server-side.
  merchant_name?: string | null
  onchain?: {
    invoiceId?: string
    merchant?: string
    token?: string
    amount?: string // base units (wei / token decimals)
    fee?: string | null // base units; null when the backend couldn't quote (feeUnavailable)
    total?: string | null
    maxFee?: string | null
    chainId?: number
    router?: string
    calldata?: string | null
    payWithPermitCalldata?: string | null
    function?: string
    decimals?: number
    isNative?: boolean
    permitType?: string | null
    permitVersion?: string | null
    feeUnavailable?: boolean
    // 1 = RSendsRouter (testnet, on-chain fee + maxFee args); 2 =
    // RSendsRouterV2 (fee-less/ownerless — fee "0", no maxFee). Absent ⇒ 1.
    routerVersion?: number
    // Split fan-out (RSendsSplitRouter): merchant is "" (no single payee),
    // router is the fee-less split router, fee is "0".
    split?: {
      router?: string
      recipients?: string[]
      sharesBps?: number[]
      amounts?: string[] // per-leg base units (server-computed, display only)
    } | null
  } | null
  // Top-level camelCase also tolerated (alternate backend shape).
  invoiceId?: string
  merchant?: string
  token?: string
  amount_base_units?: string
  chainId?: number
  router?: string
}

export interface OnChainIntent {
  invoiceId: Hex
  merchant: `0x${string}`
  token: `0x${string}`
  amount: bigint
  /** fee in token base units from the backend's live quoteFee; null → read quoteFee on-chain */
  fee: bigint | null
  decimals: number
  chainId: number
  router: `0x${string}`
  /** Router family this intent pays through: 1 = RSendsRouter (fee + maxFee),
   * 2 = RSendsRouterV2 (fee-less/ownerless — the hook forks ABI/args on this).
   * Anything other than an explicit 2 normalizes to 1 (backward compatible). */
  routerVersion: 1 | 2
  /** permit policy from the intent: "eip2612" → permit flow, else approve+pay. */
  permitType: 'eip2612' | 'none'
  /** EIP-712 domain version for the permit signature (only meaningful for eip2612). */
  permitVersion: string
  /** Split fan-out: when set, `router` is the RSendsSplitRouter (fee-less) and
   * the checkout calls paySplit* with total + sharesBps — the contract
   * recomputes per-leg amounts; `amounts` here are display/verification only.
   * Optional: absent/null ⇒ single-recipient intent. */
  split?: {
    recipients: `0x${string}`[]
    sharesBps: number[]
    amounts: bigint[]
  } | null
}

export interface PaymentIntent {
  intentId: string
  status: string
  expiresAt: string
  amountLabel: string
  currency: string
  chainLabel: string
  txHash: string | null
  metadata: Record<string, unknown> | null
  onchain: OnChainIntent | null
  raw: RawPaymentIntent
}

export const CHAIN_LABELS: Record<string, string> = {
  BASE: 'Base', ETH: 'Ethereum', ARBITRUM: 'Arbitrum', OPTIMISM: 'Optimism',
  POLYGON: 'Polygon', BSC: 'BNB Chain', AVALANCHE: 'Avalanche',
  BASE_SEPOLIA: 'Base Sepolia', SEPOLIA: 'Sepolia',
}

export const PAID_STATES = new Set(['completed', 'paid'])
export const DEAD_STATES = new Set(['expired', 'cancelled'])

export type TerminalKind = 'already_paid' | 'expired' | null

export function terminalKind(status: string): TerminalKind {
  if (PAID_STATES.has(status)) return 'already_paid'
  if (DEAD_STATES.has(status)) return 'expired'
  if (status === 'pending') return null
  // review / refunded / partial / overpaid: settled on-chain from the payer's
  // side — show the already-completed view rather than wallet UI.
  return 'already_paid'
}

export function formatCountdown(ms: number): string {
  if (ms <= 0) return '0:00'
  const totalSec = Math.floor(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function normalizeIntent(
  raw: RawPaymentIntent,
  intentId: string,
): PaymentIntent {
  const chainLabel = raw.chain
    ? (CHAIN_LABELS[raw.chain.toUpperCase()] ?? raw.chain)
    : 'Base'

  // Build the on-chain block only when the backend supplied the required
  // fields. Prefer the nested `onchain` object; fall back to top-level
  // camelCase for alternate backend shapes.
  let onchain: OnChainIntent | null = null
  const oc = raw.onchain ?? null
  const invoiceId = oc?.invoiceId ?? raw.invoiceId
  const merchant = oc?.merchant ?? raw.merchant
  const token = oc?.token ?? raw.token
  const amountStr =
    oc?.amount ?? raw.amount_base_units ?? (typeof raw.amount === 'string' ? raw.amount : undefined)
  const chainId = oc?.chainId ?? raw.chainId
  const router = oc?.router ?? raw.router
  const rawSplit = oc?.split ?? null
  if (
    invoiceId && (merchant || rawSplit) && token != null &&
    amountStr != null && chainId != null && router
  ) {
    try {
      // Split block: parse + validate the vectors; any malformation (missing
      // arrays, length mismatch, fewer than 2 legs) throws → graceful "not
      // available" UI, never a half-parsed split.
      let split: OnChainIntent['split'] = null
      if (rawSplit) {
        const recipients = (rawSplit.recipients ?? []).map((r) => getAddress(r))
        const sharesBps = (rawSplit.sharesBps ?? []).map((b) => Number(b))
        const amounts = (rawSplit.amounts ?? []).map((a) => BigInt(a))
        if (
          recipients.length < 2 ||
          recipients.length !== sharesBps.length ||
          recipients.length !== amounts.length
        ) {
          throw new Error('malformed split vectors')
        }
        split = { recipients, sharesBps, amounts }
      }

      onchain = {
        invoiceId: invoiceId as Hex,
        // Split intents have no single payee (backend sends "") — the split
        // vectors ARE the payee set; zeroAddress is a never-used placeholder.
        merchant: merchant ? getAddress(merchant) : zeroAddress,
        token: getAddress(token),
        amount: BigInt(amountStr),
        fee: oc?.fee != null ? BigInt(oc.fee) : null,
        decimals: oc?.decimals ?? 18,
        chainId: chainId,
        router: getAddress(router),
        routerVersion: oc?.routerVersion === 2 ? 2 : 1,
        permitType: oc?.permitType === 'eip2612' ? 'eip2612' : 'none',
        permitVersion: oc?.permitVersion ?? '1',
        split,
      }
    } catch {
      // Malformed on-chain fields → fall back to "not available" UI.
      onchain = null
    }
  }

  return {
    intentId,
    status: raw.status,
    expiresAt: raw.expires_at,
    amountLabel: raw.amount != null ? String(raw.amount) : '',
    currency: raw.currency ?? '',
    chainLabel,
    txHash: raw.matched_tx_hash || raw.tx_hash || null,
    metadata: raw.metadata ?? null,
    onchain,
    raw,
  }
}

export function merchantName(intent: PaymentIntent): string {
  if (intent.raw.merchant_name) return intent.raw.merchant_name
  const meta = intent.metadata
  if (!meta) return 'RSends Payment'
  return (meta.merchant_name as string) || (meta.store_name as string) || 'RSends Payment'
}
