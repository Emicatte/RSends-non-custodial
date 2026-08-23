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
import { Mono, truncate } from '@/app/pay/_components/payUi'
import { formatTokenAmount } from '@/lib/web3/feeMath'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'

/**
 * PayerAddress — which account is about to pay (or just paid).
 *
 * Deliberately inert: no button, no link, no menu. It is mounted in exactly
 * the places where an interactive wallet control would be dangerous, namely
 * once a transaction is in flight, so it must not be able to drop a wallet
 * mid-payment. The interactive control is RainbowKit's own, mounted upstream
 * only while nothing has been broadcast.
 */
export function PayerAddress({
  address,
  label,
}: {
  address: string | null
  label: string
}) {
  if (!address) return null
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 8,
        fontFamily: C.D,
        fontSize: 12,
        color: C.sub,
      }}
    >
      <span>{label}</span>
      <Mono style={{ fontSize: 12, color: C.text }}>{truncate(address, 6, 4)}</Mono>
    </div>
  )
}

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

// Leg accents cycle through the semantic palette — position 0 (the primary,
// which absorbs the integer rounding remainder) always gets the brand accent.
const SPLIT_LEG_COLORS = [C.purple, C.blue, C.green, C.amber] as const

export function SplitBreakdown({
  split,
  currency,
  decimals,
}: {
  split: NonNullable<OnChainIntent['split']>
  currency: string
  decimals: number
}) {
  const t = useTranslations('pay')
  return (
    <div
      data-testid="split-breakdown"
      style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
    >
      <p style={{ margin: 0, fontFamily: C.D, fontSize: 12, color: C.sub }}>
        {t('split.title', { count: split.recipients.length })}
      </p>

      {/* Proportional distribution bar — flex weight IS the bps share. */}
      <div
        aria-hidden
        style={{
          display: 'flex',
          height: 6,
          borderRadius: 3,
          overflow: 'hidden',
          gap: 2,
        }}
      >
        {split.sharesBps.map((bps, i) => (
          <span
            key={i}
            style={{
              flex: bps,
              background: SPLIT_LEG_COLORS[i % SPLIT_LEG_COLORS.length],
              borderRadius: 2,
            }}
          />
        ))}
      </div>

      {split.recipients.map((addr, i) => (
        <div
          key={addr}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            gap: 12,
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              aria-hidden
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: SPLIT_LEG_COLORS[i % SPLIT_LEG_COLORS.length],
                flexShrink: 0,
              }}
            />
            <Mono style={{ fontSize: 12.5, color: C.text }}>{truncate(addr)}</Mono>
            <span style={{ fontFamily: C.D, fontSize: 11.5, color: C.sub }}>
              {split.sharesBps[i] / 100}%
            </span>
          </span>
          <Mono style={{ fontSize: 12.5, color: C.text }}>
            {formatTokenAmount(split.amounts[i], decimals)} {currency}
          </Mono>
        </div>
      ))}
    </div>
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
