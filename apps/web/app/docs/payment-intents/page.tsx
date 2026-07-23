import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Payment intents',
  description:
    'Create, fetch and cancel RSends payment intents. The amount is denominated in the settlement token; the reference is the on-chain matching key; on mainnet the payer pays exactly the amount — there is no fee in the flow.',
}

export default function PaymentIntentsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Payments"
        title="Payment intents"
        lead={
          <>
            A payment intent is your request for a specific amount, in a specific token, to your
            wallet. RSends turns it into on-chain pay instructions and watches the chain for a
            matching settlement.
          </>
        }
      />

      <H2>Endpoints</H2>
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent" />
      <Endpoint method="GET" path="/api/v1/merchant/payment-intent/{intent_id}" />
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/cancel" />

      <H2>Create an intent</H2>
      <P>
        The amount is <strong>denominated in the settlement token</strong> (e.g. <Code>100</Code>{' '}
        means 100 USDC), not in fiat. Send the token you want to be paid in and, optionally, the
        destination wallet.
      </P>
      <CodeBlock
        label="POST /api/v1/merchant/payment-intent"
        code={`curl https://pay.rsends.io/api/v1/merchant/payment-intent \\
  -H "Authorization: Bearer rk_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": 100,
    "currency": "USDC",
    "chain": "base_sepolia",
    "recipient": "0xYourMerchantWallet...",
    "expires_in_minutes": 30,
    "metadata": { "order_id": "ORD-1024" }
  }'`}
      />
      <Table
        head={['Field', 'Type', 'Notes']}
        rows={[
          [<Code key="a">amount</Code>, 'number', 'In the settlement token, > 0'],
          [<Code key="b">currency</Code>, 'string', 'Settlement token — USDC is the enabled token today'],
          [<Code key="c">chain</Code>, 'string', '"base_sepolia" (test) / "base" (live). Test keys are testnet-only'],
          [<Code key="d">recipient</Code>, 'string?', 'Your destination wallet (0x…). Where the funds settle'],
          [<Code key="e">expected_sender</Code>, 'string?', 'Restrict payment to a known payer address'],
          [<Code key="f">expires_in_minutes</Code>, 'int', '5–1440, default 30'],
          [<Code key="g">metadata</Code>, 'object?', 'Arbitrary merchant data (order_id, customer, …)'],
          [<Code key="h">allow_overpayment / allow_partial</Code>, 'bool', 'Tolerance policy for the matched amount'],
        ]}
      />

      <H2>The response</H2>
      <P>
        The response echoes the intent plus an <Code>onchain</Code> object — the exact, non-custodial
        instructions the payer&apos;s wallet executes. There is no deposit address and no custodial
        key anywhere in it.
      </P>
      <CodeBlock
        label="201 application/json"
        code={`{
  "intent_id": "int_abc123",
  "reference_id": "a1b2c3d4e5f6a7b8",
  "onchain_invoice_id": "0x9f…",          // bytes32, derived from reference_id
  "amount": 100,
  "currency": "USDC",
  "chain": "base_sepolia",
  "status": "pending",
  "expires_at": "2026-06-30T12:30:00+00:00",
  "created_at": "2026-06-30T12:00:00+00:00",
  "onchain": {
    "invoiceId": "0x9f…",
    "merchant":  "0xYourMerchantWallet...",
    "token":     "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "amount":    "100000000",             // base units (USDC has 6 decimals)
    "fee":       "0",                     // routerVersion 2: always "0" — no fee in the flow
    "total":     "100000000",             // == amount: exactly what the payer parts with
    "maxFee":    null,                    // routerVersion 2: no fee ceiling exists
    "chainId":   84532,
    "router":    "0x2Ec353815F2Cd382628d0D399F8d80959C1758CA",
    "routerVersion": 2,                   // 2 = fee-less router; 1 = legacy testnet router
    "function":  "pay",                   // "pay" (ERC-20) | "payNative" (ETH)
    "decimals":  6,
    "isNative":  false
  }
}`}
      />
      <Table
        head={['Field', 'Meaning']}
        rows={[
          [<Code key="r">reference_id</Code>, <>Your <strong>on-chain matching key</strong>. RSends derives the bytes32 <Code>invoiceId</Code> from it and matches the emitted <Code>PaymentMade</Code> event back to this intent.</>],
          [<Code key="i">onchain.invoiceId</Code>, <>The <Code>invoiceId</Code> argument to <Code>pay(...)</Code>.</>],
          [<Code key="ro">onchain.router</Code>, <>The immutable RSends router the payment goes through.</>],
          [<Code key="rv">onchain.routerVersion</Code>, <><Code>2</Code> — the fee-less router (mainnet design): one transfer, payer → you, no fee arguments. <Code>1</Code> — the legacy testnet router, which still quotes an on-chain flat fee.</>],
          [<Code key="f">onchain.fee</Code>, <>Always <Code>&quot;0&quot;</Code> on <Code>routerVersion 2</Code>. On version 1 (testnet) it is the flat fee read live from that router&apos;s <Code>quoteFee</Code>.</>],
          [<Code key="s">status</Code>, <>Lifecycle state — see below.</>],
        ]}
      />

      <H3>Hosting the checkout</H3>
      <P>
        To collect the payment, send the payer to the hosted checkout using the{' '}
        <Code>intent_id</Code>:
      </P>
      <CodeBlock label="checkout URL" code="https://demo.rsends.io/pay/{intent_id}" />
      <P>
        That page re-fetches the intent and its <Code>onchain</Code> instructions, then drives the
        payer&apos;s wallet — see <A href="/docs/hosted-checkout">Hosted checkout</A>.
      </P>

      <H2>No fee in the payment flow</H2>
      <P>
        On the fee-less router (<Code>routerVersion 2</Code>) a payment is{' '}
        <strong>one transfer</strong>: the payer sends exactly <Code>amount</Code>, you receive
        exactly <Code>amount</Code>, and no other party receives anything. The contract has no fee
        configuration, no owner and no pause — nothing on-chain can redirect or withhold a
        payment. RSends pricing is a flat subscription, entirely off-chain.
      </P>
      <Callout variant="info" title="What the payer signs for">
        The payer&apos;s wallet authorizes exactly <Code>amount</Code> (which equals{' '}
        <Code>total</Code>) — an approve or permit for that value, then one router call that moves
        it straight to your wallet. On the legacy testnet router (<Code>routerVersion 1</Code>) the
        old on-chain flat fee still applies: the payer authorizes <Code>amount + fee</Code> and the
        checkout passes <Code>maxFee</Code>; use <Code>routerVersion</Code> to tell the two apart.
      </Callout>

      <H2>Intent lifecycle</H2>
      <Table
        head={['status', 'Meaning']}
        rows={[
          [<Code key="p">pending</Code>, 'Created, awaiting an on-chain payment'],
          [<Code key="c">completed</Code>, 'PaymentMade event matched — funds settled to your wallet'],
          [<Code key="o">overpaid / partial</Code>, 'Matched outside exact amount, accepted per your tolerance policy'],
          [<Code key="e">expired</Code>, 'expires_at passed with no payment'],
          [<Code key="x">cancelled</Code>, 'You cancelled it via the cancel endpoint'],
          [<Code key="rv">review</Code>, 'Ambiguous or late payment held for manual review'],
          [<Code key="rf">refunded</Code>, 'A merchant-sent refund was recorded against it — see Refunds'],
        ]}
      />

      <H3>Cancel an intent</H3>
      <P>
        Cancel a still-<Code>pending</Code> intent to stop accepting payment for it. Cancellation is
        an off-chain state change — there are no funds to return, because none were ever held.
      </P>
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/cancel" />

      <PageNav
        prev={{ href: '/docs/testing', label: 'Testing' }}
        next={{ href: '/docs/hosted-checkout', label: 'Hosted checkout' }}
      />
    </>
  )
}
