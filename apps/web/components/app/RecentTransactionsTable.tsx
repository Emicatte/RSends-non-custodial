'use client'

import { useTranslations } from 'next-intl'

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

export const CHAIN_BADGE: Record<string, { bg: string; text: string }> = {
  Base: { bg: 'rgba(0, 82, 255, 0.08)', text: '#0052ff' },
  Tron: { bg: 'rgba(255, 6, 10, 0.08)', text: '#cc0510' },
  Sol: { bg: 'rgba(153, 69, 255, 0.08)', text: '#7c2dc7' },
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
 * before a row could reach here. That coercion is the defect being removed, so
 * this stops being a latent crash and becomes the rendering path.
 */
export function chainBadgeFor(chain: string): { bg: string; text: string } {
  return CHAIN_BADGE[chain] ?? CHAIN_BADGE_UNKNOWN
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
   * Any chain string, including one no badge is defined for — `chainBadgeFor`
   * is total over it. `keyof typeof CHAIN_BADGE` used to sit here and promised
   * nothing anyway (`keyof Record<string, …>` widens to `string | number`),
   * which is precisely how the partial lookup read as safe.
   */
  chain: string
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
            const chainBadge = chainBadgeFor(tx.chain)
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
                      background: chainBadge.bg,
                      color: chainBadge.text,
                      fontSize: 11,
                      fontWeight: 700,
                      letterSpacing: '0.02em',
                    }}
                  >
                    {tx.chain}
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
