'use client'

/**
 * SummarySection — the three-line breakdown (Amount / RSends fee / Total)
 * in DM Mono with per-token decimals, plus the gas note. Fee and total come
 * from the single fee source of truth (resolveFeeBreakdown upstream); while
 * quoting, fixed-width placeholders keep the rows from shifting.
 */

import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { Mono } from '@/app/pay/_components/payUi'
import { formatTokenAmount } from '@/lib/web3/feeMath'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'

function Row({
  label,
  value,
  currency,
  decimals,
  emphasize = false,
}: {
  label: string
  value: bigint | null
  currency: string
  decimals: number
  emphasize?: boolean
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 12,
        minHeight: 26,
        flexWrap: 'wrap',
      }}
    >
      <span
        style={{
          fontFamily: C.D,
          fontSize: 13,
          color: emphasize ? C.text : C.sub,
          fontWeight: emphasize ? 600 : 400,
        }}
      >
        {label}
      </span>
      {value != null ? (
        <Mono
          style={{
            fontSize: emphasize ? 15 : 13,
            fontWeight: emphasize ? 500 : 400,
            color: C.text,
          }}
        >
          {`${formatTokenAmount(value, decimals)} ${currency}`}
        </Mono>
      ) : (
        <span
          data-testid="summary-pending"
          aria-hidden
          style={{
            display: 'inline-block',
            width: 84,
            height: 14,
            borderRadius: 6,
            background: 'rgba(10,10,10,0.07)',
          }}
        />
      )}
    </div>
  )
}

export function SummarySection({
  onchain,
  currency,
  fee,
  total,
}: {
  onchain: OnChainIntent
  currency: string
  fee: bigint | null
  total: bigint | null
}) {
  const t = useTranslations('pay')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Row
        label={t('summary.amount')}
        value={onchain.amount}
        currency={currency}
        decimals={onchain.decimals}
      />
      <Row
        label={t('summary.fee')}
        value={fee}
        currency={currency}
        decimals={onchain.decimals}
      />
      <div style={{ borderTop: `1px solid ${C.border}`, margin: '4px 0' }} />
      <Row
        label={t('summary.total')}
        value={total}
        currency={currency}
        decimals={onchain.decimals}
        emphasize
      />
      <p
        style={{
          margin: '6px 0 0',
          fontFamily: C.D,
          fontSize: 12,
          color: C.sub,
        }}
      >
        {t('summary.gasNote')}
      </p>
    </div>
  )
}
