/**
 * The one source of truth for everything the landing page's device showcase
 * displays. Typed against the real DTOs, so a wire-shape change breaks the
 * build here rather than rotting silently on the marketing page.
 *
 * Rules this data keeps:
 *
 *  - No real merchant, address, intent id, amount or API key. Addresses are in
 *    the 0x0000…0001 style and the transaction hashes resolve to nothing on any
 *    explorer, which is the correct outcome for demo data.
 *  - USDC and USDT on Base only. Both are registered for chain 8453 in
 *    services/backend/app/tokens/registry.py. EURC is in NO registry and
 *    create-intent rejects it, so it must never appear here.
 *  - No authored aggregate that implies custody. See TOTAL_BALANCE below.
 *
 * ── Why the payment timestamps are fixed and the delivery timestamps are not
 *
 * The payments table RENDERS its dates (`fmtDate(r.created_at)`), and this
 * section is server-prerendered, so a clock-derived date would render one
 * string on the server and another on the client and tear the React root — the
 * hazard app/[locale]/app/payments/page.tsx documents at length. So they are
 * frozen literals.
 *
 * `expires_at` on the pending rows is far in the future ON PURPOSE: the chip is
 * derived, not stored (`effectiveStatus`), so a near-term expiry would silently
 * turn every pending row red some weeks after this shipped.
 *
 * The webhook card is different — it only COUNTS its deliveries against a 24h
 * window and never prints their dates. It already reads `useClientNow()`, which
 * is null until mount, so the counters are designed to go 0 → N after
 * hydration. Deriving those timestamps from the same clock changes no rendered
 * text, so they stay fresh instead of ageing into zeroes.
 *
 * The dates below will eventually look old. Editing this file is now the whole
 * job — the previous version of this section needed a Playwright run to change
 * a number.
 */

import type { Metric } from '@/components/app/MetricCards'
import type { VolumeBucket } from '@/components/app/VolumeTrendChart'
import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'
import type { OrgWebhook, OrgWebhookDelivery } from '@/hooks/useOrgWebhooks'

/** Obviously synthetic, in the 0x0000…000N style. Never a real payee. */
const addr = (n: number) => `0x${n.toString(16).padStart(40, '0')}`
const MERCHANT = addr(1)

/** Fixed, and not a hash from any chain. */
const tx = (seed: string) => `0x${seed}${'0'.repeat(64 - seed.length)}`

/** Comfortably past any plausible viewing date — see the note above. */
const NEVER_EXPIRES = '2099-01-01T00:00:00Z'

