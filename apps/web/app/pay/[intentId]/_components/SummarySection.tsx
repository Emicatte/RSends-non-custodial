'use client'

/**
 * TotalHeadline + GasNote — the checkout presents ONE figure to the payer:
 * the total the wallet will charge (amount + on-chain fee, from
 * resolveFeeBreakdown upstream). No breakdown rows. While the total is
 * still resolving (backend feeUnavailable → on-chain quote in flight) a
 * fixed-size placeholder holds the line — the bare principal is never
 * shown as if it were the charge.
 */

import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { Mono } from '@/app/pay/_components/payUi'
import { formatTokenAmount } from '@/lib/web3/feeMath'

export function TotalHeadline({
  total,
  currency,
  decimals,
}: {
  total: bigint | null
  currency: string
  decimals: number
}) {
  return (
    <Mono style={{ fontSize: 34, fontWeight: 500, color: C.text }}>
      {total != null ? (
        formatTokenAmount(total, decimals)
      ) : (
        <span
          data-testid="amount-pending"
          aria-hidden
          style={{
            display: 'inline-block',
            width: 120,
            height: 28,
            borderRadius: 8,
            background: 'rgba(10,10,10,0.07)',
            verticalAlign: 'middle',
          }}
        />
      )}{' '}
      <span style={{ fontSize: 18, color: C.sub }}>{currency}</span>
    </Mono>
  )
}

export function GasNote() {
  const t = useTranslations('pay')
  return (
    <p
      style={{
        margin: 0,
        fontFamily: C.D,
        fontSize: 12,
        color: C.sub,
      }}
    >
      {t('summary.gasNote')}
    </p>
  )
}
