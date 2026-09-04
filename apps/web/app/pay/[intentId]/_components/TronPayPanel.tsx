'use client'

/**
 * TronPayPanel — the connect-and-pay half of the TRON checkout.
 *
 * Everything it knows comes from two hooks: `useTronWallet` for the session and
 * `useTronPayment` for the payment. It holds no chain logic of its own, which
 * is the point — the states below are a rendering of a machine that is tested
 * separately, not a second copy of the rules.
 *
 * The copy is deliberately literal about what is and is not known. "Payment
 * sent" is not "payment complete": only the backend's paid status produces the
 * latter, so the processing copy says what the payer is waiting for and roughly
 * how long. An inclusion timeout is phrased as information rather than failure
 * because the transfer may still land. And disconnect says the session on this
 * page was cleared, because TronLink cannot be disconnected by a website and
 * claiming otherwise would be a small lie the payer can check.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'

import { C } from '@/app/designTokens'
import {
  Eyebrow,
  GhostButton,
  Mono,
  PrimaryButton,
  Spinner,
  truncate,
} from '@/app/pay/_components/payUi'
import { explorerTxUrl } from '@/lib/web3/explorer'
import type { PaymentIntent } from '@/lib/web3/paymentIntent'
import type { TronNetworkConfig } from '@/lib/web3/tron/tronNetwork'
import { SUN_PER_TRX } from '@/lib/web3/tron/tronResources'
import { useTronPayment } from '@/lib/web3/tron/useTronPayment'

import { useTronWallet } from './TronWalletProvider'

const TRONLINK_INSTALL = 'https://www.tronlink.org/'

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
      <span style={{ fontFamily: C.D, fontSize: 12, color: C.sub }}>{label}</span>
      <Mono style={{ fontSize: 12, color: C.text }}>{value}</Mono>
    </div>
  )
}

function Line({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ margin: 0, fontFamily: C.D, fontSize: 13, color: C.sub, lineHeight: 1.5 }}>
      {children}
    </p>
  )
}

export function TronPayPanel({
  intent,
  network,
  backendPaid,
  onBroadcast,
}: {
  intent: PaymentIntent
  network: TronNetworkConfig
  backendPaid: boolean
  onBroadcast: () => void
}) {
  const t = useTranslations('pay')
  const wallet = useTronWallet()
  const { status, quote, pay, reset } = useTronPayment(intent, network, wallet, {
    backendPaid,
    onBroadcast,
  })
  const [picking, setPicking] = useState(false)

  const amount = intent.amountExact ?? ''
  const token = intent.currency
  const tronlink = wallet.options.find((o) => o.kind === 'tronlink')
  const explorer = (hash: string) => explorerTxUrl(null, hash, intent.raw.chain)

  const busy = (label: string) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <Spinner />
      <Line>{label}</Line>
    </div>
  )

  const txLink = (hash: string) => {
    const href = explorer(hash)
    if (!href) return <Mono style={{ fontSize: 12 }}>{truncate(hash, 10, 8)}</Mono>
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: C.purple }}>
        {t('button.viewTx')}
      </a>
    )
  }

  // ── Not connected ──────────────────────────────────────────────
  if (!wallet.address) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <Line>{t('tron.connectPrompt')}</Line>

        {!picking && (
          <PrimaryButton onClick={() => setPicking(true)}>
            {t('button.connect')}
          </PrimaryButton>
        )}

        {picking &&
          wallet.options.map((option) => (
            <GhostButton
              key={option.kind}
              // `checking` is a probe still running, not a missing wallet, so
              // the control is disabled rather than absent or offered as broken.
              disabled={option.availability === 'checking'}
              onClick={() => void wallet.connect(option.kind)}
            >
              {option.label}
            </GhostButton>
          ))}

        {tronlink?.availability === 'checking' && <Line>{t('tron.checking')}</Line>}

        {tronlink?.availability === 'absent' && (
          <>
            <Line>{t('tron.notInstalled')}</Line>
            <a
              href={TRONLINK_INSTALL}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontFamily: C.D, fontSize: 13, color: C.purple }}
            >
              {t('tron.install')}
            </a>
          </>
        )}

        {/* Desktop WalletConnect: our own QR, in this page's styling, because
            `onUri` skips the adapter's modal entirely. */}
        {wallet.wcUri && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Line>{t('tron.scanToConnect')}</Line>
            <Mono style={{ fontSize: 10, wordBreak: 'break-all', color: C.sub }}>
              {wallet.wcUri}
            </Mono>
          </div>
        )}

        {wallet.status === 'connecting' && busy(t('tron.checking'))}
        {wallet.error && <Line>{t('tron.connectError')}</Line>}

        {/* Shown disabled before a wallet exists, so the payer can see what
            they are about to authorise and for how much. It is the only other
            place on the page that names the amount — the instruction block
            being the first — which keeps "how much" answerable at a glance
            without connecting anything. */}
        <PrimaryButton disabled onClick={() => {}}>
          {t('button.pay', { amount, token })}
        </PrimaryButton>
      </div>
    )
  }

  // ── Connected ──────────────────────────────────────────────────
  const summary = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <Row label={t('tron.payingFrom')} value={truncate(wallet.address, 6, 6)} />
      {/* Abbreviated on purpose: the full address belongs to the instruction
          block, once, so there is exactly one place to copy it from. */}
      <Row label={t('tron.destination')} value={truncate(intent.recipient ?? '', 6, 6)} />
      <Row label={t('payTo')} value={`${amount} ${token}`} />
      {!wallet.chainReadable && (
        <Line>{t('tron.networkRequested', { network: intent.chainLabel })}</Line>
      )}
    </div>
  )

  const body = () => {
    switch (status.kind) {
      case 'idle':
      case 'connected':
        return (
          <PrimaryButton onClick={() => void pay()}>
            {t('button.pay', { amount, token })}
          </PrimaryButton>
        )

      case 'preflight':
        return busy(t('tron.preflight'))

      case 'awaiting_signature':
        return busy(t('tron.awaitingSignature'))

      case 'signature_expired':
        return busy(t('tron.signatureExpired'))

      case 'broadcasting':
        return busy(t('tron.broadcasting'))

      case 'processing':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Line>
              {status.inclusion === 'timeout'
                ? t('tron.inclusionTimeout')
                : t('tron.processing')}
            </Line>
            {txLink(status.txid)}
          </div>
        )

      case 'paid':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Eyebrow>{t('success.title')}</Eyebrow>
            {status.txid ? txLink(status.txid) : null}
          </div>
        )

      case 'expired':
      case 'already_paid':
        // The page-level views own these; the panel simply steps aside.
        return null

      case 'failed':
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Line>{failureCopy(status.reason, status.detail)}</Line>
            {status.txid ? txLink(status.txid) : null}
            {status.reason === 'wrong_network' && wallet.canSwitchChain && (
              <PrimaryButton onClick={() => void wallet.switchChain(network.chainId)}>
                {t('button.switch')}
              </PrimaryButton>
            )}
            {RETRYABLE.has(status.reason) && (
              <GhostButton onClick={reset}>{t('button.retry')}</GhostButton>
            )}
          </div>
        )
    }
  }

  function failureCopy(reason: string, detail: string): string {
    switch (reason) {
      case 'wrong_network':
        return t('tron.wrongNetwork', { network: intent.chainLabel })
      case 'insufficient_usdt':
        return t('tron.insufficientUsdt', { token, amount })
      case 'insufficient_trx':
        return t('tron.insufficientTrx', {
          trx: quote ? (quote.costSun / SUN_PER_TRX).toFixed(2) : '0',
        })
      case 'user_rejected':
        return t('rejected')
      case 'tx_reverted':
        return t('tron.reverted', { token })
      case 'out_of_energy':
        return t('tron.outOfEnergy', { token })
      case 'wallet_disconnected':
      case 'wallet_not_found':
      case 'connection_failed':
        return t('tron.connectError')
      default:
        // Carries the node's own words when it gave any: a decoded
        // CONTRACT_VALIDATE_ERROR says more than "something went wrong".
        return detail ? `${t('tron.txFailed')} ${detail}` : t('tron.txFailed')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {summary}
      {body()}
      <GhostButton onClick={() => void wallet.disconnect()}>
        {t('tron.disconnect')}
      </GhostButton>
      <Line>{t('tron.disconnectNote')}</Line>
    </div>
  )
}

/** Failures a payer can do something about from this page. */
const RETRYABLE = new Set([
  'user_rejected',
  'wallet_disconnected',
  'connection_failed',
  'network_error',
  'tx_expired',
  'insufficient_trx',
  'insufficient_usdt',
  'unknown',
])

export default TronPayPanel
