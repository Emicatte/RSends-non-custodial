import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Table, UL, LI, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Hosted checkout',
  description:
    'The RSends hosted checkout connects the payer’s own wallet and calls router.pay(...) in the browser — no card fields, no processor. Reconcile from the webhook, never from the browser redirect.',
}

export default function HostedCheckoutPage() {
  return (
    <>
      <PageHeader
        eyebrow="Payments"
        title="Hosted checkout"
        lead={
          <>
            The fastest way to collect a payment: send the payer to a page that connects{' '}
            <strong>their own wallet</strong> and submits the on-chain payment for you. You write no
            wallet code and never handle a private key.
          </>
        }
      />

      <H2>Where it lives</H2>
      <P>
        After you <A href="/docs/payment-intents">create an intent</A>, redirect the payer to the
        hosted checkout, keyed by the <Code>intent_id</Code>:
      </P>
      <CodeBlock label="checkout URL" code="https://demo.rsends.io/pay/{intent_id}" />

      <H2>What the page does</H2>
      <P>
        The checkout re-fetches the intent&apos;s <Code>onchain</Code> instructions and walks the
        payer through a normal wallet flow:
      </P>
      <UL>
        <LI>
          <strong>Connect a wallet.</strong> The payer connects their own wallet (MetaMask,
          Coinbase Wallet, WalletConnect, …). The funds and the keys are always theirs.
        </LI>
        <LI>
          <strong>Approve, then pay.</strong> For an ERC-20 token, the wallet first approves{' '}
          <Code>amount + fee</Code> to the router, then calls{' '}
          <Code>pay(invoiceId, merchant, token, amount, maxFee)</Code>. Native ETH skips approval and
          calls <Code>payNative(...)</Code> with <Code>msg.value</Code>.
        </LI>
        <LI>
          <strong>Settle atomically.</strong> In one transaction the router sends your amount to your
          wallet, the fee to the fee collector, and emits <Code>PaymentMade</Code>.
        </LI>
      </UL>
      <CodeBlock
        label="the call the browser makes"
        code={`// Read straight from intent.onchain — nothing is invented client-side.
router.pay(
  invoiceId,   // onchain.invoiceId  (bytes32, derived from your reference)
  merchant,    // onchain.merchant   (your destination wallet)
  token,       // onchain.token      (e.g. test USDC)
  amount,      // onchain.amount     (base units)
  maxFee       // onchain.maxFee     (payer's ceiling; reverts if quoteFee exceeds it)
)`}
      />

      <Callout variant="info" title="No card fields, no processor">
        There are no PCI form fields here and no payment processor in the path. The page is just a
        wallet front-end for an on-chain call. RSends is never a party to the transfer — it only
        prepared the parameters and will later observe the result.
      </Callout>

      <H2>The golden rule</H2>
      <P>
        When the payment lands, the browser will redirect or show a success screen. That is a{' '}
        <strong>UI hint, not proof of payment.</strong> A redirect can be faked, refreshed, or lost.
      </P>
      <Callout variant="warn" title="Never mark an order paid from the browser redirect">
        Treat the redirect as “the customer says they paid.” The authoritative signal is the{' '}
        <A href="/docs/webhooks">
          <Code>payment.completed</Code> webhook
        </A>{' '}
        — verified by its signature — or the on-chain <Code>PaymentMade</Code> event read directly.
        Fulfil only after you have reconciled against one of those.
      </Callout>

      <H3>Recommended flow</H3>
      <Table
        head={['Where', 'Do']}
        rows={[
          ['Browser', 'Show a friendly “processing / thank you” state on redirect. Do not fulfil yet.'],
          ['Server (webhook)', <>Receive <Code>payment.completed</Code>, verify the signature, then mark the order paid and fulfil.</>],
          ['Anywhere', <>Optionally cross-check the <Code>PaymentMade</Code> event on-chain for full independence.</>],
        ]}
      />

      <H3>Build your own checkout?</H3>
      <P>
        You don&apos;t have to use the hosted page. Because the intent response hands you the full{' '}
        <Code>onchain</Code> object (router, invoiceId, token, amount, fee, calldata), you can drive{' '}
        <Code>pay(...)</Code> from your own front-end. The settlement and reconciliation model is
        identical — the webhook and the chain remain the source of truth.
      </P>

      <PageNav
        prev={{ href: '/docs/payment-intents', label: 'Payment intents' }}
        next={{ href: '/docs/webhooks', label: 'Webhooks' }}
      />
    </>
  )
}
