import type { Metadata } from 'next'
import { CodeBlock } from './_components/CodeBlock'
import { Callout } from './_components/Callout'
import { H2, H3, P, A, Code, Table, UL, LI, PageHeader, PageNav } from './_components/primitives'

export const metadata: Metadata = {
  title: 'Overview',
  description:
    'Accept stablecoin payments without holding funds or keys. RSends settles payments directly payer → merchant on-chain through an immutable router — no balance, no reserve, no payout.',
}

export default function OverviewPage() {
  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Accept stablecoin payments without holding funds or keys."
        lead={
          <>
            RSends is a <strong>non-custodial</strong> stablecoin payment gateway. Your customer
            pays in stablecoin on Base, and the funds settle on-chain <strong>directly into your
            own wallet</strong> through an immutable smart contract — the router. RSends never
            holds, controls, or can move them.
          </>
        }
      />

      <H2>Funds are yours the instant the transaction confirms</H2>
      <P>
        This is the whole point of RSends, and what makes it different from a custodial processor.
        There is <strong>no balance to track, no reserve withheld, and no payout to wait for</strong>:
        the payer&apos;s wallet sends the stablecoin straight to your wallet in the same transaction
        that records the payment. RSends only watches the chain and tells you it happened.
      </P>
      <Callout variant="info" title="The contrast, stated plainly">
        A custodial card processor receives your customer&apos;s money, parks it in a balance, keeps
        a reserve against chargebacks, and pays you out days later. RSends does none of that — it
        never receives the money at all. The only thing it moves is information.
      </Callout>

      <H2>How a payment flows</H2>
      <Table
        head={['Step', 'What happens']}
        rows={[
          [
            <strong key="1">1. Create an intent</strong>,
            <>
              Your server calls <Code>POST /api/v1/merchant/payment-intent</Code> with the amount,
              settlement token and your destination wallet. You get back the intent and its{' '}
              <Code>onchain</Code> pay instructions.
            </>,
          ],
          [
            <strong key="2">2. Send the payer to checkout</strong>,
            <>
              Redirect the customer to the hosted checkout on{' '}
              <Code>demo.rsends.io/pay/{'{intentId}'}</Code>. They connect <em>their own</em> wallet
              and approve the payment in the browser.
            </>,
          ],
          [
            <strong key="3">3. Settle on-chain</strong>,
            <>
              The browser calls <Code>pay(...)</Code> on the router. The stablecoin moves payer →
              your wallet — one transfer, no fee in the flow — and a <Code>PaymentMade</Code>{' '}
              event is emitted, all atomically.
            </>,
          ],
          [
            <strong key="4">4. Reconcile</strong>,
            <>
              RSends indexes the event, matches it to your intent, and delivers a{' '}
              <Code>payment.completed</Code> webhook carrying the on-chain proof. You can also read
              the chain yourself.
            </>,
          ],
        ]}
      />

      <H2>Base URL</H2>
      <P>
        The REST API is served over HTTPS. Every response is <Code>application/json</Code>. Examples
        in these docs use:
      </P>
      <CodeBlock label="Base URL" code="https://pay.rsends.io" />
      <P>
        Merchant endpoints live under <Code>/api/v1/merchant/*</Code> and are authenticated with a
        secret API key — see <A href="/docs/authentication">Authentication</A>.
      </P>

      <H2>Getting started in three steps</H2>
      <Table
        head={['Step', 'What you do']}
        rows={[
          [
            <strong key="1">1. Get an API key</strong>,
            <>
              RSends is in private beta — keys are issued by the operator, scoped to{' '}
              <Code>test</Code> or <Code>live</Code>. There is no self-serve signup yet.
            </>,
          ],
          [
            <strong key="2">2. Create &amp; host a payment</strong>,
            <>
              Call <A href="/docs/payment-intents">Payment intents</A> and send the payer to the{' '}
              <A href="/docs/hosted-checkout">hosted checkout</A>.
            </>,
          ],
          [
            <strong key="3">3. Listen for webhooks</strong>,
            <>
              Register a <A href="/docs/webhooks">webhook</A> and verify every delivery&apos;s
              signature before trusting it.
            </>,
          ],
        ]}
      />

      <H2>Verify on-chain yourself</H2>
      <P>
        Because settlement is on-chain, you never have to take RSends&apos; word for it. Every
        payment is a public <Code>PaymentMade</Code> event you can read directly on BaseScan,
        keyed by your <Code>reference</Code> (the on-chain <Code>invoiceId</Code>).
      </P>
      <Callout variant="chain" title="The chain is the source of truth">
        The webhook is a convenience; the blockchain is the record. Anyone — you, your auditor, your
        customer — can independently confirm a payment settled, for the right amount, to the right
        wallet, without any access to RSends. Trust is not required.
      </Callout>

      <H3>What you&apos;ll need</H3>
      <UL>
        <LI>
          A destination wallet address you control (an EOA or smart wallet on Base). This is where
          your money lands — RSends never holds the keys.
        </LI>
        <LI>A server that can call the REST API and receive webhooks.</LI>
        <LI>
          For testing: a wallet funded from public faucets — see <A href="/docs/testing">Testing</A>.
        </LI>
      </UL>

      <PageNav next={{ href: '/docs/authentication', label: 'Authentication' }} />
    </>
  )
}
