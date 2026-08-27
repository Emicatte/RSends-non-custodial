/**
 * The payer-facing `pay` i18n namespace: key parity across all 5 locales,
 * the FINAL English copy verbatim, and the copy-discipline constraints (no
 * em dashes, no exclamation marks) in every locale.
 */
import en from '@/messages/en.json'
import itMessages from '@/messages/it.json'
import es from '@/messages/es.json'
import fr from '@/messages/fr.json'
import de from '@/messages/de.json'

const LOCALES: Record<string, Record<string, unknown>> = {
  en,
  it: itMessages,
  es,
  fr,
  de,
}

function keyTree(node: unknown, prefix = ''): string[] {
  if (typeof node !== 'object' || node === null) return [prefix]
  return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) =>
    keyTree(v, prefix ? `${prefix}.${k}` : k),
  )
}

function stringValues(node: unknown): string[] {
  if (typeof node === 'string') return [node]
  if (typeof node !== 'object' || node === null) return []
  return Object.values(node as Record<string, unknown>).flatMap(stringValues)
}

const EN_VERBATIM: Record<string, string> = {
  'summary.gasNote': 'Your wallet adds a small network gas fee on top.',
  'trust.nonCustodial':
    "Funds go directly to the merchant's wallet. RSends never holds your money.",
  'trust.contract': 'Executed by an immutable smart contract.',
  'trust.viewContract': 'View contract',
  'button.connect': 'Connect wallet',
  'button.switch': 'Switch network',
  'button.approve': 'Approve {token}',
  'button.pay': 'Pay {amount} {token}',
  'button.viewTx': 'View transaction',
  'button.retry': 'Try again',
  'button.otherWallet': 'Use a different wallet',
  'steps.approve': 'Step 1 of 2: Approve {token}',
  'steps.confirm': 'Step 2 of 2: Confirm payment',
  approveExplainer:
    'First allow the contract to use your {token}, then confirm the payment. Two wallet confirmations in total.',
  wrongNetwork: 'This payment runs on {network}. Switch your wallet to continue.',
  insufficient:
    'Not enough {token} in this wallet. You need {amount} {token} plus gas.',
  waitingWallet: 'Waiting for confirmation in your wallet.',
  txPending: 'Transaction sent. Waiting for the network.',
  syncing: "Confirmed on-chain. Updating the merchant's records.",
  'success.title': 'Payment complete',
  'success.body': 'You paid {amount} {token} to {merchant}.',
  rejected: 'You canceled the request in your wallet. Nothing was sent.',
  failed:
    'The transaction did not complete. No payment left your wallet. Check the details on the explorer.',
  expired: 'This payment link has expired. Ask the merchant for a new one.',
  alreadyPaid: 'This payment was already completed.',
  notFound: 'We could not find this payment. Check the link and try again.',
  loadingRetry: 'Taking longer than usual. Retrying.',
  // Network-failure copy. The cause is the network, never the payer or the
  // merchant, and the wording never overstates certainty in either direction:
  // "has not started" only where no transaction exists, "cannot confirm"
  // where one does. No jargon (no RPC, no provider, no error code) in the
  // headline — the raw code lives in the collapsed detail.
  networkDown:
    'The network is not responding right now. Your payment has not started.',
  backendDown:
    'We cannot reach the payment service right now. Nothing has been charged.',
  confirmationUnknown:
    'Your transaction was sent. We cannot confirm it right now. Check it on the explorer.',
  errorDetails: 'Technical details',
  // Wallet-side copy. The subject is the WALLET, never RSends and never the
  // payer: a wallet that refuses a chain has not failed a payment, it has
  // declined to start one. Both lines say plainly that nothing moved, and
  // both point at the same remedy the page now offers.
  walletSilent:
    'Your wallet has not answered yet. Check for a wallet window or popup. If it says this network is not supported, you can pay with a different wallet.',
  walletChainUnsupported:
    'This wallet does not support {network}. Nothing was sent and nothing was charged. You can pay with a different wallet.',
  payingFrom: 'Paying from',
  paidFrom: 'Paid from',
}

function resolve(obj: unknown, path: string): unknown {
  return path
    .split('.')
    .reduce<unknown>(
      (node, part) => (node as Record<string, unknown> | undefined)?.[part],
      obj,
    )
}

describe('pay namespace', () => {
  it('exists in every locale with an identical key tree', () => {
    const enKeys = keyTree((en as Record<string, unknown>).pay).sort()
    expect(enKeys.length).toBeGreaterThan(20)
    for (const [locale, messages] of Object.entries(LOCALES)) {
      const keys = keyTree(messages.pay).sort()
      expect({ locale, keys }).toEqual({ locale, keys: enKeys })
    }
  })

  it('carries the final English copy verbatim', () => {
    for (const [path, expected] of Object.entries(EN_VERBATIM)) {
      expect({ path, value: resolve((en as Record<string, unknown>).pay, path) })
        .toEqual({ path, value: expected })
    }
  })

  it('has no em dashes and no exclamation marks in any locale', () => {
    for (const [locale, messages] of Object.entries(LOCALES)) {
      for (const value of stringValues(messages.pay)) {
        expect({ locale, value, hasEmDash: /[—–]/.test(value) }).toEqual({
          locale,
          value,
          hasEmDash: false,
        })
        expect({ locale, value, hasBang: value.includes('!') }).toEqual({
          locale,
          value,
          hasBang: false,
        })
      }
    }
  })
})
