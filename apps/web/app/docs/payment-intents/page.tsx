import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Payment intents',
  description:
    'Create, fetch, cancel and resolve RSends payment intents. The amount is denominated in the settlement token, the reference is the on-chain matching key, and your principal always settles whole — branch on routerVersion for what the payer authorises.',
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
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/resolve" />
      <P>
        Paths are relative to the environment base URL — on the sandbox,{' '}
        <Code>https://pay.rsends.io/api/backend</Code>. See <A href="/docs">Environments</A>.
      </P>

      <H2>Create an intent</H2>
      <P>
        The amount is <strong>denominated in the settlement token</strong> (e.g. <Code>100</Code>{' '}
        means 100 USDC), not in fiat. Send the token you want to be paid in and, optionally, the
        destination wallet.
      </P>
      <CodeBlock
        label="POST /api/v1/merchant/payment-intent"
        code={`curl -X POST https://pay.rsends.io/api/backend/api/v1/merchant/payment-intent \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount": 100,
    "currency": "USDC",
    "chain": "base_sepolia",
    "recipient": "0xYourDestinationWallet00000000000000000000",
    "expires_in_minutes": 30,
    "metadata": { "order_id": "ORD-1024" }
  }'`}
      />
      <Table
        head={['Field', 'Type', 'Notes']}
        rows={[
          [<Code key="a">amount</Code>, 'number · required', 'In the settlement token, > 0'],
          [<Code key="b">currency</Code>, 'string · required', <>Settlement token. On Base Sepolia: <Code>USDC</Code> or <Code>ETH</Code>. Anything not enabled on the chain → <Code>400 UNSUPPORTED_TOKEN</Code></>],
          [<Code key="c">chain</Code>, 'string · default "BASE"', <><Code>&quot;base_sepolia&quot;</Code> (test) / <Code>&quot;base&quot;</Code> (live). A test key on a mainnet chain → <Code>400 TESTNET_ONLY</Code></>],
          [<Code key="d">recipient</Code>, 'string?', <>Destination wallet (<Code>0x…</Code>, 40 hex). Omit it and your organisation&apos;s settlement wallet is used — see below</>],
          [<Code key="e">expected_sender</Code>, 'string?', 'Restrict the payment to a known payer address'],
          [<Code key="f">expires_in_minutes</Code>, 'int · default 30', '5–1440 (max 24h)'],
          [<Code key="g">metadata</Code>, 'object?', <>Arbitrary merchant data. <Code>merchant_name</Code> (or <Code>store_name</Code>) is the one key the payer sees on the checkout — everything else stays private</>],
          [<Code key="h">allow_overpayment</Code>, 'bool · default true', 'Accept a payment larger than the amount'],
          [<Code key="i">allow_partial</Code>, 'bool · default false', 'Accept a payment of ≥ 50% of the amount'],
          [<Code key="j">amount_tolerance_percent</Code>, 'number · default 1.0', 'Matching tolerance on the amount, 0–10'],
          [<Code key="k">late_payment_policy</Code>, 'string · default "auto"', <><Code>auto</Code> (complete with a late flag) · <Code>review</Code> (hold for manual resolution) · <Code>reject</Code> (don&apos;t match)</>],
          [<Code key="l">split</Code>, 'array?', <>2–20 recipients with <Code>share_bps</Code> summing to <strong>exactly</strong> 10000. Mutually exclusive with <Code>recipient</Code>. Not enabled on every chain → <Code>422 SPLIT_UNAVAILABLE</Code></>],
          [<Code key="m">network</Code>, 'string?', <><strong>Accepted but ignored</strong> — the network is derived from <Code>chain</Code> so it can never contradict it</>],
        ]}
      />

      <H3>Where the money goes</H3>
      <P>
        An intent cannot exist without a resolvable on-chain recipient — that is the non-custodial
        invariant, enforced at creation. The <Code>recipient</Code> you pass wins; if you omit it,
        RSends falls back to your organisation&apos;s settlement wallet (set in Settings). If
        neither resolves, creation fails with <Code>422 SETTLEMENT_WALLET_MISSING</Code> rather than
        defaulting to some address. A wallet claimed by more than one organisation fails with{' '}
        <Code>422 SETTLEMENT_WALLET_AMBIGUOUS</Code>.
      </P>

      <H2>The response</H2>
      <P>
        The response echoes the intent plus an <Code>onchain</Code> object — the exact, non-custodial
        instructions the payer&apos;s wallet executes. There is no deposit address and no custodial
        key anywhere in it.
      </P>
      <CodeBlock
        label="200 application/json — sandbox (Base Sepolia)"
        code={`{
  "intent_id": "pi_9f1c4a7e2b5d8036c1e94ab7d2508f63",
  "reference_id": "a1b2c3d4e5f6a7b8",
  "onchain_invoice_id": "0x9f…",          // bytes32, derived from reference_id + chain id
  "amount": 100.0,
  "currency": "USDC",
  "chain": "base_sepolia",
  "recipient": "0xyourdestinationwallet00000000000000000000",
  "status": "pending",
  "expires_at": "2026-08-06T12:30:00+00:00",
  "created_at": "2026-08-06T12:00:00+00:00",
  "completed_at": null,
  "tx_hash": null,
  "metadata": { "order_id": "ORD-1024" },
  "onchain": {
    "invoiceId": "0x9f…",
    "merchant":  "0xyourdestinationwallet00000000000000000000",
    "token":     "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    "amount":    "100000000",             // base units (USDC has 6 decimals) — what YOU receive
    "fee":       "600000",                // 0.60 USDC — read live from the router's quoteFee
    "total":     "100600000",             // amount + fee — what the PAYER parts with
    "maxFee":    "600000",                // payer's ceiling; pay() reverts above it
    "chainId":   84532,
    "router":    "0x2Ec353815F2Cd382628d0D399F8d80959C1758CA",
    "routerVersion": 1,                   // 1 = deployed sandbox router (fee); 2 = fee-less
    "function":  "pay",                   // "pay" (ERC-20) | "payNative" (ETH)
    "decimals":  6,
    "isNative":  false,
    "permitType": "eip2612",              // "eip2612" → permit flow; "none" → approve + pay
    "feeUnavailable": false
  }
}`}
      />
      <Table
        head={['Field', 'Meaning']}
        rows={[
          [<Code key="id">intent_id</Code>, <><Code>pi_</Code> + 32 hex. Unguessable by design — it is also the checkout link&apos;s only credential.</>],
          [<Code key="r">reference_id</Code>, <>Your <strong>on-chain matching key</strong>. RSends derives the bytes32 <Code>invoiceId</Code> from it and matches the emitted <Code>PaymentMade</Code> event back to this intent.</>],
          [<Code key="i">onchain.invoiceId</Code>, <>The <Code>invoiceId</Code> argument to <Code>pay(...)</Code>.</>],
          [<Code key="ro">onchain.router</Code>, <>The immutable RSends router the payment goes through.</>],
          [<Code key="rv">onchain.routerVersion</Code>, <><Code>1</Code> — the router deployed today: quotes an on-chain flat fee and takes a <Code>maxFee</Code> argument. <Code>2</Code> — the fee-less, ownerless router arriving at the mainnet cutover: no fee, no fee arguments. <strong>Branch on this field</strong>, never on a hardcoded assumption.</>],
          [<Code key="f">onchain.fee</Code>, <>On <Code>routerVersion 1</Code>, the flat fee read live from the router&apos;s <Code>quoteFee</Code>. On version 2 it is always <Code>&quot;0&quot;</Code>.</>],
          [<Code key="t">onchain.total</Code>, <><Code>amount + fee</Code> — the number the payer&apos;s wallet actually authorises. Show <em>this</em> in your UI, not <Code>amount</Code>.</>],
          [<Code key="fu">onchain.feeUnavailable</Code>, <><Code>true</Code> when the live fee quote failed (RPC down): <Code>fee</Code>/<Code>total</Code>/<Code>calldata</Code> come back <Code>null</Code> and the client is expected to read <Code>quoteFee</Code> on-chain itself.</>],
          [<Code key="s">status</Code>, <>Lifecycle state — see below.</>],
        ]}
      />

      <H3>Hosting the checkout</H3>
      <P>
        There is no <Code>checkout_url</Code> field in the response — you compose the URL from the{' '}
        <Code>intent_id</Code>:
      </P>
      <CodeBlock
        label="checkout URL"
        code="https://demo.rsends.io/pay/pi_9f1c4a7e2b5d8036c1e94ab7d2508f63"
      />
      <P>
        That page re-fetches the intent and its <Code>onchain</Code> instructions, then drives the
        payer&apos;s wallet — see <A href="/docs/hosted-checkout">Hosted checkout</A>.
      </P>

      <H2>Fees: what the sandbox does today</H2>
      <P>
        <strong>Your principal always arrives whole.</strong> Nothing is ever deducted from what
        settles into your wallet — RSends never touches the transfer. What differs between the two
        routers is whether the <em>payer</em> is charged something on top.
      </P>
      <Table
        head={['', 'routerVersion 1 — deployed today', 'routerVersion 2 — at mainnet cutover']}
        rows={[
          [<strong key="p">Payer parts with</strong>, <Code key="t1">total</Code>, <Code key="t2">amount</Code>],
          [<strong key="y">You receive</strong>, <Code key="a1">amount</Code>, <Code key="a2">amount</Code>],
          [
            <strong key="f">Fee</strong>,
            <>A flat fee (never a percentage), read live from the contract. For USDC: <Code>0.60</Code> under 1000 USDC, <Code>3.00</Code> at or above. Native ETH is configured at zero</>,
            <>None — the contract has no fee configuration at all</>,
          ],
          [<strong key="c">Call shape</strong>, <>Carries a <Code>maxFee</Code> argument; the ERC-20 approval must cover <Code>amount + fee</Code></>, <>No fee argument; the approval covers <Code>amount</Code></>],
        ]}
      />
      <Callout variant="warn" title="What the payer signs for, today">
        On the sandbox the payer&apos;s wallet authorises <Code>total</Code> —{' '}
        <Code>amount + fee</Code> — not <Code>amount</Code>. If you render the amount yourself,
        render <Code>onchain.total</Code>, or your figure won&apos;t match what the wallet asks
        for. Every value comes back in the response: you never compute a fee client-side.
      </Callout>
      <Callout variant="info" title="Where RSends makes its money">
        Not from the payment. RSends pricing is a flat off-chain subscription; the fee above is a
        property of the currently-deployed router contract, and it disappears with the fee-less
        router at the mainnet cutover. Either way it is never netted out of your settlement.
      </Callout>

      <H2>Intent lifecycle</H2>
      <Table
        head={['status', 'Meaning']}
        rows={[
          [<Code key="p">pending</Code>, 'Created, awaiting an on-chain payment'],
          [<Code key="c">completed / paid</Code>, <>PaymentMade event matched — funds settled to your wallet. <Code>paid</Code> and <Code>completed</Code> are the same terminal success state (<Code>completed</Code> is the legacy spelling); accept both.</>],
          [<Code key="o">overpaid / partial</Code>, 'Matched outside exact amount, accepted per your tolerance policy'],
          [<Code key="e">expired</Code>, 'expires_at passed with no payment'],
          [<Code key="x">cancelled</Code>, 'You cancelled it via the cancel endpoint'],
          [<Code key="rv">review</Code>, 'Ambiguous or late payment held for manual review — resolve it below'],
          [<Code key="rf">refunded</Code>, 'A merchant-sent refund was recorded against it — see Refunds'],
        ]}
      />

      <H3>Cancel an intent</H3>
      <P>
        Cancel a still-<Code>pending</Code> intent to stop accepting payment for it. Cancellation is
        an off-chain state change — there are no funds to return, because none were ever held. Any
        other state returns <Code>400 INVALID_STATE</Code>.
      </P>
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/cancel" />
      <Callout variant="info" title="Money on-chain beats the cancel button">
        If an on-chain payment for the intent has already been observed, cancelling returns{' '}
        <Code>409 SETTLEMENT_IN_FLIGHT</Code> — the payer&apos;s funds have moved and the intent
        will settle. The same rule beats the expiry timer: an intent with an observed payment is
        never flipped to <Code>expired</Code>.
      </Callout>

      <H3>Resolve a held payment</H3>
      <P>
        An intent in <Code>review</Code> (a late payment under{' '}
        <Code>late_payment_policy: &quot;review&quot;</Code>) waits for your decision. Post{' '}
        <Code>{'{"action": "complete"}'}</Code> to accept it — which fires a{' '}
        <Code>payment.completed_late</Code> webhook — or <Code>{'{"action": "refund"}'}</Code> to
        mark it <Code>refunded</Code> for your books. Any other state returns{' '}
        <Code>400 INVALID_STATE</Code>. See <A href="/docs/refunds">Refunds</A>.
      </P>
      <Endpoint method="POST" path="/api/v1/merchant/payment-intent/{intent_id}/resolve" />

      <H3>Errors you should handle</H3>
      <Table
        head={['Code', 'HTTP', 'When']}
        rows={[
          [<Code key="1">UNSUPPORTED_TOKEN</Code>, '400', 'Token not enabled on that chain'],
          [<Code key="2">UNSUPPORTED_CHAIN</Code>, '400', 'Chain has no settlement path at all'],
          [<Code key="3">TESTNET_ONLY / MAINNET_ONLY</Code>, '400', 'Key environment vs requested chain'],
          [<Code key="4">SETTLEMENT_WALLET_MISSING</Code>, '422', 'No recipient passed and no settlement wallet set'],
          [<Code key="5">INTENT_NOT_FOUND</Code>, '404', 'Unknown id — or it belongs to someone else, or to the other environment'],
          [<Code key="6">INVALID_STATE</Code>, '400', 'Cancel/resolve from a state that doesn’t allow it'],
          [<Code key="7">SETTLEMENT_IN_FLIGHT</Code>, '409', 'Cancel after an on-chain payment was observed'],
          [<Code key="8">MONTHLY_LIMIT_EXCEEDED</Code>, '429', 'Key’s monthly intent quota reached (unlimited by default)'],
        ]}
      />
      <P>
        Full table, envelope shapes and rate limits: <A href="/docs/errors">Errors</A>.
      </P>

      <PageNav
        prev={{ href: '/docs/testing', label: 'Testing' }}
        next={{ href: '/docs/hosted-checkout', label: 'Hosted checkout' }}
      />
    </>
  )
}
