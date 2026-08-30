'use client'

/**
 * HostedCheckout — the thin orchestrator of the hosted checkout page.
 *
 * usePaymentIntent drives data (skeleton → not_found/terminal/active);
 * useHostedCheckout drives the wallet flow. Terminal intent states render
 * status cards INSTEAD of any wallet UI. This is the ONLY component (with
 * CheckoutClient) that imports RainbowKit: the Connect button is passed
 * into ActionArea as a slot so every tested unit stays wallet-lib-free.
 */

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { ConnectButton } from '@rainbow-me/rainbowkit'
import { C } from '@/app/designTokens'
import { Eyebrow, Mono } from '@/app/pay/_components/payUi'
import { payFlowFor } from '@/lib/web3/chainFamily'
import { useHostedCheckout } from '@/lib/web3/useHostedCheckout'
import { usePaymentIntent } from '@/lib/web3/usePaymentIntent'
import { formatTokenAmount } from '@/lib/web3/feeMath'
import {
  formatCountdown,
  merchantName,
  terminalKind,
  type PaymentIntent,
} from '@/lib/web3/paymentIntent'
import { ActionArea } from './ActionArea'
import { CheckoutFrame } from './CheckoutFrame'
import { CheckoutSkeleton } from './CheckoutSkeleton'
import { TronCheckout } from './TronCheckout'
import {
  GasNote,
  PayerAddress,
  SplitBreakdown,
  TotalHeadline,
} from './SummarySection'
import { TrustFooter } from './TrustFooter'
import {
  AlreadyPaidView,
  ErrorDetail,
  ExpiredView,
  NetworkErrorView,
  NotFoundView,
  SuccessView,
} from './StatusViews'

export default function HostedCheckout() {
  const { intentId } = useParams<{ intentId: string }>()
  const { phase, backendPaid, refresh, startSyncPolling } =
    usePaymentIntent(intentId)

  if (phase.kind === 'loading') return <CheckoutSkeleton slow={phase.slow} />
  if (phase.kind === 'not_found') return <NotFoundView />
  if (phase.kind === 'unreachable') {
    return <NetworkErrorView onRetry={refresh} detail={phase.detail} />
  }

  const intent = phase.intent

  // Which flow this intent belongs to is decided by its CHAIN, never by
  // `onchain == null`. On a watch-only chain a null block is the normal shape
  // (there is no contract to call), while on a router chain it means the
  // intent is unpayable — branching on the null would render a valid TRON
  // invoice as a broken EVM one, and vice versa.
  if (payFlowFor(intent) === 'tron_instructions') {
    return <TronCheckout intent={intent} onLocalExpiry={refresh} />
  }

  // An intent that is terminal on arrival never mounts wallet UI. Status
  // flips DURING an active payment session are handled inside CheckoutActive
  // (which knows whether a tx of ours is in flight).
  if (!intent.onchain) {
    const kind = terminalKind(intent.status)
    if (kind === 'expired') return <ExpiredView />
    if (kind === 'already_paid') {
      return (
        <AlreadyPaidView
          chainId={null}
          chain={intent.raw.chain}
          txHash={intent.txHash}
        />
      )
    }
    // Pending but the on-chain payment block is missing: keep the reserved
    // skeleton; the watch poll keeps refetching and recovers when the
    // backend ships the fields.
    return <CheckoutSkeleton slow={false} />
  }

  return (
    <CheckoutActive
      intent={intent}
      backendPaid={backendPaid}
      onMined={startSyncPolling}
      onLocalExpiry={refresh}
    />
  )
}

