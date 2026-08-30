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
 *  - USDC on Base only. USDT was here and is gone: the landing copy's USDT
 *    claim is itself unresolved (see the release gate on this branch), and a
 *    shop window should not be the thing that settles a token question.
 *    EURC is in NO backend registry and create-intent rejects it, so it must
 *    never appear here either.
 *  - No authored aggregate that implies custody. RSends holds nothing.
 *
 * ── Why the timestamps are literals and not derived from a clock
 *
 * This section is server-prerendered, so a clock-derived string renders one way
 * on the server and another on the client and tears the React root — the hazard
 * app/[locale]/app/payments/page.tsx documents at length. So they are frozen.
 *
 * `expires_at` on the pending rows is far in the future ON PURPOSE: the chip is
 * derived, not stored (`effectiveStatus`), so a near-term expiry would silently
 * turn every pending row red some weeks after this shipped.
 *
 * The dates below will eventually look old. Editing this file is now the whole
 * job — the previous version of this section needed a Playwright run to change
 * a number.
 */

import type { Metric } from '@/components/app/MetricCards'
import type { TxRow } from '@/components/app/RecentTransactionsTable'
import type { VolumeBucket } from '@/components/app/VolumeTrendChart'
import type { OrgPaymentRecord } from '@/hooks/useOrgPayments'

/** Obviously synthetic, in the 0x0000…000N style. Never a real payee. */
const addr = (n: number) => `0x${n.toString(16).padStart(40, '0')}`
const MERCHANT = addr(1)

/** Fixed, and not a hash from any chain. */
const tx = (seed: string) => `0x${seed}${'0'.repeat(64 - seed.length)}`

/** Comfortably past any plausible viewing date — see the note above. */
const NEVER_EXPIRES = '2099-01-01T00:00:00Z'

