'use client'

import { useTranslations } from 'next-intl'

import { chainLabelForKey } from '@/lib/web3/paymentIntent'

/**
 * The /app home's recent-settlements table, lifted verbatim out of
 * app/[locale]/app/page.tsx.
 *
 * Presentational: every cell arrives already formatted. That split is not
 * cosmetic — the page is what knows whether an amount has a USD peg at all
 * (`amount_usd_known`), and rendering `$0` for a payment the registry cannot
 * value would claim a real payment was worth nothing. That knowledge stays on
 * the page; this file only draws.
 *
 * Same reason as MetricCards and PaymentsTable: the landing page's device
 * mockup renders this against a fixture, so the shop window cannot drift away
 * from the dashboard. Anything added here becomes public.
 */

const COLORS = {
  ink: '#1a1a1a',
  muted: '#6b6b6b',
  border: 'rgba(26, 26, 26, 0.08)',
  green: '#2D8659',
  greenLight: 'rgba(45, 134, 89, 0.10)',
  orange: '#C45A3C',
  orangeLight: 'rgba(196, 90, 60, 0.10)',
  red: '#C03A3A',
  redLight: 'rgba(192, 58, 58, 0.10)',
}

/**
 * Keyed on the backend's `chain_key` — snake, machine-stable — NOT on display
 * text. It used to be keyed on labels ('Base', 'Tron', 'Sol') while
 * `explorer.ts` was keyed on snake names, so the same row was looked up in two
 * vocabularies that could not be checked against each other. 'Sol' is gone
 * rather than migrated: no backend chain id maps to Solana, so that entry was
 * unreachable and always had been.
 *
 * `testnet` is declared HERE, per entry, rather than in a second list of
 * testnet chains. A separate list is one more table to drift.
 */
export const CHAIN_BADGE: Record<
  string,
  { bg: string; text: string; testnet?: true }
> = {
  base: { bg: 'rgba(0, 82, 255, 0.08)', text: '#0052ff' },
  base_sepolia: { bg: 'rgba(0, 82, 255, 0.08)', text: '#0052ff', testnet: true },
  ethereum: { bg: 'rgba(98, 126, 234, 0.10)', text: '#4d63c8' },
  arbitrum: { bg: 'rgba(18, 140, 214, 0.10)', text: '#1073b0' },
  tron: { bg: 'rgba(255, 6, 10, 0.08)', text: '#cc0510' },
  tron_nile: { bg: 'rgba(255, 6, 10, 0.08)', text: '#cc0510', testnet: true },
}

/**
 * The badge for a chain `CHAIN_BADGE` has no entry for.
 *
 * Grey on purpose. An unidentified chain must not borrow a known network's
 * colour: a row painted Base blue asserts a network we never identified, which
 * is the same lie as labelling it "Base" — just told in a channel the reader
 * cannot quote back. Neutral says "this is what we were told, verbatim".
 */
export const CHAIN_BADGE_UNKNOWN = {
  bg: 'rgba(26, 26, 26, 0.06)',
  text: COLORS.muted,
}

/**
 * Total over every string. The lookup it replaces was partial — an unknown
 * chain read back `undefined` and the next line dereferenced `.bg` on it — and
 * survived only because the page coerced every unrecognised chain to `'Base'`
 * before a row could reach here. That coercion is gone, so this is now the
 * rendering path for every chain the frontend cannot name.
 */
export function chainBadgeFor(chainKey: string): {
  bg: string
  text: string
  testnet?: true
} {
  return CHAIN_BADGE[chainKey] ?? CHAIN_BADGE_UNKNOWN
}

/**
 * Testnet badges are OUTLINED where mainnet badges are filled.
 *
 * "Base Sepolia" and "Base" differ by one word that a reader scanning a table
 * will not register, and the whole defect this branch fixes is testnet
 * settlements presenting as mainnet ones. The label alone is not enough
 * separation, so the shape carries it too — legible without reading, and
 * without a colour that would claim a different network.
 */
function badgeStyle(badge: ReturnType<typeof chainBadgeFor>) {
  return badge.testnet
    ? {
        background: 'transparent',
        color: badge.text,
        border: `1px solid ${badge.text}`,
      }
    : { background: badge.bg, color: badge.text, border: '1px solid transparent' }
}

export type TxStatus = 'confirmed' | 'pending' | 'failed'

export const STATUS_BADGE: Record<
  TxStatus,
  { bg: string; text: string; key: 'statusConfirmed' | 'statusPending' | 'statusFailed' }
> = {
  confirmed: { bg: COLORS.greenLight, text: COLORS.green, key: 'statusConfirmed' },
  pending: { bg: COLORS.orangeLight, text: COLORS.orange, key: 'statusPending' },
  failed: { bg: COLORS.redLight, text: COLORS.red, key: 'statusFailed' },
}

export type TxRow = {
  id: number
  /** Already formatted — the page owns the clock (see useClientNow). */
  time: string
  type: string
  /** Already formatted, in USD, or the token symbol when there is no peg. */
  amount: string
  /**
   * The backend's `chain_key` — a machine-stable snake name, never display
   * text. The component derives the label from it; a caller must not pass one
   * in, because a label cannot be keyed back to a chain.
   *
   * Any string is legal, including a `chain:{id}` we cannot name:
   * `chainBadgeFor` and `chainLabelForKey` are both total over it.
   */
  chainKey: string
  status: TxStatus
}

export const TX_COLUMNS = ['time', 'type', 'amount', 'chain', 'status'] as const

export function RecentTransactionsTable({ rows }: { rows: ReadonlyArray<TxRow> }) {
  const t = useTranslations('app.dashboard')

  return (
    <div style={{ overflowX: 'auto' }}>
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'var(--font-display)',
          fontSize: 13,
        }}
      >
        <thead>
          <tr>
            {TX_COLUMNS.map((col) => (
              <th
                key={col}
                className="px-4 py-3"
                style={{
                  textAlign: 'left',
                  borderBottom: `1px solid ${COLORS.border}`,
                  fontSize: 11,
                  fontWeight: 700,
                  color: COLORS.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                }}
              >
                {t(`recentTransactions.${col}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((tx) => {
            const chainBadge = chainBadgeFor(tx.chainKey)
            const statusBadge = STATUS_BADGE[tx.status]
            return (
              <tr key={tx.id}>
                <td className="px-4 py-3" style={{ color: COLORS.muted, borderBottom: `1px solid ${COLORS.border}` }}>
                  {tx.time}
                </td>
                <td className="px-4 py-3" style={{ color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                  {tx.type}
                </td>
                <td className="px-4 py-3" style={{ color: COLORS.ink, fontWeight: 600, borderBottom: `1px solid ${COLORS.border}` }}>
                  {tx.amount}
                </td>
                <td className="px-4 py-3" style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <span
                    className="inline-block px-2 py-0.5 rounded-md"
                    style={{
                      ...badgeStyle(chainBadge),
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.02em',
                    }}
                  >
                    {chainLabelForKey(tx.chainKey)}
                  </span>
                </td>
                <td className="px-4 py-3" style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                  <span
                    className="inline-block px-2 py-0.5 rounded-md"
                    style={{
                      background: statusBadge.bg,
                      color: statusBadge.text,
                      fontSize: 11,
                      fontWeight: 700,
                    }}
                  >
                    {t(`recentTransactions.${statusBadge.key}`)}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
