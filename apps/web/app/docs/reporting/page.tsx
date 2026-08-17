import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Reporting',
  description:
    'List RSends transactions and summarize volume. The data is sourced from indexed on-chain PaymentMade events — not an internal ledger. Your principal arrives whole; no fee is taken in the payment flow.',
}

export default function ReportingPage() {
  return (
    <>
      <PageHeader
        eyebrow="After payment"
        title="Reporting"
        lead={
          <>
            List your transactions and roll up volume for reconciliation. Every figure traces back to
            a public on-chain event — there is no private ledger you have to trust.
          </>
        }
      />

      <H2>List transactions</H2>
      <Endpoint method="GET" path="/api/v1/merchant/transactions" />
      <P>
        Returns your intents and their settlement state, newest first, paginated. Filter by{' '}
        <Code>status</Code> or <Code>currency</Code> to reconcile.
      </P>
      <Table
        head={['Query param', 'Notes']}
        rows={[
          [<Code key="s">status</Code>, <>One of <Code>pending</Code> · <Code>paid</Code> · <Code>completed</Code> · <Code>expired</Code> · <Code>cancelled</Code> · <Code>review</Code> · <Code>refunded</Code> · <Code>partial</Code> · <Code>overpaid</Code>. Anything else is rejected with <Code>400 INVALID_STATUS</Code> — never silently ignored</>],
          [<Code key="c">currency</Code>, 'Settlement token filter, e.g. USDC. Exact match'],
          [<Code key="p">page</Code>, 'Page number, ≥ 1. Default 1'],
          [<Code key="pp">per_page</Code>, 'Results per page, 1–100. Default 20'],
        ]}
      />
      <CodeBlock
        label="GET /api/v1/merchant/transactions?status=completed"
        code={`{
  "total": 128,
  "page": 1,
  "per_page": 20,
  "records": [
    {
      "intent_id": "pi_9f1c4a7e2b5d8036c1e94ab7d2508f63",
      "onchain_invoice_id": "0x9f…",
      "amount": 100.0,
      "amount_received": "100",
      "overpaid_amount": null,
      "underpaid_amount": null,
      "currency": "USDC",
      "chain": "base_sepolia",
      "status": "completed",
      "recipient": "0xyourdestinationwallet00000000000000000000",
      "tx_hash": "0x…",
      "matched_tx_hash": "0x…",
      "completed_late": false,
      "late_minutes": null,
      "metadata": { "order_id": "ORD-1024" },
      "created_at": "2026-08-06T12:00:00+00:00",
      "expires_at": "2026-08-06T12:30:00+00:00",
      "completed_at": "2026-08-06T12:00:05+00:00"
    }
  ]
}`}
      />
      <P>
        Results are scoped to your account <em>and</em> your key&apos;s environment: a test key
        never sees live intents, and vice versa. Newest first.
      </P>

      <H2>Where the numbers come from</H2>
      <P>
        Each completed record corresponds to a <Code>PaymentMade</Code> event that the RSends indexer
        read from the chain and matched to your intent by <Code>onchain_invoice_id</Code>. Reporting
        is a <strong>view over indexed on-chain events</strong>, not an internal balance sheet.
      </P>
      <Callout variant="chain" title="Reconcile against the chain">
        For any record, take its <Code>tx_hash</Code> to BaseScan and confirm the{' '}
        <Code>PaymentMade</Code> event yourself — amount, recipient, payer. Your books and the
        chain should match exactly, because the chain is what RSends indexed in the first place.
      </Callout>

      <H2>What you receive</H2>
      <P>
        The amount you see settled is the <strong>whole principal you asked for</strong>. Nothing
        is ever deducted from a settlement: RSends never takes custody, and its pricing is a flat
        off-chain subscription. Where the deployed router charges an on-chain flat fee, the{' '}
        <em>payer</em> pays it on top of your amount — it is never netted out of what reaches you.
        The fee-less router arriving at the mainnet cutover removes it from the flow entirely.
      </P>
      <Table
        head={['Figure', 'Meaning']}
        rows={[
          [<Code key="a">amount</Code>, 'What you requested — and exactly what landed in your wallet'],
          [<Code key="ar">amount_received</Code>, 'The matched on-chain amount (equals amount within your tolerance)'],
        ]}
      />
      <Callout variant="info" title="No withholding">
        Because RSends never takes custody, nothing is held back from a payment. There is no reserve,
        no rolling withholding, and no <Code>reserve_withheld</Code> line — every settled payment is
        final and whole the moment it confirms.
      </Callout>

      <H3>Volume summary</H3>
      <P>
        Aggregate by paging through completed records and summing <Code>amount</Code> per{' '}
        <Code>currency</Code>, or filter by date range using <Code>created_at</Code> /{' '}
        <Code>completed_at</Code>. Because the underlying truth is on-chain, a periodic
        chain-vs-report reconciliation is straightforward and worth automating.
      </P>

      <PageNav
        prev={{ href: '/docs/webhooks', label: 'Webhooks' }}
        next={{ href: '/docs/refunds', label: 'Refunds' }}
      />
    </>
  )
}