export const SHOWCASE_PAYMENTS: OrgPaymentRecord[] = [
  { intent_id: 'pi_00000000000000000000000000000001', amount: 1_240, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('7b1c4a09e3d5'), matched_tx_hash: tx('7b1c4a09e3d5'), created_at: '2026-08-29T18:08:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000002', amount: 875,   currency: 'USDC', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T17:22:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000003', amount: 640,   currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('2f80ba61c74e'), matched_tx_hash: tx('2f80ba61c74e'), created_at: '2026-08-29T15:47:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000004', amount: 320,   currency: 'USDC', chain: 'base', status: 'expired',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T13:05:00Z', expires_at: '2026-08-29T14:05:00Z' },
  { intent_id: 'pi_00000000000000000000000000000005', amount: 1_075, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('9c34ef7012ab'), matched_tx_hash: tx('9c34ef7012ab'), created_at: '2026-08-29T11:31:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000006', amount: 395,   currency: 'USDC', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T09:58:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000007', amount: 1_180, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('4a72d1c8930f'), matched_tx_hash: tx('4a72d1c8930f'), created_at: '2026-08-29T08:12:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000008', amount: 210,   currency: 'USDC', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-29T06:40:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_00000000000000000000000000000009', amount: 960,   currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('e05b98af3612'), matched_tx_hash: tx('e05b98af3612'), created_at: '2026-08-29T04:19:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_0000000000000000000000000000000a', amount: 260,   currency: 'USDC', chain: 'base', status: 'cancelled', recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-28T22:54:00Z', expires_at: '2026-08-29T10:54:00Z' },
  { intent_id: 'pi_0000000000000000000000000000000b', amount: 1_120, currency: 'USDC', chain: 'base', status: 'paid',      recipient: MERCHANT, tx_hash: tx('b6413d0e75c2'), matched_tx_hash: tx('b6413d0e75c2'), created_at: '2026-08-28T19:36:00Z', expires_at: NEVER_EXPIRES },
  { intent_id: 'pi_0000000000000000000000000000000c', amount: 480,   currency: 'USDC', chain: 'base', status: 'pending',   recipient: MERCHANT, tx_hash: null, matched_tx_hash: null, created_at: '2026-08-28T16:03:00Z', expires_at: NEVER_EXPIRES },
]

/**
 * The four cards the real dashboard renders, in its order. Values are
 * pre-formatted because that is the shape MetricCards takes — the page does the
 * formatting, and it formats USD (app/[locale]/app/page.tsx). They are
 * formatted the same way here rather than re-authored in another currency,
 * because a currency the product cannot produce is exactly the drift this
 * section exists to end. (The brief for this section said "€210–€1.240"; the
 * AMOUNT column is USD, and EURC is 422'd by create-intent, so the range is
 * kept and the sign is the product's.)
 *
 * $97,375 across 184 payments is ~$529 average, which is the shape of a B2B
 * gateway. The ratio is deliberate; do not round it into one that is not.
 *
 * A SENTENCE sub-label is a key, not a literal. This is where the bug was: the
 * two removed cards carried the literals `"+4 this week"` and `"0 chains"`,
 * which rendered in English inside the Italian page. A percentage stays a
 * plain string because `+12.4%` is the same in five languages.
 *
 * There is no balance tile and no client count, and their absence is the
 * point. RSends is non-custodial — it holds no funds, so a balance card can
 * only ever assert a custody the product does not have, and `$0` in the middle
 * of populated cards reads as a field that failed to load. "Active clients" is
 * a claim about the company, not a reading off the interface, and this page is
 * shown to prospective partners.
 */
export const SHOWCASE_METRICS: ReadonlyArray<Metric> = [
  { key: 'volume24h', value: '$97,375', delta: '+12.4%', deltaPositive: true },
  {
    key: 'transactions24h',
    value: '184',
    delta: { key: 'metrics.vsYesterday', values: { count: '+23' } },
    deltaPositive: true,
  },
  { key: 'volume30d', value: '$2,641,180', delta: '+8.1%', deltaPositive: true },
  {
    key: 'webhooksDelivered24h',
    value: '184',
    delta: { key: 'metrics.deliveryRate', values: { rate: 100 } },
    deltaPositive: true,
    deltaIsCount: true,
  },
]

/**
 * The last six settlements, for the real RecentTransactionsTable under the
 * cards. All on Base, all USDC, statuses mixed — a table where every row is
 * green is a table nobody believes.
 *
 * `type` is `transfer` in lower case because that is the literal the backend
 * sends (`user_org_stats_routes`), not a label written for marketing.
 *
 * TIME is a bare UTC clock. The dashboard renders a RELATIVE label there
 * (`relTime`), which is pinned to `Intl.RelativeTimeFormat('en')` — so a
 * faithful copy would put "2 hours ago" on the Italian page, which is the
 * exact defect this pass was opened to fix. A clock reads the same in five
 * languages and does not age. The dashboard's English relative times are a
 * real gap, filed separately; they are not fixed by making this fixture lie.
 */
export const SHOWCASE_RECENT_TX: ReadonlyArray<TxRow> = [
  { id: 1, time: '18:08', type: 'transfer', amount: '$1,240', chain: 'Base', status: 'confirmed' },
  { id: 2, time: '17:22', type: 'transfer', amount: '$875', chain: 'Base', status: 'confirmed' },
  { id: 3, time: '15:47', type: 'transfer', amount: '$640', chain: 'Base', status: 'pending' },
  { id: 4, time: '11:31', type: 'transfer', amount: '$1,075', chain: 'Base', status: 'confirmed' },
  { id: 5, time: '09:58', type: 'transfer', amount: '$395', chain: 'Base', status: 'failed' },
  { id: 6, time: '06:40', type: 'transfer', amount: '$210', chain: 'Base', status: 'confirmed' },
]

/**
 * Seven UTC days of settled volume, for the real VolumeTrendChart that sits
 * under the KPI cards on the dashboard. Fixed dates, for the same reason the
 * payment rows are fixed: the chart labels them.
 *
 * The last bucket is 97_375 so the chart and the "Volume 24h" card agree. Two
 * numbers on one screen that disagree is exactly the kind of thing a
 * hand-drawn mockup gets wrong, and the point of this section is that it does
 * not. These seven days total 552,505 against a 30-day 2,641,180 — a month
 * still up 8.1% on the one before it, with a slightly quieter last week. Check
 * that arithmetic again if you change either number.
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

/** The payer's side: what SuccessView shows once the transaction has mined. */
export const SHOWCASE_PAY = {
  amount: '240.6',
  currency: 'USDC',
  merchant: 'Northwind Supply',
  chainId: 84532,
  txHash: '0x7b1c4a09e3d5f28c6b90ad4172e8c3f5d016b7a4e92c85df3016a7b4c2e9d580',
  payer: addr(0xbeef),
} as const
