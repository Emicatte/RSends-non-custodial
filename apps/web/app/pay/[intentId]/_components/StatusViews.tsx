'use client'

/**
 * StatusViews — terminal cards, rendered INSTEAD of any wallet UI:
 * success (this session's payment), expired, already paid, not found.
 * Success and already-paid link the settlement tx on the explorer.
 */

import type { ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { Card, Mono, Shell, truncate } from '@/app/pay/_components/payUi'
import { explorerTxUrl } from '@/lib/web3/explorer'

function StatusCard({
  mark,
  title,
  children,
}: {
  mark: ReactNode
  title?: string
  children: ReactNode
}) {
  return (
    <Shell>
      <Card>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 12,
            textAlign: 'center',
            padding: '10px 0',
          }}
        >
          <div
            aria-hidden
            style={{
              width: 44,
              height: 44,
              borderRadius: '50%',
              border: `1px solid ${C.border}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
              color: C.purple,
            }}
          >
            {mark}
          </div>
          {title && (
            <h1
              style={{
                margin: 0,
                fontFamily: C.D,
                fontSize: 20,
                fontWeight: 600,
                color: C.text,
              }}
            >
              {title}
            </h1>
          )}
          {children}
        </div>
      </Card>
    </Shell>
  )
}

function Body({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        margin: 0,
        fontFamily: C.D,
        fontSize: 13.5,
        lineHeight: 1.6,
        color: C.sub,
      }}
    >
      {children}
    </p>
  )
}

function ViewTxLink({ chainId, hash }: { chainId: number; hash: string }) {
  const t = useTranslations('pay')
  return (
    <a
      href={explorerTxUrl(chainId, hash)}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        color: C.purple,
        textDecoration: 'none',
        fontFamily: C.D,
        fontSize: 13,
        minHeight: 44,
      }}
    >
      {t('button.viewTx')}
      <Mono style={{ fontSize: 12, color: C.sub }}>{truncate(hash, 10, 6)}</Mono>
    </a>
  )
}

export function SuccessView({
  amount,
  currency,
  merchant,
  chainId,
  txHash,
}: {
  amount: string
  currency: string
  merchant: string
  chainId: number
  txHash: string | null
}) {
  const t = useTranslations('pay')
  return (
    <StatusCard mark="✓" title={t('success.title')}>
      <Body>{t('success.body', { amount, token: currency, merchant })}</Body>
      {txHash && <ViewTxLink chainId={chainId} hash={txHash} />}
    </StatusCard>
  )
}

export function ExpiredView() {
  const t = useTranslations('pay')
  return (
    <StatusCard mark="○">
      <Body>{t('expired')}</Body>
    </StatusCard>
  )
}

export function AlreadyPaidView({
  chainId,
  txHash,
}: {
  chainId: number | null
  txHash: string | null
}) {
  const t = useTranslations('pay')
  return (
    <StatusCard mark="✓">
      <Body>{t('alreadyPaid')}</Body>
      {txHash && <ViewTxLink chainId={chainId ?? 84532} hash={txHash} />}
    </StatusCard>
  )
}

export function NotFoundView() {
  const t = useTranslations('pay')
  return (
    <StatusCard mark="?">
      <Body>{t('notFound')}</Body>
    </StatusCard>
  )
}
