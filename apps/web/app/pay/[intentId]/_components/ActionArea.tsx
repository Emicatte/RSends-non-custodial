'use client'

/**
 * ActionArea — renders the action slot for every CheckoutStep. Pure
 * presentational: receives the step + callbacks from the central hook and
 * the RainbowKit Connect button as a slot (this file never imports wallet
 * libraries). The two-step Approve/Pay indicator appears ONLY on the
 * approve+pay fallback path; the permit path is a single confirmation.
 * The tx hash is linked on the explorer from the moment it exists.
 */

import type { ReactNode } from 'react'
import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import {
  GhostButton,
  Mono,
  PrimaryButton,
  Spinner,
  truncate,
} from '@/app/pay/_components/payUi'
import type { CheckoutStep } from '@/lib/web3/checkoutState'
import { explorerTxUrl } from '@/lib/web3/explorer'
import { formatTokenAmount } from '@/lib/web3/feeMath'
import type { OnChainIntent } from '@/lib/web3/paymentIntent'

export interface ActionAreaProps {
  step: CheckoutStep
  onchain: OnChainIntent
  currency: string
  total: bigint | null
  networkLabel: string
  connectSlot: ReactNode
  approveHash: string | null
  payHash: string | null
  /** the wallet prompt has been open long enough to deserve an explanation */
  waitingLong: boolean
  /** nothing has been broadcast, so offering to change wallet is safe */
  canSwitchWallet: boolean
  onSwitch: () => void
  onApprove: () => void
  onPay: () => void
  onRetry: () => void
  onUseOtherWallet: () => void
}

function Note({ children, tone = 'sub' }: { children: ReactNode; tone?: 'sub' | 'error' }) {
  return (
    <p
      style={{
        margin: 0,
        fontFamily: C.D,
        fontSize: 13,
        lineHeight: 1.5,
        color: tone === 'error' ? C.red : C.sub,
        textAlign: 'center',
      }}
    >
      {children}
    </p>
  )
}

function StepIndicator({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontFamily: C.M,
        fontSize: 12,
        letterSpacing: '0.04em',
        color: C.purple,
        textAlign: 'center',
      }}
    >
      {children}
    </div>
  )
}

function WaitingRow({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        minHeight: 47,
      }}
    >
      <Spinner size={16} />
      <span style={{ fontFamily: C.D, fontSize: 13, color: C.sub }}>{children}</span>
    </div>
  )
}

function TxLink({
  chainId,
  hash,
  label,
}: {
  chainId: number
  hash: string
  label: string
}) {
  const href = explorerTxUrl(chainId, hash)
  // With no explorer for this chain the hash is still the thing the payer
  // needs; it just is not a link. Better than a link to another network.
  if (!href) {
    return (
      <div style={{ textAlign: 'center' }}>
        <Mono style={{ fontSize: 12, color: C.sub }}>{truncate(hash, 10, 6)}</Mono>
      </div>
    )
  }
  return (
    <div style={{ textAlign: 'center' }}>
      <a
        href={href}
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
        {label}
        <Mono style={{ fontSize: 12, color: C.sub }}>{truncate(hash, 10, 6)}</Mono>
      </a>
    </div>
  )
}

