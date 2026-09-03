'use client'

/**
 * TronCheckout — the watch-only payment screen.
 *
 * TRON settles without a contract, so this is not a variant of the wallet
 * flow: there is nothing to connect to, nothing to approve, and no transaction
 * for us to build. The payer sends a plain TRC-20 transfer to the merchant's
 * own address and the poller closes the invoice by observing the chain. What
 * the page owes them is therefore an INSTRUCTION, and the two values it hands
 * over have to survive intact.
 *
 * The amount leads, because a human retypes it. `tron_matcher` compares exact
 * base units with zero tolerance: anything short becomes a `partial` intent,
 * which is terminal and does not accumulate — a second transfer completing the
 * sum finds no pending candidate and matches nothing, forever. So the amount
 * is the largest thing on the page, in mono, copyable, and printed exactly as
 * the backend computed it.
 *
 * The address is rendered byte-identical. Base58check is case-sensitive and
 * excludes 0 O I l, so folding a T-address does not give a different address,
 * it gives a string that does not decode. Nothing between the API response and
 * the clipboard touches it — no trim, no case fold, no truncation on the value
 * (only the wrapping is cosmetic).
 *
 * THERE IS NOW A WALLET, and the reason the earlier version of this file gave
 * for not having one is worth recording, because it was right at the time. A
 * TronLink `transfer` deeplink needs the payer's own address (`from` +
 * `loginAddress`) plus a callbackUrl we do not host, and a page with no wallet
 * connection never learns either; a guessed scheme would open a wallet with a
 * wrong or missing amount, which the zero-tolerance matcher would reject. A
 * CONNECTED wallet answers all of that: it tells us the payer's address, so the
 * page builds the exact transfer itself and the wallet only signs it. No
 * deeplink is guessed and no amount is left to a human.
 *
 * The instruction block below is kept, not replaced, and collapsed beneath the
 * wallet flow. Turkish payers move USDT from exchanges, where there is no
 * wallet to connect, and it remains the only path open to them.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import dynamic from 'next/dynamic'
import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { Card, Eyebrow, Mono, Shell, useCopy } from '@/app/pay/_components/payUi'
import { explorerTxUrl } from '@/lib/web3/explorer'
import {
  DEAD_STATES,
  PAID_STATES,
  formatCountdown,
  merchantName,
  type PaymentIntent,
} from '@/lib/web3/paymentIntent'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'
import { AlreadyPaidView, ExpiredView } from './StatusViews'

// Only the instruction screen needs the QR encoder, and only a TRON intent
// reaches the instruction screen — keep `qrcode` out of the shared /pay chunk.
const TronQr = dynamic(() => import('./TronQr').then((m) => m.TronQr), {
  ssr: false,
  loading: () => <QrPlaceholder />,
})

/**
 * The wallet stack, client-only and loaded only on this branch. The EVM route
 * never reaches this file, so its bundle and its hydration are unchanged, and
 * nothing here can probe an injected provider while React is reconciling.
 */
const TronWalletProvider = dynamic(
  () => import('./TronWalletProvider').then((m) => m.TronWalletProvider),
  { ssr: false },
)
const TronPayPanel = dynamic(
  () => import('./TronPayPanel').then((m) => m.TronPayPanel),
  { ssr: false },
)

const QR_SIZE = 176

function QrPlaceholder() {
  return (
    <div
      aria-hidden
      style={{
        width: QR_SIZE,
        height: QR_SIZE,
        borderRadius: 8,
        border: `1px solid ${C.border}`,
        background: C.bg,
      }}
    />
  )
}

/**
 * A value the payer has to reproduce somewhere else, with the button that
 * spares them from typing it. The button is the affordance, but the text is
 * the contract: both carry the same string, unmodified.
 */
function CopyableValue({
  value,
  label,
  children,
}: {
  value: string
  label: string
  children: ReactNode
}) {
  const t = useTranslations('pay')
  const { copied, copy } = useCopy()
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
      <button
        type="button"
        onClick={() => copy(value)}
        aria-label={label}
        style={{
          flexShrink: 0,
          fontFamily: C.M,
          fontSize: 12,
          color: copied ? C.green : C.purple,
          background: 'transparent',
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          padding: '6px 10px',
          minHeight: 32,
          cursor: 'pointer',
          transition: 'color 150ms ease',
        }}
      >
        {copied ? t('tron.copied') : t('tron.copy')}
      </button>
    </div>
  )
}

function Warning({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        margin: 0,
        padding: '10px 12px',
        borderRadius: 10,
        background: 'rgba(255,181,71,0.12)',
        border: '1px solid rgba(255,181,71,0.35)',
        fontFamily: C.D,
        fontSize: 12.5,
        lineHeight: 1.5,
        color: C.text,
      }}
    >
      {children}
    </p>
  )
}

function Note({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        margin: 0,
        fontFamily: C.D,
        fontSize: 12.5,
        lineHeight: 1.5,
        color: C.sub,
      }}
    >
      {children}
    </p>
  )
}

/**
 * An underpayment that has already landed in the merchant's wallet. There is
 * no top-up affordance because there is no top-up: the matcher does not
 * accumulate, so a second transfer would not close this invoice either. The
 * only honest next step is the merchant.
 */
