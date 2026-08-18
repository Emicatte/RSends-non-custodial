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
              <Code>demo.rsends.io/pay/{'{intent_id}'}</Code>. They connect <em>their own</em>{' '}
              wallet and approve the payment in the browser.
            </>,
          ],
          [
            <strong key="3">3. Settle on-chain</strong>,
            <>
              The browser calls <Code>pay(...)</Code> on the router. The stablecoin moves payer →
              your wallet and a <Code>PaymentMade</Code> event is emitted, atomically. Your amount
              always arrives whole; on the sandbox router the payer additionally covers a small
              on-chain fee on top (see <A href="/docs/payment-intents">Payment intents</A>).
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

      <H2 id="environments">Environments</H2>
      <P>
        There are two environments. <strong>Sandbox</strong> is live today and is what a partner can
        integrate against right now. <strong>Production</strong> is not deployed yet — the mainnet
        router has not been published, so the values below are marked as pending and will be filled
        in at launch.
      </P>
      <Table
        head={['', 'Sandbox', 'Production']}
        rows={[
          [
            <strong key="b">Base URL</strong>,
            <Code key="bs">https://pay.rsends.io/api/backend</Code>,
            <em key="bp">Pending — assigned at launch</em>,
          ],
          [
            <strong key="n">Network</strong>,
            'Base Sepolia — chain id 84532',
            'Base mainnet — chain id 8453',
          ],
          [
            <strong key="k">API keys</strong>,
            <Code key="ks">rsend_test_…</Code>,
            <Code key="kp">rsend_live_…</Code>,
          ],
          [
            <strong key="t">Tokens</strong>,
            'USDC and native ETH (test tokens, no real value)',
            <em key="tp">Enabled per jurisdiction at rollout</em>,
          ],
          [
            <strong key="r">Router</strong>,
            <>
              <Code>0x2Ec3…58CA</Code> — <Code>routerVersion 1</Code>, charges an on-chain flat fee
            </>,
            <em key="rp">Pending — RSendsRouterV2, fee-less</em>,
          ],
          [
            <strong key="c">Checkout</strong>,
            <Code key="cs">demo.rsends.io/pay/{'{intent_id}'}</Code>,
            <em key="cp">Pending</em>,
          ],
        ]}
      />
      <P>
        The REST API is served over HTTPS and every response is <Code>application/json</Code>.
        Endpoint paths are identical in both environments — only the base URL, the key and the chain
        change. So the sandbox call for <Code>/api/v1/merchant/payment-intent</Code> is:
      </P>
      <CodeBlock
        label="sandbox — full URL"
        code="https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent"
      />
      <Callout variant="info" title="Why the base URL carries an /api/backend prefix">
        The sandbox API is reached through the RSends edge, which forwards your{' '}
        <Code>Authorization</Code>, <Code>Content-Type</Code> and <Code>X-Idempotency-Key</Code>{' '}
        headers to the backend and returns its status and body verbatim. Two consequences worth
        knowing up front: response headers other than <Code>Content-Type</Code> are not passed back
        (so the <Code>X-RateLimit-*</Code> headers are not visible on this base URL — the limits
        themselves still apply, and are documented in <A href="/docs/errors">Errors</A>), and a
        request that takes longer than 25 seconds returns{' '}
        <Code>502 BACKEND_UNREACHABLE</Code>. A dedicated API hostname is planned for launch.
      </Callout>

      <H2>Getting started in three steps</H2>
      <P>
        The <A href="/docs/quickstart">Quickstart</A> walks all of this end to end, with working
        calls.
      </P>
      <Table
        head={['Step', 'What you do']}
        rows={[
          [
            <strong key="1">1. Get an API key</strong>,
            <>
              Self-serve: sign in, open <Code>/app</Code> → API keys → Merchant keys and create a{' '}
              <Code>rsend_test_</Code> key (org <Code>admin</Code> role required). Your organisation
              must be <strong>approved</strong> before the merchant API answers — see{' '}
              <A href="/docs/authentication">Authentication</A>.
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

      <PageNav next={{ href: '/docs/quickstart', label: 'Quickstart' }} />
    </>
  )
}
