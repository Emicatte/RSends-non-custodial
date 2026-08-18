import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Webhooks',
  description:
    'Receive signed RSends webhooks. The settlement event is payment.completed. Verify every delivery with X-RSend-Signature over "{timestamp}.{body}" within a 5-minute window.',
}

export default function WebhooksPage() {
  return (
    <>
      <PageHeader
        eyebrow="Payments"
        title="Webhooks"
        lead={
          <>
            Register an HTTPS endpoint to be told when a payment settles on-chain. Every delivery is
            signed, so you can prove it came from RSends before you act on it.
          </>
        }
      />

      <H2>Register a webhook</H2>
      <Endpoint method="POST" path="/api/v1/merchant/webhook/register" />
      <P>
        The URL must be <strong>HTTPS</strong> and must resolve to a publicly routable address.
        Loopback, private, link-local and otherwise reserved addresses are rejected at registration
        with <Code>422 WEBHOOK_URL_FORBIDDEN</Code>, and re-checked immediately before every
        delivery — so a hostname that later starts resolving to an internal address stops being
        delivered to. Webhooks are environment-scoped: one registered with a test key never
        receives live events, and vice versa. Registration is limited to 5 per hour.
      </P>
      <CodeBlock
        label="request"
        code={`{
  "url": "https://your-app.example.com/rsends/webhook",
  "events": ["payment.completed", "payment.expired"]
}`}
      />
      <CodeBlock
        label="response"
        code={`{
  "webhook_id": 42,
  "url": "https://your-app.example.com/rsends/webhook",
  "secret": "a1b2c3…   (64 hex chars)",
  "events": ["payment.completed", "payment.expired"],
  "is_active": true
}`}
      />
      <Callout variant="warn" title="Secret shown once">
        The <Code>secret</Code> is returned only in this registration response. Store it — it is the
        key used to verify the signature on every delivery and cannot be retrieved again. When you go
        live, you swap this secret along with your API key.
      </Callout>

      <H3>Send a test delivery</H3>
      <Endpoint method="POST" path="/api/v1/merchant/webhook/test" />
      <P>
        Posts a sample event to your URL so you can confirm your endpoint and signature check work
        before a real payment.
      </P>

      <H2>The settlement event</H2>
      <P>
        When a payment settles on-chain and RSends matches it to your intent, you receive{' '}
        <Code>payment.completed</Code>. This is the one event you should treat as “money received.”{' '}
        <Code>payment.expired</Code> fires when an intent lapses unpaid. In the rare case of a deep
        chain reorganization shortly after completion, <Code>payment.reversed</Code> can follow a{' '}
        <Code>payment.completed</Code> within roughly the chain’s finality window (~15 minutes on
        Base) — treat it as “stop fulfilment.” After a <Code>payment.reversed</Code>, poll the
        intent before writing the order off: if the network re-includes the transaction, the intent
        returns to <Code>paid</Code> without a second <Code>payment.completed</Code>.
      </P>
      <Table
        head={['Event', 'Meaning']}
        rows={[
          [<Code key="1">payment.completed</Code>, 'Payment settled on-chain and matched — fulfil the order'],
          [<Code key="2">payment.expired</Code>, 'Intent reached expires_at with no payment'],
          [<Code key="3">payment.completed_late</Code>, 'Settled after expiry, accepted per your policy'],
          [<Code key="4">payment.overpaid / payment.partial</Code>, 'Matched outside the exact amount, within tolerance'],
          [<Code key="5">payment.needs_review</Code>, 'Held — could not be matched cleanly, awaiting manual resolution'],
          [<Code key="6">payment.expired_rejected</Code>, 'Late payment rejected per your policy — no settlement will occur'],
          [<Code key="7">payment.reversed</Code>, 'A delivered payment.completed was rolled back by a chain reorg — un-fulfil'],
          [<Code key="8">payment.cancelled / payment.ambiguous</Code>, 'Reserved — subscribable today, not yet emitted'],
        ]}
      />

      <H2>Event payload</H2>
      <P>
        Deliveries POST a JSON body. <strong>Every event carries the same field set</strong> — the
        example below is the full shape, and the test delivery posts exactly it. Alongside the
        intent fields, it carries the <strong>on-chain proof</strong> of settlement — the transaction
        hash, the chain (canonical lowercase name plus numeric <Code>chain_id</Code>), and the{' '}
        <Code>onchain_invoice_id</Code> you can look up directly. Amount fields are{' '}
        <strong>strings</strong>, and <Code>amount</Code> is what settled to you — whole, never
        net of anything. There is deliberately no <Code>fee</Code> field: RSends is paid by
        off-chain subscription, and where the deployed router charges the <em>payer</em> an
        on-chain fee it is readable from the transaction itself via <Code>tx_hash</Code>.
      </P>
      <CodeBlock
        label="payment.completed — body"
        code={`{
  "event_id": "evt_3f9a…",
  "event": "payment.completed",
  "intent_id": "pi_abc123…",
  "reference_id": "a1b2c3d4e5f6a7b8",
  "onchain_invoice_id": "0x9f…",        // on-chain key for the PaymentMade event
  "amount": "100",
  "amount_received": "100",
  "overpaid_amount": null,
  "underpaid_amount": null,
  "currency": "USDC",
  "chain": "base_sepolia",
  "chain_id": 84532,
  "recipient": "0x…",                    // where the funds settled
  "tx_hash": "0x…",                      // the settlement transaction
  "status": "completed",
  "completed_late": false,
  "late_minutes": null,
  "metadata": { "order_id": "ORD-1024" },
  "timestamp": "2026-06-30T12:00:05+00:00",
  "created_at": "2026-06-30T12:00:00+00:00",
  "completed_at": "2026-06-30T12:00:05+00:00",
  "settlement": "onchain"                // extra on settlement events only
}`}
      />
      <Callout variant="info" title="Deriving full on-chain proof">
        From <Code>tx_hash</Code> on{' '}
        <A href="https://sepolia.basescan.org">sepolia.basescan.org</A> you can read the rest of the
        proof — the <strong>block number</strong>, the <strong>payer address</strong> and the exact{' '}
        <Code>amount</Code> — straight from the <Code>PaymentMade</Code> event. Two event shapes
        exist, keyed by <Code>topics[0]</Code>: the router deployed today (
        <Code>routerVersion 1</Code>) emits the 7-argument shape with a trailing <Code>fee</Code>{' '}
        word (topic <Code>0xab7ccb7f…deb04947</Code>), while the fee-less router arriving at the
        mainnet cutover emits{' '}
        <Code>PaymentMade(bytes32,address,address,address,uint256,uint256)</Code> — token, amount,
        blockTimestamp (topic <Code>0xc3e210e1…cc843241</Code>). Richer proof fields embedded
        directly in the payload are on the roadmap; today the load-bearing handle is{' '}
        <Code>tx_hash</Code> + <Code>onchain_invoice_id</Code>.
      </Callout>

      <H2>Delivery headers &amp; signature</H2>
      <Table
        head={['Header', 'Value']}
        rows={[
          [<Code key="1">X-RSend-Signature</Code>, <span key="v">HMAC-SHA256 of <Code>{'"{timestamp}.{body}"'}</Code>, hex</span>],
          [<Code key="2">X-RSend-Timestamp</Code>, 'Unix seconds for this attempt — part of the signed string'],
          [<Code key="3">X-RSend-Event</Code>, 'The event type'],
          [<Code key="4">X-RSend-Delivery</Code>, 'Per-delivery UUID'],
          [<Code key="5">X-RSend-Delivery-Id</Code>, 'Idempotency key — dedupe retries on this'],
        ]}
      />
      <P>
        The signature covers <strong>both the timestamp and the exact raw body</strong>, so tampering
        with either invalidates it. This is the only signing scheme RSends uses — there is no other
        variant to support.
      </P>
      <CodeBlock
        label="verify a delivery — Node.js"
        code={`import crypto from 'node:crypto'

function verifyRSendsWebhook(secret, headers, rawBody) {
  const ts  = headers['x-rsend-timestamp']
  const sig = headers['x-rsend-signature']

  // 1) Freshness: reject anything outside a 5-minute window (anti-replay).
  const now = Math.floor(Date.now() / 1000)
  if (!ts || Math.abs(now - Number(ts)) > 300) return false

  // 2) Recompute HMAC-SHA256 over "{timestamp}.{rawBody}" and compare in
  //    constant time. rawBody MUST be the exact bytes received (do not re-serialize).
  const expected = crypto
    .createHmac('sha256', secret)
    .update(\`\${ts}.\${rawBody}\`)
    .digest('hex')

  return sig.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
}`}
      />
      <Callout variant="warn" title="Always verify the signature">
        Treat an unverified body as untrusted input. Recompute the HMAC over{' '}
        <Code>{'"{timestamp}.{raw_body}"'}</Code>, confirm the timestamp is within 5 minutes, and
        compare in constant time <strong>before</strong> reading any field. This is the load-bearing
        rule of the integration. Use <Code>X-RSend-Delivery-Id</Code> to dedupe retries.
      </Callout>

      <H2>Retries</H2>
      <P>
        A delivery counts as accepted when your endpoint answers <strong>2xx</strong>. Anything
        else — a non-2xx status, a timeout, a connection error — is retried. Each attempt has a{' '}
        <strong>10-second</strong> timeout, and there are up to <strong>5 retries</strong> with
        exponential backoff:
      </P>
      <Table
        head={['Attempt', 'Sent after the previous failure']}
        rows={[
          ['1st retry', '30 seconds'],
          ['2nd retry', '2 minutes'],
          ['3rd retry', '8 minutes'],
          ['4th retry', '32 minutes'],
          ['5th retry', '2 hours'],
        ]}
      />
      <P>
        After the 5th retry the delivery is marked failed and is not attempted again — reconcile
        from <A href="/docs/reporting">Reporting</A> or the chain. Answer quickly and do the work
        asynchronously: a slow handler that exceeds 10 seconds is treated as a failure even if it
        eventually succeeds, which turns into duplicate deliveries.
      </P>
      <Callout variant="warn" title="Dedupe on the delivery id, not the event">
        Every retry of the same event carries the same <Code>X-RSend-Delivery-Id</Code>. Key your
        handler on it and make it idempotent — that is the whole retry contract.
      </Callout>

      <H3>Refund events are merchant-recorded</H3>
      <P>
        RSends never moves money, so there is no processor-driven refund event. A refund is a
        transfer <strong>you</strong> send from your own wallet and then record against the original
        payment for reporting — see <A href="/docs/refunds">Refunds</A>.
      </P>

      <H2>Verify on-chain yourself</H2>
      <Callout variant="chain" title="The webhook is a convenience, the chain is the record">
        You never have to trust the webhook alone. The <Code>PaymentMade</Code> event for your{' '}
        <Code>reference</Code> is public on BaseScan; anyone can confirm the amount, the recipient,
        and the payer independently of RSends. If the webhook and the chain ever disagree, the chain
        wins.
      </Callout>

      <PageNav
        prev={{ href: '/docs/hosted-checkout', label: 'Hosted checkout' }}
        next={{ href: '/docs/reporting', label: 'Reporting' }}
      />
    </>
  )
}