function PartialView({ intent }: { intent: PaymentIntent }) {
  const t = useTranslations('pay')
  const received = intent.amountReceived ?? '0'
  const missing = intent.underpaidAmount
  const txUrl = intent.txHash
    ? explorerTxUrl(null, intent.txHash, intent.raw.chain)
    : null
  return (
    <Shell>
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Eyebrow>{t('tron.partial.title')}</Eyebrow>
          <Note>
            {missing
              ? t('tron.partial.body', {
                  received,
                  missing,
                  token: intent.currency,
                })
              : t('tron.partial.bodyReceivedOnly', {
                  received,
                  token: intent.currency,
                })}
          </Note>
          <Warning>{t('tron.partial.note')}</Warning>
          {txUrl && (
            <a
              href={txUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: C.purple,
                fontFamily: C.D,
                fontSize: 13,
                textDecoration: 'none',
                minHeight: 44,
                display: 'inline-flex',
                alignItems: 'center',
              }}
            >
              {t('button.viewTx')}
            </a>
          )}
        </div>
      </Card>
    </Shell>
  )
}

export function TronCheckout({
  intent,
  onLocalExpiry,
  // Optional so this component still renders standalone: the wallet flow is
  // self-contained, and the polling wiring belongs to whoever owns the intent
  // poll. Defaulted rather than required so a caller that only wants the
  // screen does not have to fabricate a poller.
  backendPaid = false,
  onBroadcast = () => {},
}: {
  intent: PaymentIntent
  onLocalExpiry: () => void
  backendPaid?: boolean
  onBroadcast?: () => void
}) {
  const t = useTranslations('pay')

  // Same contract as the wallet flow: the local clock only triggers a
  // confirming refetch, and the backend's reported status stays authoritative.
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

  // Terminal states, decided on the raw status rather than terminalKind():
  // that helper folds `partial` into "already paid", which is the right
  // conservative answer on a router chain, where partial cannot occur, and the
  // wrong one here, where it is the state this whole screen exists to explain.
  if (intent.status === 'partial') return <PartialView intent={intent} />
  if (PAID_STATES.has(intent.status)) {
    return (
      <AlreadyPaidView
        chainId={null}
        chain={intent.raw.chain}
        txHash={intent.txHash}
      />
    )
  }
  if (DEAD_STATES.has(intent.status)) return <ExpiredView />
  if (intent.status !== 'pending') {
    return (
      <AlreadyPaidView
        chainId={null}
        chain={intent.raw.chain}
        txHash={intent.txHash}
      />
    )
  }

  const address = intent.recipient
  const amount = intent.amountExact
  // Null only for a chain this checkout cannot pay on, which the family gate
  // above already excludes; the guard keeps the wallet flow off screen rather
  // than guessing a network.
  const network = tronNetworkFor(intent.raw.chain)

  // Without an address there is no instruction to give, and inventing one is
  // out of the question. This is the same shape as the EVM "on-chain block is
  // missing" branch: say nothing, let the watch poll recover.
  if (!address || !amount) {
    return (
      <Shell>
        <Card>
          <Note>{t('tron.unavailable')}</Note>
        </Card>
      </Shell>
    )
  }

  return (
    <Shell>
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Who, and how long */}
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

          {/* Connect and pay. The primary path now: the page can know the
              payer's address, so it can build the transfer for them. */}
          {network && (
            <TronWalletProvider network={network}>
              <TronPayPanel
                intent={intent}
                network={network}
                backendPaid={backendPaid}
                onBroadcast={onBroadcast}
              />
            </TronWalletProvider>
          )}

          {/* The manual instructions, kept and collapsed rather than removed.
              Turkish payers move USDT from exchanges, where there is no wallet
              to connect, and this is the only path open to them. Closed by
              default because it is now the secondary route; the content stays
              in the DOM so it is findable and copyable without a round trip. */}
          <details>
            <summary
              style={{
                cursor: 'pointer',
                fontFamily: C.D,
                fontSize: 13,
                color: C.sub,
              }}
            >
              {t('tron.fallbackSummary')}
            </summary>

            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 16,
                paddingTop: 16,
              }}
            >
          {/* The amount. Loudest element on the page, because it is the one a
              human has to reproduce exactly. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Eyebrow>{t('tron.sendExactly')}</Eyebrow>
            <CopyableValue value={amount} label={t('tron.copyAmount')}>
              <Mono
                style={{
                  display: 'block',
                  fontSize: 30,
                  lineHeight: 1.15,
                  fontWeight: 600,
                  color: C.text,
                  wordBreak: 'break-all',
                }}
              >
                {amount}{' '}
                <span style={{ fontSize: 18, color: C.sub }}>
                  {intent.currency}
                </span>
              </Mono>
            </CopyableValue>
            <Note>{t('tron.exactAmountNote')}</Note>
          </div>

          {/* The address */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Eyebrow>{t('tron.toAddress')}</Eyebrow>
            <CopyableValue value={address} label={t('tron.copyAddress')}>
              <Mono
                style={{
                  display: 'block',
                  fontSize: 14,
                  lineHeight: 1.5,
                  color: C.text,
                  wordBreak: 'break-all',
                }}
              >
                {address}
              </Mono>
            </CopyableValue>
          </div>

          {/* The QR of that same address, and nothing more */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <TronQr value={address} size={QR_SIZE} />
            <Note>{t('tron.qrNote')}</Note>
          </div>

          <Warning>
            {t('tron.networkWarning', {
              token: intent.currency,
              network: intent.chainLabel,
            })}
          </Warning>

          <Note>{t('tron.waiting')}</Note>
            </div>
          </details>
        </div>
      </Card>
    </Shell>
  )
}

export default TronCheckout
