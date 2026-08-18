import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Table, UL, LI, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Quickstart',
  description:
    'From zero to a settled test payment on Base Sepolia: mint a sandbox key, create a payment intent, send the payer to the hosted checkout, and receive the signed payment.completed webhook.',
}

export default function QuickstartPage() {
  return (
    <>
      <PageHeader
        eyebrow="Get started"
        title="Quickstart"
        lead={
          <>
            Six steps from nothing to a payment that has actually settled on-chain, in the{' '}
            <strong>sandbox</strong> (Base Sepolia). Everything here is real and copyable — the only
            thing you must replace is your own key.
          </>
        }
      />

      <H2>What you need first</H2>
      <UL>
        <LI>
          An RSends account with its <strong>company profile submitted</strong> — one self-serve
          form, no waiting on anyone (see step 1).
        </LI>
        <LI>
          A wallet you control, funded with Base Sepolia test USDC and a little test ETH for gas.
          This is the <em>payer</em> wallet — see <A href="/docs/testing">Testing</A>.
        </LI>
        <LI>A destination wallet address for the funds to land in.</LI>
        <LI>A server that can receive an HTTPS webhook (or a tunnel to your laptop).</LI>
      </UL>
      <Callout variant="info" title="Sandbox base URL">
        Every call below goes to <Code>https://pay.rsends.io/api/backend</Code>, followed by the
        endpoint path. So <Code>/api/v1/merchant/payment-intent</Code> is reached at{' '}
        <Code>https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent</Code>. See{' '}
        <A href="/docs">Environments</A> for why the base URL carries that prefix today.
      </Callout>

      <H2>1. Get a sandbox API key</H2>
      <P>
        Keys are self-serve, and so is everything before them. Sign up, submit your company profile
        when <Code>/app</Code> asks for it, then open <strong>API keys</strong> →{' '}
        <strong>Merchant keys</strong> and create one. You need the <Code>admin</Code> role in your
        organisation. The key is <Code>rsend_test_…</Code>, scoped <Code>write</Code>, bound to the
        test environment, and shown <strong>once</strong>.
      </P>
      <Callout variant="info" title="No approval queue for the sandbox">
        Submitting the company profile is the only gate — you are not waiting on anyone to let you
        in. If every call returns <Code>403</Code> with{' '}
        <Code>{'{"detail":{"code":"company_profile_required"}}'}</Code>, the profile is still
        incomplete; finish it in <Code>/app</Code> and the same call works immediately. (Mainnet is
        different: a <Code>rsend_live_</Code> key does require manual approval.)
      </Callout>

      <H2>2. Create a payment intent</H2>
      <P>
        Ask for an amount, in a token, on a chain. The amount is denominated in the settlement
        token — <Code>100</Code> means 100 USDC.
      </P>
      <CodeBlock
        label="POST /api/v1/merchant/payment-intent"
        code={`curl -X POST https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -H "X-Idempotency-Key: order-1024-attempt-1" \\
  -d '{
    "amount": 100,
    "currency": "USDC",
    "chain": "base_sepolia",
    "recipient": "0xYourDestinationWallet00000000000000000000",
    "expires_in_minutes": 30,
    "metadata": { "order_id": "ORD-1024" }
  }'`}
      />
      <P>
        <Code>200 OK</Code>. The response echoes the intent and adds an <Code>onchain</Code> object —
        the exact instructions the payer&apos;s wallet will execute. Two fields matter immediately:{' '}
        <Code>intent_id</Code> (step 3) and <Code>onchain.total</Code> (what the payer actually
        authorises).
      </P>
      <CodeBlock
        label="200 application/json (abridged)"
        code={`{
  "intent_id": "pi_9f1c4a7e2b5d8036c1e94ab7d2508f63",
  "reference_id": "a1b2c3d4e5f6a7b8",
  "onchain_invoice_id": "0x9f…",
  "amount": 100.0,
  "currency": "USDC",
  "chain": "base_sepolia",
  "recipient": "0xyourdestinationwallet00000000000000000000",
  "status": "pending",
  "expires_at": "2026-08-06T12:30:00+00:00",
  "created_at": "2026-08-06T12:00:00+00:00",
  "onchain": {
    "invoiceId": "0x9f…",
    "merchant":  "0xyourdestinationwallet00000000000000000000",
    "token":     "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    "amount":    "100000000",      // 100 USDC — what YOU receive
    "fee":       "600000",         // 0.60 USDC — live from the router
    "total":     "100600000",      // what the PAYER parts with
    "maxFee":    "600000",
    "chainId":   84532,
    "router":    "0x2Ec353815F2Cd382628d0D399F8d80959C1758CA",
    "routerVersion": 1,
    "function":  "pay",
    "decimals":  6,
    "isNative":  false
  }
}`}
      />
      <Callout variant="warn" title="On the sandbox the payer pays amount + fee">
        The deployed Base Sepolia router is <Code>routerVersion 1</Code>, which charges an on-chain
        flat fee on top of your amount: the payer authorises <Code>total</Code>, you receive{' '}
        <Code>amount</Code> whole. At the mainnet cutover this becomes the fee-less{' '}
        <Code>routerVersion 2</Code> — <Code>fee</Code> is <Code>&quot;0&quot;</Code> and{' '}
        <Code>total == amount</Code>. Branch on <Code>routerVersion</Code>, never on a hardcoded
        assumption. See <A href="/docs/payment-intents">Payment intents</A>.
      </Callout>

      <H2>3. Send the payer to the hosted checkout</H2>
      <P>
        There is no <Code>checkout_url</Code> field — you compose the URL from the{' '}
        <Code>intent_id</Code>:
      </P>
      <CodeBlock
        label="checkout URL"
        code="https://demo.rsends.io/pay/pi_9f1c4a7e2b5d8036c1e94ab7d2508f63"
      />
      <P>
        Open it, connect the funded wallet, approve, and pay. The stablecoin moves from the
        payer&apos;s wallet to your destination wallet in one transaction. Nothing passes through
        RSends. If you&apos;d rather build your own checkout, everything you need is in the{' '}
        <Code>onchain</Code> object — see <A href="/docs/hosted-checkout">Hosted checkout</A>.
      </P>

      <H2>4. Register a webhook</H2>
      <P>
        Do this before the payment if you want to watch it land live. The URL must be HTTPS and
        publicly resolvable — private, loopback and link-local addresses are rejected with{' '}
        <Code>422 WEBHOOK_URL_FORBIDDEN</Code>.
      </P>
      <CodeBlock
        label="POST /api/v1/merchant/webhook/register"
        code={`curl -X POST https://pay.rsends.io/api/backend/api/v1/merchant/webhook/register \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://your-app.example.com/rsends/webhook",
    "events": ["payment.completed", "payment.expired"]
  }'`}
      />
      <CodeBlock
        label="200 application/json"
        code={`{
  "webhook_id": 42,
  "url": "https://your-app.example.com/rsends/webhook",
  "secret": "…64 hex chars…",
  "events": ["payment.completed", "payment.expired"],
  "is_active": true
}`}
      />
      <Callout variant="warn" title="Store the secret now">
        <Code>secret</Code> is returned in this response and never again. It is the HMAC key for
        every delivery&apos;s signature. Fire a test delivery with{' '}
        <Code>POST /api/v1/merchant/webhook/test</Code> (<Code>{'{"webhook_id": 42}'}</Code>) to
        confirm your endpoint and verification work before a real payment arrives.
      </Callout>

      <H2>5. Verify the webhook, then fulfil</H2>
      <P>
        When the payment settles you receive <Code>payment.completed</Code>. Verify the signature
        over the <strong>raw body</strong> before reading a single field.
      </P>
      <CodeBlock
        label="verify a delivery — Node.js"
        code={`import crypto from 'node:crypto'

function verifyRSendsWebhook(secret, headers, rawBody) {
  const ts  = headers['x-rsend-timestamp']
  const sig = headers['x-rsend-signature']

  // Freshness: reject anything outside a 5-minute window (anti-replay).
  const now = Math.floor(Date.now() / 1000)
  if (!ts || Math.abs(now - Number(ts)) > 300) return false

  // HMAC-SHA256 over "{timestamp}.{rawBody}", constant-time compare.
  const expected = crypto
    .createHmac('sha256', secret)
    .update(\`\${ts}.\${rawBody}\`)
    .digest('hex')

  return sig.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))
}`}
      />
      <P>
        Dedupe on <Code>X-RSend-Delivery-Id</Code> — a retry carries the same id, and RSends retries
        up to 5 times on any non-2xx. Full payload shape, event list and retry schedule:{' '}
        <A href="/docs/webhooks">Webhooks</A>.
      </P>
      <P>
        Prefer polling? <Code>GET /api/v1/merchant/payment-intent/{'{intent_id}'}</Code> returns the
        same state (60/min per key).
      </P>

      <H2>6. Confirm it on-chain</H2>
      <P>
        Take <Code>tx_hash</Code> from the webhook to{' '}
        <A href="https://sepolia.basescan.org">sepolia.basescan.org</A> and read the{' '}
        <Code>PaymentMade</Code> event: the amount, your wallet, the payer. You have now verified
        the payment without trusting RSends at all.
      </P>
      <Callout variant="chain" title="That’s the whole integration">
        One POST to create, one redirect, one signed webhook to verify. No balance to reconcile, no
        payout to wait for, no funds held anywhere. Going to production means swapping the key and
        the chain — see <A href="/docs/testing">Testing</A>.
      </Callout>

      <H3>Where to go next</H3>
      <Table
        head={['If you need', 'Read']}
        rows={[
          [
            'Every request field, the recipient rules, the fee model',
            <A key="pi" href="/docs/payment-intents">Payment intents</A>,
          ],
          [
            'Keys, scopes, the approval gate, idempotency',
            <A key="au" href="/docs/authentication">Authentication</A>,
          ],
          [
            'Every event, the payload contract, retries',
            <A key="wh" href="/docs/webhooks">Webhooks</A>,
          ],
          [
            'Error codes and rate limits',
            <A key="er" href="/docs/errors">Errors</A>,
          ],
        ]}
      />

      <PageNav
        prev={{ href: '/docs', label: 'Overview' }}
        next={{ href: '/docs/authentication', label: 'Authentication' }}
      />
    </>
  )
}