export const SHOWCASE_PAYMENTS: OrgPaymentRecord[] = [
  { intent_id: 'pi_00000000000000000000000000000001', amount: 1_900, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('7b1c4a09e3d5'), matched_tx_hash: tx('7b1c4a09e3d5'), created_at: '2026-08-29T18:08:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000002', amount: 480,   currency: 'USDT', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T17:22:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000003', amount: 1_240, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('2f80ba61c74e'), matched_tx_hash: tx('2f80ba61c74e'), created_at: '2026-08-29T15:47:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000004', amount: 320,   currency: 'USDC', chain: 'base', status: 'expired',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T13:05:00Z', expires_at: '2026-08-29T14:05:00Z' },
  { intent_id: 'pi_00000000000000000000000000000005', amount: 875,   currency: 'USDT', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('9c34ef7012ab'), matched_tx_hash: tx('9c34ef7012ab'), created_at: '2026-08-29T11:31:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000006', amount: 120,   currency: 'USDC', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T09:58:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000007', amount: 1_450, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('4a72d1c8930f'), matched_tx_hash: tx('4a72d1c8930f'), created_at: '2026-08-29T08:12:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000008', amount: 640,   currency: 'USDT', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T06:40:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000009', amount: 1_075, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('e05b98af3612'), matched_tx_hash: tx('e05b98af3612'), created_at: '2026-08-29T04:19:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_0000000000000000000000000000000a', amount: 260,   currency: 'USDC', chain: 'base', status: 'cancelled', recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-28T22:54:00Z', expires_at: '2026-08-29T10:54:00Z' },
  { intent_id: 'pi_0000000000000000000000000000000b', amount: 1_680, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('b6413d0e75c2'), matched_tx_hash: tx('b6413d0e75c2'), created_at: '2026-08-28T19:36:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_0000000000000000000000000000000c', amount: 395,   currency: 'USDT', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-28T16:03:00Z', expires_at: NEVER_EXPIRES },
]

/**
 * The four cards the real dashboard renders, in its order. Values are
 * pre-formatted because that is the shape MetricCards takes — the page does the
 * formatting, and it formats USD (app/[locale]/app/page.tsx:60). They are
 * formatted the same way here rather than re-authored in another currency,
 * because a currency the product cannot produce is exactly the drift this
 * section exists to end.
 *
 * $97,375 across 184 payments is ~$529 average, which is the shape of a B2B
 * gateway. The ratio is deliberate; do not round it into one that is not.
 *
 * TOTAL BALANCE IS ZERO, AND THAT IS THE POINT. RSends is non-custodial: it
 * holds no funds, so there is no balance. Any other number here would be the
 * marketing page asserting custody. The card itself is the real dashboard's —
 * that it exists at all is a contradiction in the product, filed separately.
 */
export const SHOWCASE_METRICS: ReadonlyArray<Metric> = [
  { key: 'volume24h',       value: '$97,375', delta: '+12.4%', deltaPositive: true },
  { key: 'transactions24h', value: '184',     delta: '+23',    deltaPositive: true },
  { key: 'totalBalance',    value: '$0',      delta: '0 chains', deltaPositive: true, deltaIsCount: true },
  { key: 'activeClients',   value: '37',      delta: '+4 this week', deltaPositive: true, deltaIsCount: true },
]

/**
 * Seven UTC days of settled volume, for the real VolumeTrendChart that sits
 * under the KPI cards on the dashboard. Fixed dates, for the same reason the
 * payment rows are fixed: the chart labels them.
 *
 * The last bucket is 97_375 so the chart and the "Volume 24h" card agree. Two
 * numbers on one screen that disagree is exactly the kind of thing a
 * hand-drawn mockup gets wrong, and the point of this section is that it does
 * not.
 */
export const SHOWCASE_VOLUME_SERIES: VolumeBucket[] = [
  { date: '2026-08-23', volume_usd: 61_420 },
  { date: '2026-08-24', volume_usd: 44_180 },
  { date: '2026-08-25', volume_usd: 88_905 },
  { date: '2026-08-26', volume_usd: 73_640 },
  { date: '2026-08-27', volume_usd: 104_215 },
  { date: '2026-08-28', volume_usd: 82_770 },
  { date: '2026-08-29', volume_usd: 97_375 },
]

/** Three endpoints, which is what a merchant with staging and prod looks like. */
export const SHOWCASE_WEBHOOKS: OrgWebhook[] = [
  {
    webhook_id: 1,
    url: 'https://api.northwind.example/rsends/events',
    events: ['payment.completed', 'payment.expired'],
    is_active: true,
    created_at: '2026-08-01T09:00:00Z',
  },
  {
    webhook_id: 2,
    url: 'https://ops.northwind.example/hooks/ledger',
    events: ['payment.completed'],
    is_active: true,
    created_at: '2026-08-06T14:20:00Z',
  },
  {
    webhook_id: 3,
    url: 'https://staging.northwind.example/rsends/events',
    events: ['payment.completed', 'payment.partial', 'payment.overpaid'],
    is_active: false,
    created_at: '2026-07-19T11:05:00Z',
  },
]

/**
 * Deliveries, spaced across the last few hours of whatever "now" is. See the
 * header: the card counts these against a 24h window and never prints a date,
 * so a live clock changes no rendered text.
 */
export function showcaseDeliveries(
  nowMs: number | null,
  webhookId = 1,
): OrgWebhookDelivery[] {
  // The inactive staging endpoint has nothing recent, which is what makes its
  // zeroed counters read as "switched off" rather than as broken.
  if (webhookId === 3) return []
  const base = nowMs ?? Date.parse('2026-08-29T18:00:00Z')
  const ago = (minutes: number) => new Date(base - minutes * 60_000).toISOString()
  const row = (
    id: number,
    event_type: string,
    status: string,
    response_code: number | null,
    retries: number,
    minutes: number,
  ): OrgWebhookDelivery => ({
    id,
    event_type,
    status,
    response_code,
    retries,
    next_retry_at: status === 'pending' ? ago(minutes - 30) : null,
    created_at: ago(minutes),
    delivered_at: status === 'delivered' ? ago(minutes) : null,
  })
  return [
    row(1, 'payment.completed', 'delivered', 200, 0, 14),
    row(2, 'payment.completed', 'delivered', 200, 0, 96),
    row(3, 'payment.expired', 'failed', 503, 3, 180),
    row(4, 'payment.completed', 'delivered', 200, 0, 242),
    row(5, 'payment.completed', 'pending', null, 2, 310),
    row(6, 'payment.completed', 'delivered', 200, 0, 455),
  ]
}

/** The payer's side: what SuccessView shows once the transaction has mined. */
export const SHOWCASE_PAY = {
  amount: '240.6',
  currency: 'USDC',
  merchant: 'Northwind Supply',
  chainId: 84532,
  txHash: '0x7b1c4a09e3d5f28c6b90ad4172e8c3f5d016b7a4e92c85df3016a7b4c2e9d580',
  payer: addr(0xbeef),
} as const