function CheckoutActive({
  intent,
  backendPaid,
  onMined,
  onLocalExpiry,
}: {
  intent: PaymentIntent
  backendPaid: boolean
  onMined: () => void
  onLocalExpiry: () => void
}) {
  const t = useTranslations('pay')
  const onchain = intent.onchain!
  const checkout = useHostedCheckout(onchain, { backendPaid, onMined })

  const paymentInFlight =
    checkout.payHash != null ||
    checkout.step === 'paying' ||
    checkout.step === 'syncing' ||
    checkout.step === 'success'

  // ── Expiry countdown (backend stays authoritative: local zero just
  //    triggers a confirming refetch, which reports effective expiry) ──
  const [remainingMs, setRemainingMs] = useState(() =>
    Math.max(0, new Date(intent.expiresAt).getTime() - Date.now()),
  )
  const expiryNotifiedRef = useRef(false)
  useEffect(() => {
    const tick = () => {
      const ms = Math.max(0, new Date(intent.expiresAt).getTime() - Date.now())
      setRemainingMs(ms)
      if (ms <= 0 && !expiryNotifiedRef.current) {
        expiryNotifiedRef.current = true
        onLocalExpiry()
      }
    }
    tick()
    const id = window.setInterval(tick, 1_000)
    return () => window.clearInterval(id)
  }, [intent.expiresAt, onLocalExpiry])

  // ── Terminal outcomes ──
  if (checkout.step === 'success') {
    return (
      <SuccessView
        // checkout.total is non-null by the time step === 'success' (pay()
        // never fires with a null total); the ?? is unreachable narrowing.
        amount={formatTokenAmount(checkout.total ?? onchain.amount, onchain.decimals)}
        currency={intent.currency}
        merchant={merchantName(intent)}
        chainId={onchain.chainId}
        txHash={checkout.payHash ?? intent.txHash}
        payer={checkout.address}
      />
    )
  }
  const kind = terminalKind(intent.status)
  if (kind === 'expired' && !paymentInFlight) return <ExpiredView />
  if (kind === 'already_paid' && !paymentInFlight) {
    return (
      <AlreadyPaidView
        chainId={onchain.chainId}
        chain={intent.raw.chain}
        txHash={intent.txHash}
      />
    )
  }

  return (
    <CheckoutFrame
      header={
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <Eyebrow>{t('payTo')}</Eyebrow>
            <span
              style={{
                fontFamily: C.D,
                fontSize: 15,
                fontWeight: 600,
                color: C.text,
              }}
            >
              {merchantName(intent)}
            </span>
          </div>
          <span style={{ fontFamily: C.D, fontSize: 12, color: C.sub }}>
            {t('expiresIn')}{' '}
            <Mono style={{ fontSize: 12, color: C.text }}>
              {formatCountdown(remainingMs)}
            </Mono>
          </span>
        </div>
      }
      wallet={
        // Which account is about to pay, always visible once connected. The
        // control is RainbowKit's own (its modal carries copy-address and
        // disconnect) and is mounted ONLY while nothing of ours has been
        // broadcast; from the first hash onward the same line degrades to an
        // inert address, so no affordance can drop a wallet mid-payment.
        checkout.address == null ? null : checkout.canSwitchWallet ? (
          <ConnectButton
            chainStatus="none"
            showBalance={false}
            accountStatus="address"
          />
        ) : (
          <PayerAddress address={checkout.address} label={t('payingFrom')} />
        )
      }
      amount={
        <TotalHeadline
          total={checkout.total}
          currency={intent.currency}
          decimals={onchain.decimals}
        />
      }
      summary={
        onchain.split ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <SplitBreakdown
              split={onchain.split}
              currency={intent.currency}
              decimals={onchain.decimals}
            />
            <GasNote />
          </div>
        ) : (
          <GasNote />
        )
      }
      action={
        <ActionArea
          step={checkout.step}
          onchain={onchain}
          currency={intent.currency}
          total={checkout.total}
          networkLabel={intent.chainLabel}
          connectSlot={
            <ConnectButton
              label={t('button.connect')}
              chainStatus="none"
              showBalance={false}
            />
          }
          approveHash={checkout.approveHash}
          payHash={checkout.payHash}
          waitingLong={checkout.waitingLong}
          canSwitchWallet={checkout.canSwitchWallet}
          onSwitch={checkout.switchNetwork}
          onApprove={checkout.approve}
          onPay={() => void checkout.pay()}
          onUseOtherWallet={checkout.useDifferentWallet}
          onRetry={
            checkout.step === 'chain_unreachable'
              ? checkout.retryReads
              : checkout.retry
          }
        />
      }
      notice={
        // The frame reserves this line whether or not it is filled, so
        // showing a code during an outage cannot shift the card.
        checkout.step === 'chain_unreachable' && checkout.errorDetail ? (
          <ErrorDetail detail={checkout.errorDetail} />
        ) : null
      }
      footer={<TrustFooter chainId={onchain.chainId} router={onchain.router} />}
    />
  )
}
