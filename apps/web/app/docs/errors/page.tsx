import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Errors',
  description:
    'RSends error codes, the two envelope shapes to parse, per-endpoint rate limits, and idempotent retry-safe semantics via X-Idempotency-Key.',
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
        Every error carries a stable <Code>error</Code> code and a human-readable{' '}
        <Code>message</Code>. Branch on <Code>error</Code>, show <Code>message</Code>. There are two
        wrappings, depending on whether the error came from a route or from the request pipeline —
        write your parser to accept both.
      </P>
      <CodeBlock
        label="the two shapes"
        code={`// Route errors (validation, not-found, state conflicts) — nested under "detail":
{
  "detail": {
    "error": "INTENT_NOT_FOUND",
    "message": "Payment intent 'pi_…' not found"
  }
}

// Pipeline errors (auth, rate limiting, idempotency) — flat:
{
  "error": "INVALID_API_KEY",
  "message": "Valid API key required"
}

// The approval gate is a special case — a code, no message:
{ "detail": { "code": "approval_pending" } }`}
      />
      <Callout variant="info" title="A parser that handles both">
        <Code>const e = body.detail ?? body</Code>, then read <Code>e.error</Code> (or{' '}
        <Code>e.code</Code> for the approval gate). Aligning these two shapes is a known open item
        on our side; until then, that one line covers every response.
      </Callout>

      <H2>Status conventions</H2>
      <P>
        Standard HTTP semantics: <Code>2xx</Code> success, <Code>4xx</Code> a problem with your
        request, <Code>5xx</Code> a problem on our side or upstream (retry those).
      </P>
      <Table
        head={['Code', 'HTTP', 'Meaning']}
        rows={[
          [<Code key="1">INVALID_API_KEY</Code>, '401', 'Missing, malformed, or revoked API key'],
          [<Code key="2">INSUFFICIENT_SCOPE</Code>, '403', <>A <Code>read</Code> key attempted a non-GET request</>],
          [<Code key="cp">company_profile_required</Code>, '403', <>Submit your company profile in <Code>/app</Code> — the one gate on sandbox access. Shaped <Code>{'{"detail":{"code":…}}'}</Code></>],
          [<Code key="ap">approval_pending</Code>, '403', <>Manual approval outstanding. Applies to <Code>rsend_live_</Code> keys only — the sandbox does not wait on it</>],
          [<Code key="ad">approval_declined</Code>, '403', <>Your organisation was declined; carries a <Code>reason</Code>. Blocks both environments</>],
          [<Code key="4">UNSUPPORTED_TOKEN</Code>, '400', 'Token is not enabled on the requested chain'],
          [<Code key="uc">UNSUPPORTED_CHAIN</Code>, '400', 'Chain has no settlement path at all'],
          [<Code key="5">TESTNET_ONLY / MAINNET_ONLY</Code>, '400', 'Key environment does not match the requested chain'],
          [<Code key="6">INVALID_STATE</Code>, '400', 'Action not allowed from the intent’s current state (cancel, resolve)'],
          [<Code key="is">INVALID_STATUS</Code>, '400', <>Unknown <Code>status</Code> filter on the transactions list</>],
          [<Code key="wi">WEBHOOK_INACTIVE</Code>, '400', 'Cannot test-fire a deactivated webhook'],
          [<Code key="7">INTENT_NOT_FOUND</Code>, '404', 'No payment intent with that id for your account and environment'],
          [<Code key="8">WEBHOOK_NOT_FOUND</Code>, '404', 'No webhook with that id for your account and environment'],
          [<Code key="sf">SETTLEMENT_IN_FLIGHT</Code>, '409', 'Cancel attempted after an on-chain payment was already observed'],
          [<Code key="9">DUPLICATE_REQUEST_IN_FLIGHT</Code>, '409', 'Same idempotency key still being processed — see below'],
          [<Code key="ir">IDEMPOTENCY_KEY_REUSED</Code>, '409', 'Same idempotency key sent with a different request body — see below'],
          [<Code key="sw">SETTLEMENT_WALLET_MISSING</Code>, '422', 'No recipient given and no settlement wallet configured'],
          [<Code key="sa">SETTLEMENT_WALLET_AMBIGUOUS</Code>, '422', 'The owner wallet maps to more than one organisation — pass an explicit recipient'],
          [<Code key="su">SPLIT_UNAVAILABLE</Code>, '422', 'Split payments are not enabled on that chain'],
          [<Code key="wf">WEBHOOK_URL_FORBIDDEN</Code>, '422', 'Webhook URL is not HTTPS, or resolves to a private/reserved address'],
          [<Code key="10">RATE_LIMIT_EXCEEDED</Code>, '429', <>Per-endpoint limit hit. Body is <Code>{'{error, retry_after}'}</Code></>],
          [<Code key="kr">KEY_RATE_LIMIT_EXCEEDED</Code>, '429', 'Your key’s global per-minute limit hit'],
          [<Code key="11">MONTHLY_LIMIT_EXCEEDED</Code>, '429', 'Key’s monthly intent quota reached (unlimited unless one is set)'],
          [<Code key="ru">RATE_LIMIT_UNAVAILABLE</Code>, '503', 'Rate limiting is fail-closed and cannot verify right now — retry'],
          [<Code key="12">SERVICE_TEMPORARILY_UNAVAILABLE</Code>, '503', 'Idempotency cannot be verified right now — retry with backoff'],
          [<Code key="bu">BACKEND_UNREACHABLE</Code>, '502', 'The request exceeded the 25s edge timeout, or the API was unreachable'],
          [<Code key="13">INTERNAL_ERROR</Code>, '500', 'Unexpected server error'],
        ]}
      />
      <P>
        Request-body validation failures (a bad address, an amount ≤ 0, a{' '}
        <Code>split</Code> whose shares don&apos;t sum to 10000) return the standard FastAPI{' '}
        <Code>422</Code> with a <Code>detail</Code> array naming the offending field.
      </P>

      <H2 id="rate-limits">Rate limits</H2>
      <P>
        Limits are per API key on the merchant API, over a sliding window. They are generous enough
        that a normal integration never sees them — you would have to be polling hard or looping.
      </P>
      <Table
        head={['Endpoint', 'Limit']}
        rows={[
          [<><Code>POST</Code> /payment-intent (create)</>, '100 / minute'],
          [<><Code>POST</Code> /payment-intent/{'{id}'}/cancel · /resolve</>, '10 / minute'],
          [<><Code>GET</Code> /payment-intent/{'{id}'}</>, '60 / minute'],
          [<><Code>GET</Code> /transactions</>, '60 / minute'],
          [<><Code>POST</Code> /webhook/register</>, '5 / hour'],
          [<><Code>POST</Code> /webhook/test</>, '10 / minute'],
          [<>Public checkout status (<Code>/api/v1/public/payment-intent/{'{id}'}</Code>)</>, '20 / minute per IP'],
          [<em key="g">Global, across all endpoints</em>, '100 / minute per key'],
        ]}
      />
      <P>
        Exceeding a limit returns <Code>429</Code> with a <Code>retry_after</Code> value in seconds.
        The API also emits <Code>X-RateLimit-Limit</Code>, <Code>X-RateLimit-Remaining</Code>,{' '}
        <Code>X-RateLimit-Reset</Code> and <Code>Retry-After</Code> headers.
      </P>
      <Callout variant="warn" title="Those headers aren’t visible on the sandbox base URL">
        The sandbox base URL routes through the RSends edge, which returns the status and body
        verbatim but does not forward response headers other than <Code>Content-Type</Code>. The
        limits and the <Code>429</Code> bodies are real; only the header hints are missing. Read{' '}
        <Code>retry_after</Code> from the body and back off on it.
      </Callout>
      <Callout variant="info" title="Rate limiting fails closed">
        If the limiter cannot verify a request, the API answers <Code>503</Code>{' '}
        <Code>RATE_LIMIT_UNAVAILABLE</Code> rather than letting it through unchecked. It is
        transient — retry with backoff.
      </Callout>

      <H2>Idempotency &amp; retry-safety</H2>
      <P>
        Network calls fail mid-flight; you should be able to retry without doubling anything. Send
        an <Code>X-Idempotency-Key</Code> header (any opaque string you generate — an order id plus
        an attempt counter works well) on any <Code>POST</Code>:
      </P>
      <CodeBlock
        label="idempotent create"
        code={`curl -X POST https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -H "X-Idempotency-Key: ORD-1024" \\
  -d '{ "amount": 100, "currency": "USDC", "chain": "base_sepolia" }'`}
      />
      <Table
        head={['Surface', 'Guarantee']}
        rows={[
          ['Repeated request', <>A retry with the same key replays the original response instead of re-running the call. The record is kept <strong>24 hours</strong>; successful responses are what get replayed.</>],
          ['Concurrent duplicate', <>A retry arriving while the first is still in flight waits briefly, then returns <Code>409 DUPLICATE_REQUEST_IN_FLIGHT</Code> rather than racing.</>],
          ['Other merchants', <>Keys are scoped to your account and environment. Another merchant sending the same key string cannot reach your record, and you cannot reach theirs.</>],
          ['Key reused for a different call', <>The same key with a <strong>different request body</strong> is <Code>409 IDEMPOTENCY_KEY_REUSED</Code> — never the first call’s response, and never a second intent. Retries must resend the original body unchanged; a genuinely new request needs a new key.</>],
          ['Webhook deliveries', <>Each carries a stable <Code>X-RSend-Delivery-Id</Code>. Dedupe on it — a retried delivery is the same event, not a new one.</>],
          ['Settlement matching', <>A given on-chain payment matches one intent once. The indexer will not record it twice, and a reversed payment is signalled with <Code>payment.reversed</Code>.</>],
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