export function ActionArea(props: ActionAreaProps) {
  const t = useTranslations('pay')
  const { step, onchain, currency, total } = props

  const totalLabel =
    total != null ? formatTokenAmount(total, onchain.decimals) : null
  const payLabel = t('button.pay', {
    amount: totalLabel ?? '…',
    token: currency,
  })

  switch (step) {
    case 'connect':
      return <>{props.connectSlot}</>

    case 'wrong_network':
      return (
        <>
          <Note>{t('wrongNetwork', { network: props.networkLabel })}</Note>
          <PrimaryButton onClick={props.onSwitch}>
            {t('button.switch')}
          </PrimaryButton>
        </>
      )

    case 'quoting':
      return (
        <PrimaryButton disabled>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
            <Spinner size={14} />
            {payLabel}
          </span>
        </PrimaryButton>
      )

    case 'insufficient_balance':
      return (
        <Note>
          {t('insufficient', { token: currency, amount: totalLabel ?? '…' })}
        </Note>
      )

    case 'needs_approve':
      return (
        <>
          <StepIndicator>{t('steps.approve', { token: currency })}</StepIndicator>
          <Note>{t('approveExplainer', { token: currency })}</Note>
          <PrimaryButton onClick={props.onApprove}>
            {t('button.approve', { token: currency })}
          </PrimaryButton>
        </>
      )

    case 'approving':
    case 'paying':
      // The spinner and the waiting copy STAY: the wallet prompt is still
      // live and may still be confirmed. Only the explanation is added, and
      // the escape hatch only while nothing has been broadcast.
      return (
        <>
          <WaitingRow>{t('waitingWallet')}</WaitingRow>
          {props.waitingLong && (
            <>
              <Note>{t('walletSilent')}</Note>
              {props.canSwitchWallet && (
                <GhostButton onClick={props.onUseOtherWallet}>
                  {t('button.otherWallet')}
                </GhostButton>
              )}
            </>
          )}
        </>
      )

    case 'approve_pending':
      return (
        <>
          <StepIndicator>{t('steps.approve', { token: currency })}</StepIndicator>
          <WaitingRow>{t('txPending')}</WaitingRow>
          {props.approveHash && (
            <TxLink
              chainId={onchain.chainId}
              hash={props.approveHash}
              label={t('button.viewTx')}
            />
          )}
        </>
      )

    case 'ready_to_pay':
      return (
        <>
          <StepIndicator>{t('steps.confirm')}</StepIndicator>
          <PrimaryButton onClick={props.onPay} disabled={total == null}>
            {payLabel}
          </PrimaryButton>
        </>
      )

    case 'ready':
      return (
        <PrimaryButton onClick={props.onPay} disabled={total == null}>
          {payLabel}
        </PrimaryButton>
      )

    case 'tx_pending':
      return (
        <>
          <WaitingRow>{t('txPending')}</WaitingRow>
          {props.payHash && (
            <TxLink
              chainId={onchain.chainId}
              hash={props.payHash}
              label={t('button.viewTx')}
            />
          )}
        </>
      )

    case 'syncing':
      return (
        <>
          <WaitingRow>{t('syncing')}</WaitingRow>
          {props.payHash && (
            <TxLink
              chainId={onchain.chainId}
              hash={props.payHash}
              label={t('button.viewTx')}
            />
          )}
        </>
      )

    case 'rejected':
      return (
        <>
          <Note>{t('rejected')}</Note>
          <GhostButton onClick={props.onRetry}>{t('button.retry')}</GhostButton>
        </>
      )

    case 'failed':
      // Terminal: the chain answered, and the answer was no. Retrying the
      // same call cannot change that, so no retry is offered here — a
      // NETWORK failure lands on chain_unreachable below, which does.
      return (
        <>
          <Note tone="error">{t('failed')}</Note>
          {props.payHash && (
            <TxLink
              chainId={onchain.chainId}
              hash={props.payHash}
              label={t('button.viewTx')}
            />
          )}
        </>
      )

    case 'chain_unreachable':
      // No transaction exists, so nothing may be claimed or linked about one.
      return (
        <>
          <Note>{t('networkDown')}</Note>
          <GhostButton onClick={props.onRetry}>{t('button.retry')}</GhostButton>
        </>
      )

    case 'wallet_chain_unsupported':
      // The wallet's limitation, not a payment failure and not an outage.
      // Nothing was broadcast, so as with chain_unreachable nothing may be
      // claimed or linked about a transaction. Retrying THIS wallet cannot
      // help, so the only control offered is a different one.
      return (
        <>
          <Note>{t('walletChainUnsupported', { network: props.networkLabel })}</Note>
          {props.canSwitchWallet && (
            <GhostButton onClick={props.onUseOtherWallet}>
              {t('button.otherWallet')}
            </GhostButton>
          )}
        </>
      )

    case 'confirmation_unknown':
      // A transaction IS out there and we cannot read its outcome. The
      // explorer link is the payer's independent proof, and it works when
      // this product does not.
      return (
        <>
          <Note>{t('confirmationUnknown')}</Note>
          {props.payHash && (
            <TxLink
              chainId={onchain.chainId}
              hash={props.payHash}
              label={t('button.viewTx')}
            />
          )}
        </>
      )

    // success is rendered by StatusViews.SuccessView, never here.
    default:
      return null
  }
}
