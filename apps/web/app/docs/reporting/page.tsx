import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Reporting',
  description:
    'List RSends transactions and summarize volume. The data is sourced from indexed on-chain PaymentMade events — not an internal ledger. Your principal arrives whole; the fee is paid on-chain to the fee collector.',
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
          [<Code key="s">status</Code>, 'pending · completed · expired · cancelled · review · refunded · partial · overpaid'],
          [<Code key="c">currency</Code>, 'Settlement token filter, e.g. USDC'],
          [<Code key="p">page / per_page</Code>, 'Pagination'],
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
      "intent_id": "int_abc123",
      "onchain_invoice_id": "0x9f…",
      "amount": 100,
      "amount_received": "100",
      "currency": "USDC",
      "chain": "base_sepolia",
      "status": "completed",
      "tx_hash": "0x…",
      "metadata": { "order_id": "ORD-1024" },
      "created_at": "2026-06-30T12:00:00+00:00",
      "completed_at": "2026-06-30T12:00:05+00:00"
    }
  ]
}`}
      />

      <H2>Where the numbers come from</H2>
      <P>
        Each completed record corresponds to a <Code>PaymentMade</Code> event that the RSends indexer
        read from the chain and matched to your intent by <Code>onchain_invoice_id</Code>. Reporting
        is a <strong>view over indexed on-chain events</strong>, not an internal balance sheet.
      </P>
      <Callout variant="chain" title="Reconcile against the chain">
        For any record, take its <Code>tx_hash</Code> to BaseScan and confirm the{' '}
        <Code>PaymentMade</Code> event yourself — amount, recipient, payer, fee. Your books and the
        chain should match exactly, because the chain is what RSends indexed in the first place.
      </Callout>

      <H2>Fees and what you receive</H2>
      <P>
        The amount you see settled is the <strong>whole principal you asked for</strong>. The flat
        fee was paid <strong>on-chain to the fee collector by the payer</strong>, on top of your
        amount, in the same transaction — it is never deducted from your settlement.
      </P>
      <Table
        head={['Figure', 'Meaning']}
        rows={[
          [<Code key="a">amount</Code>, 'What you requested — and exactly what landed in your wallet'],
          [<Code key="ar">amount_received</Code>, 'The matched on-chain amount (equals amount within your tolerance)'],
          [<Code key="f">fee</Code>, <>Paid by the payer to the fee collector on-chain — readable from the <Code>PaymentMade</Code> event, not netted from your principal</>],
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
