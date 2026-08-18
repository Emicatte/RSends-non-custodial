import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, UL, LI, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Refunds',
  description:
    'RSends is non-custodial and cannot issue refunds — it never held the funds. A refund is a transfer you send from your own wallet. RSends can record it for reporting but never moves money.',
}

export default function RefundsPage() {
  return (
    <>
      <PageHeader
        eyebrow="After payment"
        title="Refunds"
        lead={
          <>
            Refunds work differently when no one holds your money. RSends never took custody of the
            payment, so <strong>RSends cannot send a refund</strong> — only you can, from the wallet
            the funds settled into.
          </>
        }
      />

      <H2>Why RSends can&apos;t refund for you</H2>
      <P>
        When a customer paid, the stablecoin moved directly from their wallet to{' '}
        <strong>your</strong> wallet on-chain. RSends was never in that path — it only observed the
        event. It has no balance of yours to draw from and no key that can move your funds. There is
        nothing for it to send back.
      </P>
      <Callout variant="info" title="A refund is a payment in reverse">
        To refund a customer, <strong>you</strong> send a transfer from your own wallet back to their
        address — the same way you&apos;d send any on-chain payment. You choose the amount, the token,
        and when. RSends is not a party to it.
      </Callout>

      <H2>How to refund</H2>
      <Table
        head={['Step', 'Action']}
        rows={[
          ['1', <>Look up the original payment (its <Code>tx_hash</Code> and the payer address) in <A href="/docs/reporting">Reporting</A> or on BaseScan.</>],
          ['2', <>From your merchant wallet, send the refund amount in the same token back to the payer address.</>],
          ['3', <>Record the refund against the original payment in RSends, for your reporting (below).</>],
        ]}
      />

      <H2>Recording a refund</H2>
      <P>
        RSends can <strong>record</strong> that a payment was refunded so your reporting reflects it —
        it sets the intent&apos;s status to <Code>refunded</Code>. This is bookkeeping only:{' '}
        <strong>recording a refund never moves money.</strong> The actual transfer is the one you sent
        from your own wallet.
      </P>
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/resolve" />
      <CodeBlock
        label="record a refund (resolve action)"
        code={`curl -X POST https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent/\\
pi_9f1c4a7e2b5d8036c1e94ab7d2508f63/resolve \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{ "action": "refund" }'

// → intent.status becomes "refunded" (a record). No funds move.`}
      />
      <Callout variant="warn" title="This endpoint only accepts intents in review">
        <Code>resolve</Code> is the decision point for a payment held in <Code>review</Code> — the
        state a late payment lands in under <Code>late_payment_policy: &quot;review&quot;</Code>.
        Calling it on a normally-completed payment returns <Code>400 INVALID_STATE</Code>. There is
        currently <strong>no endpoint that records a refund against a completed intent</strong>: for
        those, keep the refund in your own books and reconcile against the on-chain transfer you
        sent. The other action here is <Code>{'{"action": "complete"}'}</Code>, which accepts the
        held payment and fires <Code>payment.completed_late</Code>.
      </Callout>
      <Callout variant="warn" title="The record is not the refund">
        Marking an intent <Code>refunded</Code> does not pay anyone. Always send the on-chain transfer
        first, then record it. If you record without sending, your customer is still out of pocket.
      </Callout>

      <H3>What this means in practice</H3>
      <UL>
        <LI>You control refund policy and timing entirely — there is no processor window or reserve.</LI>
        <LI>Refunds are <strong>merchant-recorded</strong>, not processor-driven; there is no inbound “refund” webhook from RSends, and no <Code>payment.refunded</Code> event exists.</LI>
        <LI>The refund transfer is itself a public on-chain transaction your customer can verify.</LI>
      </UL>

      <PageNav
        prev={{ href: '/docs/reporting', label: 'Reporting' }}
        next={{ href: '/docs/errors', label: 'Errors' }}
      />
    </>
  )
}
