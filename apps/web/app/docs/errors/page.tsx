import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Errors',
  description:
    'RSends errors return a JSON envelope with a machine-readable code, status conventions, and idempotent, retry-safe semantics.',
}

export default function ErrorsPage() {
  return (
    <>
      <PageHeader
        eyebrow="After payment"
        title="Errors"
        lead={
          <>
            Errors return a predictable JSON envelope with a machine-readable code. Status codes
            follow HTTP conventions, and write operations are designed to be safe to retry.
          </>
        }
      />

      <H2>The error envelope</H2>
      <P>
        Every error carries a stable <Code>error</Code> code, a human-readable <Code>message</Code>,
        and optional <Code>detail</Code> context. Branch on <Code>error</Code>, show{' '}
        <Code>message</Code>.
      </P>
      <CodeBlock
        label="error envelope"
        code={`{
  "error": "INVALID_SIGNATURE",
  "message": "HMAC signature verification failed",
  "detail": null
}`}
      />

      <H2>Status conventions</H2>
      <P>
        Standard HTTP semantics: <Code>2xx</Code> success, <Code>4xx</Code> a problem with your
        request, <Code>5xx</Code> a problem on our side or upstream (retry those).
      </P>
      <Table
        head={['Code', 'HTTP', 'Meaning']}
        rows={[
          [<Code key="1">INVALID_API_KEY</Code>, '401', 'Missing, malformed, or revoked API key'],
          [<Code key="2">INSUFFICIENT_SCOPE</Code>, '403', 'Key lacks the scope for this operation (e.g. write)'],
          [<Code key="3">INVALID_SIGNATURE</Code>, '401', 'HMAC signature verification failed'],
          [<Code key="4">UNSUPPORTED_TOKEN</Code>, '400', 'Token is not enabled on the requested chain'],
          [<Code key="5">TESTNET_ONLY / MAINNET_ONLY</Code>, '400', 'Key environment does not match the requested chain'],
          [<Code key="6">INVALID_STATUS / INVALID_STATE</Code>, '400', 'Action not allowed from the intent’s current state'],
          [<Code key="7">INTENT_NOT_FOUND</Code>, '404', 'No payment intent with that id for your account'],
          [<Code key="8">WEBHOOK_NOT_FOUND</Code>, '404', 'No webhook with that id'],
          [<Code key="9">DUPLICATE_TX / DUPLICATE_REQUEST_IN_FLIGHT</Code>, '409', 'Already processed or in progress — see idempotency'],
          [<Code key="10">RATE_LIMIT_EXCEEDED</Code>, '429', 'Too many requests — retry after the cooldown'],
          [<Code key="11">MONTHLY_LIMIT_EXCEEDED</Code>, '429', 'Account volume limit reached for the period'],
          [<Code key="12">SERVICE_TEMPORARILY_UNAVAILABLE</Code>, '503', 'Transient upstream/chain issue — retry with backoff'],
          [<Code key="13">INTERNAL_ERROR</Code>, '500', 'Unexpected server error'],
        ]}
      />

      <H2>Idempotency &amp; retry-safety</H2>
      <P>
        Network calls fail mid-flight; you should be able to retry without doubling anything. RSends
        is built so that retries converge on a single result.
      </P>
      <Table
        head={['Surface', 'Guarantee']}
        rows={[
          ['Webhook deliveries', <>Each carries a stable <Code>X-RSend-Delivery-Id</Code>. Dedupe on it — a retried delivery is the same event, not a new one.</>],
          ['Settlement matching', <>A given on-chain payment matches one intent once. A duplicate submission returns <Code>DUPLICATE_TX</Code> rather than recording twice.</>],
          ['Concurrent writes', <>An in-flight duplicate returns <Code>DUPLICATE_REQUEST_IN_FLIGHT</Code> instead of racing.</>],
        ]}
      />
      <Callout variant="info" title="Retry 5xx and 429, not 4xx">
        A <Code>5xx</Code> or <Code>429</Code> is worth retrying with exponential backoff. A{' '}
        <Code>4xx</Code> (other than rate limits) means the request itself needs fixing — retrying it
        unchanged will fail the same way.
      </Callout>

      <H3>The chain is the ultimate backstop</H3>
      <P>
        If a webhook is lost or an API call is ambiguous, you are never stuck guessing: read the{' '}
        <Code>PaymentMade</Code> event for your <Code>reference</Code> on BaseScan and reconcile
        directly. See <A href="/docs/reporting">Reporting</A>.
      </P>

      <PageNav prev={{ href: '/docs/refunds', label: 'Refunds' }} />
    </>
  )
}
