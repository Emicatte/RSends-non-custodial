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
      <CodeBlock
        label="checkout URL"
        code="https://demo.rsends.io/pay/pi_9f1c4a7e2b5d8036c1e94ab7d2508f63"
      />
      <P>
        The <Code>intent_id</Code> is the only credential the page needs — it is 128 bits of
        randomness, so it is not guessable, but it <em>is</em> the key to that intent&apos;s
        checkout. Treat the link as you would a payment link anywhere else.
      </P>

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
          <strong>Approve, then pay.</strong> For an ERC-20 token, the wallet approves the router
          for <Code>onchain.total</Code>, then calls <Code>pay(...)</Code>. Native ETH skips the
          approval and calls <Code>payNative(...)</Code> with <Code>msg.value</Code> equal to the
          total. Tokens that support EIP-2612 (<Code>onchain.permitType: &quot;eip2612&quot;</Code>,
          which includes USDC) can sign a permit instead of sending a separate approval
          transaction.
        </LI>
        <LI>
          <strong>Settle atomically.</strong> One transaction: the router moves your{' '}
          <Code>amount</Code> to your wallet and emits <Code>PaymentMade</Code>. Your principal is
          never touched — on the currently-deployed router the payer additionally covers the flat
          fee, which is why the approval is for <Code>total</Code>, not <Code>amount</Code>.
        </LI>
      </UL>
      <CodeBlock
        label="the call the browser makes — routerVersion 1 (deployed today)"
        code={`// Read straight from intent.onchain — nothing is invented client-side.
router.pay(
  invoiceId,   // onchain.invoiceId  (bytes32, derived from your reference)
  merchant,    // onchain.merchant   (your destination wallet)
  token,       // onchain.token      (e.g. USDC)
  amount,      // onchain.amount     (base units — what YOU receive)
  maxFee       // onchain.maxFee     (payer's ceiling; reverts above it)
)

// routerVersion 2 (mainnet cutover) drops the fee argument entirely:
// router.pay(invoiceId, merchant, token, amount)`}
      />
      <Callout variant="info" title="Don’t hardcode the ABI — read routerVersion">
        The two routers take different arguments. <Code>onchain.routerVersion</Code> tells you
        which one you are on, and <Code>onchain.calldata</Code> ships ready-to-send bytes for
        whichever it is. Building against the field rather than the shape means the mainnet cutover
        needs no change on your side.
      </Callout>

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
        <Code>onchain</Code> object (router, routerVersion, invoiceId, token, amount, total,
        calldata, permitType), you can drive <Code>pay(...)</Code> from your own front-end. The
        settlement and reconciliation model is identical — the webhook and the chain remain the
        source of truth.
      </P>
      <P>
        Your front-end can also read the payer-facing view of an intent directly, without an API
        key: <Code>GET /api/v1/public/payment-intent/{'{intent_id}'}</Code> returns{' '}
        <Code>status</Code>, <Code>amount</Code>, <Code>currency</Code>, <Code>chain</Code>,{' '}
        <Code>expires_at</Code>, <Code>merchant_name</Code>, <Code>tx_hash</Code> and the same{' '}
        <Code>onchain</Code> object — and nothing else. It is what the hosted checkout itself
        polls. The <Code>intent_id</Code> is the credential, so keep the link private; rate limit
        is 20/min per IP.
      </P>

      <PageNav
        prev={{ href: '/docs/payment-intents', label: 'Payment intents' }}
        next={{ href: '/docs/webhooks', label: 'Webhooks' }}
      />
    </>
  )
}
