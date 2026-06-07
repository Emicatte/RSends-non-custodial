'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { CodeBlock } from './CodeBlock'
import { Callout } from './Callout'

/* ─────────────────────────────────────────────────────────────
   Section registry — drives both the sticky "On this page" nav
   and the scroll-spy. Order matches the content below.
   ───────────────────────────────────────────────────────────── */
const SECTIONS = [
  { id: 'overview',        label: 'Overview' },
  { id: 'authentication',  label: 'Authentication' },
  { id: 'transactions',    label: 'Transactions' },
  { id: 'distributions',   label: 'Distributions' },
  { id: 'splits',          label: 'Splits' },
  { id: 'execution',       label: 'Execution' },
  { id: 'webhooks',        label: 'Webhooks' },
  { id: 'errors',          label: 'Errors' },
] as const

/* ── HTTP method badge ─────────────────────────────────────── */
const METHOD_BG: Record<string, string> = {
  GET:    '#3B82F6',
  POST:   '#C8512C',
  PUT:    '#FFB547',
  DELETE: '#FF4C6A',
}

function Method({ m }: { m: keyof typeof METHOD_BG | string }) {
  return (
    <span
      className="inline-block rounded-md px-2 py-0.5 font-mono text-[10.5px] font-semibold tracking-wide text-white"
      style={{ background: METHOD_BG[m] ?? '#0A0A0A' }}
    >
      {m}
    </span>
  )
}

/* ── Endpoint row: method badge + monospace path ──────────────── */
function Endpoint({ method, path }: { method: string; path: string }) {
  return (
    <div className="my-3 flex items-center gap-3 rounded-lg border border-ink/10 bg-surface px-3.5 py-2.5">
      <Method m={method} />
      <code className="font-mono text-[13px] text-ink">{path}</code>
    </div>
  )
}

/* ── Generic two/three-column table with a thin border ────────── */
function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="my-5 overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr>
            {head.map((h) => (
              <th
                key={h}
                className="border-b border-ink/15 pb-2 pr-4 font-mono text-[10.5px] font-semibold uppercase tracking-wider text-ink/45"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              {r.map((cell, j) => (
                <td
                  key={j}
                  className="border-b border-ink/[0.07] py-2.5 pr-4 font-display text-[13px] leading-relaxed text-ink/75"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* mono cell helper for field/code names */
function Code({ children }: { children: ReactNode }) {
  return <code className="font-mono text-[12.5px] text-terracotta">{children}</code>
}

function H3({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-2 mt-8 font-display text-[17px] font-semibold tracking-tight text-ink">
      {children}
    </h3>
  )
}

function P({ children }: { children: ReactNode }) {
  return (
    <p className="my-3 font-display text-[14.5px] leading-relaxed text-ink/70">{children}</p>
  )
}

/* ── Animated section wrapper (fade/slide-in once on view) ────── */
function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <motion.section
      id={id}
      className="scroll-mt-24 border-t border-ink/[0.08] pt-12 first:border-t-0 first:pt-0"
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.4, ease: 'easeOut' }}
    >
      <h2 className="mb-4 font-display text-[26px] font-bold tracking-tight text-ink">{title}</h2>
      {children}
    </motion.section>
  )
}

/* ═══════════════════════════════════════════════════════════════
   Main docs body: sticky sidebar (scroll-spy) + content column.
   ═══════════════════════════════════════════════════════════════ */
export function ApiDocs() {
  const [active, setActive] = useState<string>(SECTIONS[0].id)
  const observer = useRef<IntersectionObserver | null>(null)

  useEffect(() => {
    observer.current = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-20% 0px -70% 0px', threshold: 0 },
    )
    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id)
      if (el) observer.current?.observe(el)
    })
    return () => observer.current?.disconnect()
  }, [])

  return (
    <div className="mx-auto mt-12 flex max-w-[1100px] gap-12 px-6 pb-32 md:px-10">
      {/* ── Sticky "On this page" sidebar (hidden < md) ── */}
      <aside className="hidden w-52 shrink-0 md:block">
        <nav className="sticky top-20" aria-label="On this page">
          <p className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.18em] text-ink/40">
            On this page
          </p>
          <ul className="space-y-1.5 border-l border-ink/10">
            {SECTIONS.map(({ id, label }) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className={`-ml-px block border-l-2 pl-4 font-display text-[13px] transition-colors ${
                    active === id
                      ? 'border-terracotta font-medium text-terracotta'
                      : 'border-transparent text-ink/55 hover:text-ink'
                  }`}
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>

      {/* ── Content column ── */}
      <div className="min-w-0 flex-1 space-y-12">
        {/* 1 ── OVERVIEW ──────────────────────────────────────── */}
        <Section id="overview" title="Overview">
          <P>
            RSends is a custodial, multi-chain B2B crypto payment gateway. The destination
            chain is chosen per transaction — RSends routes each payout to the network the
            merchant selects, with no single privileged chain.
          </P>
          <P>
            The REST API is served from a single base URL. Every response is{' '}
            <Code>application/json</Code>.
          </P>
          <CodeBlock label="Base URL" code="https://rsends.io/api/v1" />
          <H3>Getting started in three steps</H3>
          <Table
            head={['Step', 'What you do']}
            rows={[
              [<strong key="1">1. Create an API key</strong>, 'Generate a scoped key from the dashboard (Settings → API Keys). Shown once.'],
              [<strong key="2">2. Integrate the endpoints</strong>, 'Call the Transactions, Distributions, Splits and Execution endpoints with a Bearer token.'],
              [<strong key="3">3. Listen for webhooks</strong>, 'Register a webhook URL and verify each delivery with its HMAC signature.'],
            ]}
          />
        </Section>

        {/* 2 ── AUTHENTICATION ────────────────────────────────── */}
        <Section id="authentication" title="Authentication">
          <P>
            Every request to <Code>/api/v1</Code> is authenticated with a Bearer token in the{' '}
            <Code>Authorization</Code> header.
          </P>
          <CodeBlock
            label="Authorization header"
            code={`curl https://rsends.io/api/v1/tx/recent \\
  -H "Authorization: Bearer YOUR_API_KEY"`}
          />
          <H3>Creating a key</H3>
          <P>
            API keys are self-serve from the dashboard (Settings → API Keys), or via{' '}
            <Code>POST /api/v1/keys/generate</Code>. The plaintext key is returned{' '}
            <strong>once</strong> at creation and never shown again — store it securely.
          </P>
          <Endpoint method="POST" path="/api/v1/keys/generate" />
          <Callout variant="warn" title="Shown once">
            The full key is included in the generation response only. Subsequent list calls
            return just a display prefix.
          </Callout>
          <H3>Scopes</H3>
          <P>Keys are scoped. The six available scopes are:</P>
          <Table
            head={['Scope', 'Grants']}
            rows={[
              [<Code key="a">transactions:read</Code>, 'Read transactions, recent activity, anomalies'],
              [<Code key="b">transactions:write</Code>, 'Submit transaction callbacks'],
              [<Code key="c">routes:read</Code>, 'Read forwarding routes / distributions'],
              [<Code key="d">contacts:read</Code>, 'Read saved contacts'],
              [<Code key="e">wallets:read</Code>, 'Read wallet balances'],
              [<Code key="f">account:read</Code>, 'Read account / profile data'],
            ]}
          />
          <P>
            The live list is available at{' '}
            <Code>GET /api/v1/user/api-keys/available-scopes</Code>.
          </P>
        </Section>

        {/* 3 ── TRANSACTIONS ──────────────────────────────────── */}
        <Section id="transactions" title="Transactions">
          <P>
            The merchant notifies RSends of a transaction via a signed callback, then reads
            back transaction state and anomaly reports.
          </P>

          <H3>Submit a transaction callback</H3>
          <Endpoint method="POST" path="/api/v1/tx/callback" />
          <P>Request body (selected fields):</P>
          <Table
            head={['Field', 'Type', 'Notes']}
            rows={[
              [<Code key="1">fiscal_ref</Code>, 'string', 'Merchant fiscal reference (min 4)'],
              [<Code key="2">tx_hash</Code>, 'string', 'On-chain hash, exactly 66 chars'],
              [<Code key="3">gross_amount</Code>, 'number', '> 0'],
              [<Code key="4">net_amount</Code>, 'number', '> 0'],
              [<Code key="5">fee_amount</Code>, 'number', '≥ 0'],
              [<Code key="6">currency</Code>, 'string', 'Settlement token, e.g. USDC / EURC'],
              [<Code key="7">network</Code>, 'string', 'Destination network of the transaction'],
              [<Code key="8">status</Code>, 'string', 'Defaults to "completed"'],
              [<Code key="9">timestamp</Code>, 'datetime', 'ISO 8601 — used for anti-replay'],
              [<Code key="10">x_signature</Code>, 'string', 'HMAC signature (see below)'],
              [<Code key="11">idempotency_key</Code>, 'string?', 'Optional dedupe key'],
            ]}
          />
          <P>Response (<Code>CallbackResponse</Code>):</P>
          <CodeBlock
            label="200 application/json"
            code={`{
  "status": "success",
  "message": "Transaction recorded",
  "transaction_id": 12345,
  "compliance_logged": true,
  "matched_intent_id": "int_abc123",
  "webhook_triggered": true,
  "matching": "queued"
}`}
          />

          <H3>HMAC signature</H3>
          <P>
            The callback must include <Code>x_signature</Code>, an HMAC-SHA256 hex digest over
            a pipe-joined message. The fields are concatenated in this exact order:
          </P>
          <CodeBlock
            label="signing"
            code={`message   = f"{fiscal_ref}|{tx_hash}|{gross_amount}|{currency}|{timestamp}"
signature = HMAC_SHA256(secret, message).hexdigest()

# gross_amount is stringified; timestamp is ISO 8601 (timestamp.isoformat())`}
          />
          <Callout variant="info" title="Anti-replay">
            The timestamp must be no older than <strong>300 seconds</strong> (5 minutes).
            Signatures are compared with a constant-time <Code>compare_digest</Code> to prevent
            timing attacks.
          </Callout>

          <H3>Read transactions</H3>
          <Endpoint method="GET" path="/api/v1/tx/recent" />
          <P>
            Recent transactions. Query params: <Code>wallet</Code> (optional address),{' '}
            <Code>limit</Code> (1–20, default 5).
          </P>
          <Endpoint method="GET" path="/api/v1/tx/{fiscal_ref}" />
          <P>Full detail for a single transaction by its fiscal reference.</P>
          <Endpoint method="GET" path="/api/v1/anomalies" />
          <P>
            Anomaly report. Query params: <Code>window_hours</Code> (1–720, default 24),{' '}
            <Code>currency</Code> (optional filter). Returns{' '}
            <Code>AnomalyReportResponse</Code> with{' '}
            <Code>total_transactions</Code>, <Code>anomalies_found</Code>, <Code>alerts[]</Code>,{' '}
            <Code>analysis_window_hours</Code>.
          </P>
        </Section>

        {/* 4 ── DISTRIBUTIONS ─────────────────────────────────── */}
        <Section id="distributions" title="Distributions">
          <P>
            Distributions define a set of recipients and the basis-point share each receives.
            Shares are integer basis points and must sum to <Code>10000</Code> (100%).
          </P>
          <Endpoint method="POST"   path="/api/v1/distributions" />
          <Endpoint method="GET"    path="/api/v1/distributions" />
          <Endpoint method="GET"    path="/api/v1/distributions/{dist_id}" />
          <Endpoint method="PUT"    path="/api/v1/distributions/{dist_id}" />
          <Endpoint method="DELETE" path="/api/v1/distributions/{dist_id}" />
          <Endpoint method="POST"   path="/api/v1/distributions/{dist_id}/import-csv" />
          <Endpoint method="GET"    path="/api/v1/distributions/{dist_id}/export-csv" />
          <P>
            <Code>GET /distributions</Code> accepts an optional <Code>chain_id</Code> query
            filter. <Code>import-csv</Code> takes a multipart file upload;{' '}
            <Code>export-csv</Code> streams <Code>text/csv</Code>.
          </P>
          <P>Create body (<Code>CreateDistributionPayload</Code>):</P>
          <CodeBlock
            label="POST /api/v1/distributions"
            code={`{
  "label": "Q2 affiliate payouts",
  "chain_id": 8453,
  "recipients": [
    { "address": "0xRecipientA...", "percent_bps": 7000, "label": "Partner A" },
    { "address": "0xRecipientB...", "percent_bps": 3000, "label": "Partner B" }
  ]
}`}
          />
          <Table
            head={['Field', 'Type', 'Notes']}
            rows={[
              [<Code key="1">label</Code>, 'string', '1–100 chars'],
              [<Code key="2">chain_id</Code>, 'int', 'Destination chain id for this distribution'],
              [<Code key="3">recipients[].address</Code>, 'string', 'Exactly 42 chars'],
              [<Code key="4">recipients[].percent_bps</Code>, 'int', '1–10000; shares sum to 10000'],
              [<Code key="5">recipients[].label</Code>, 'string?', 'Optional, ≤ 100 chars'],
            ]}
          />
        </Section>

        {/* 5 ── SPLITS ────────────────────────────────────────── */}
        <Section id="splits" title="Splits">
          <P>
            Split contracts route an incoming amount across recipients (by role and basis-point
            share) plus an optional RSends fee. You can simulate a split before creating it.
          </P>
          <Endpoint method="POST" path="/api/v1/splits/contracts" />
          <Endpoint method="GET"  path="/api/v1/splits/contracts" />
          <Endpoint method="GET"  path="/api/v1/splits/contracts/{contract_id}" />
          <Endpoint method="POST" path="/api/v1/splits/contracts/{contract_id}/deactivate" />
          <Endpoint method="POST" path="/api/v1/splits/simulate" />
          <Endpoint method="GET"  path="/api/v1/splits/contracts/{contract_id}/executions" />
          <P>Create body (<Code>CreateSplitContractRequest</Code>):</P>
          <CodeBlock
            label="POST /api/v1/splits/contracts"
            code={`{
  "client_id": "acme-co",
  "client_name": "Acme Co",
  "master_wallet": "0xMasterWallet...",
  "chain_id": 8453,
  "rsend_fee_bps": 50,
  "allowed_tokens": ["USDC", "EURC"],
  "recipients": [
    { "wallet_address": "0xA...", "role": "primary",    "share_bps": 9500, "position": 0 },
    { "wallet_address": "0xB...", "role": "commission", "share_bps": 500,  "position": 1 }
  ]
}`}
          />
          <Table
            head={['Field', 'Type', 'Notes']}
            rows={[
              [<Code key="1">client_id</Code>, 'string', '1–128 chars'],
              [<Code key="2">master_wallet</Code>, 'string', 'Exactly 42 chars'],
              [<Code key="3">chain_id</Code>, 'int', 'Destination chain id (default 8453)'],
              [<Code key="4">rsend_fee_bps</Code>, 'int', '0–10000'],
              [<Code key="5">recipients[].role</Code>, 'string', 'primary | commission | fee | recipient'],
              [<Code key="6">recipients[].share_bps</Code>, 'int', '1–10000'],
            ]}
          />
          <P>
            <Code>POST /splits/simulate</Code> takes <Code>amount</Code> (human-readable),{' '}
            <Code>token</Code>, <Code>decimals</Code>, <Code>recipients</Code> and{' '}
            <Code>rsend_fee_bps</Code>, and returns the computed split plan without persisting.
          </P>
        </Section>

        {/* 6 ── EXECUTION ─────────────────────────────────────── */}
        <Section id="execution" title="Execution">
          <P>
            Execution plans describe a cross-chain payout: a source token/chain, a destination
            token/chain chosen for the payout, and the destination addresses.
          </P>
          <Endpoint method="POST" path="/api/v1/execution/plan" />
          <CodeBlock
            label="POST /api/v1/execution/plan"
            code={`{
  "owner": "0xOwner...",
  "source_chain": "tron-mainnet",
  "source_token": "USDT",
  "target_chain": "8453",
  "target_token": "USDC",
  "destinations": [
    { "address": "0xA...", "percent": 70 },
    { "address": "0xB...", "percent": 30 }
  ],
  "notify": true
}`}
          />
          <P>
            Returns <Code>{'{ plan_id, steps[], total_steps }'}</Code>, where each step has{' '}
            <Code>type</Code>, <Code>chain</Code>, <Code>status</Code> and <Code>params</Code>.
          </P>
          <Endpoint method="POST" path="/api/v1/execution/plan/{plan_id}/execute" />
          <Endpoint method="GET"  path="/api/v1/execution/plan/{plan_id}" />
          <Callout variant="warn" title="Not yet implemented">
            <Code>execute</Code> and <Code>plan status</Code> currently return HTTP{' '}
            <strong>501</strong>. The plan-creation endpoint above is live; execution and
            status retrieval are on the roadmap.
          </Callout>
        </Section>

        {/* 7 ── WEBHOOKS ──────────────────────────────────────── */}
        <Section id="webhooks" title="Webhooks">
          <P>
            Register an HTTPS endpoint to receive payment events. Each delivery is signed so you
            can verify authenticity.
          </P>

          <H3>Register a webhook</H3>
          <Endpoint method="POST" path="/api/v1/merchant/webhook/register" />
          <CodeBlock
            label="request — RegisterWebhookRequest"
            code={`{
  "url": "https://your-app.example.com/rsends/webhook",
  "events": ["payment.completed", "payment.expired"]
}`}
          />
          <CodeBlock
            label="response — RegisterWebhookResponse"
            code={`{
  "webhook_id": 42,
  "url": "https://your-app.example.com/rsends/webhook",
  "secret": "a1b2c3...   (64 hex chars)",
  "events": ["payment.completed", "payment.expired"],
  "is_active": true
}`}
          />
          <Callout variant="warn" title="Secret shown once">
            The <Code>secret</Code> (a <Code>token_hex(32)</Code> → 64-char hex string) is
            returned only in this registration response. Store it — it is used to verify the
            HMAC signature on every delivery and cannot be retrieved again.
          </Callout>

          <H3>Test a webhook</H3>
          <Endpoint method="POST" path="/api/v1/merchant/webhook/test" />
          <P>
            Request <Code>{'{ "webhook_id": 42 }'}</Code> → response{' '}
            <Code>{'{ status, response_code, message }'}</Code>.
          </P>

          <H3>Event payload</H3>
          <P>Deliveries POST a JSON body with these fields:</P>
          <CodeBlock
            label="event payload"
            code={`{
  "event": "payment.completed",
  "intent_id": "int_abc123",
  "merchant_id": "acme-co",
  "amount": "100.00",
  "currency": "USDC",
  "chain": "<destination_chain>",
  "deposit_address": "0xDeposit...",
  "recipient": "0xRecipient...",
  "network": "<network>",
  "tx_hash": "0x...",
  "status": "completed",
  "metadata": { },
  "timestamp": "2026-06-07T12:00:00+00:00",
  "completed_late": false,
  "late_minutes": null,
  "amount_received": "100.00",
  "overpaid_amount": null,
  "underpaid_amount": null,
  "created_at": "2026-06-07T11:58:00+00:00",
  "completed_at": "2026-06-07T12:00:00+00:00"
}`}
          />
          <P>
            <Code>chain</Code> and <Code>network</Code> reflect the destination network chosen
            for that payment — they vary per transaction.
          </P>

          <H3>Event types</H3>
          <Table
            head={['Event', '']}
            rows={[
              [<Code key="1">payment.completed</Code>, 'Payment received and settled'],
              [<Code key="2">payment.completed_late</Code>, 'Settled after the expected window'],
              [<Code key="3">payment.expired</Code>, 'Intent expired without payment'],
              [<Code key="4">payment.expired_rejected</Code>, 'Expired and rejected'],
              [<Code key="5">payment.needs_review</Code>, 'Flagged for manual review'],
              [<Code key="6">payment.cancelled</Code>, 'Intent cancelled'],
              [<Code key="7">payment.partial</Code>, 'Underpaid / partial amount'],
              [<Code key="8">payment.overpaid</Code>, 'Amount exceeded the request'],
              [<Code key="9">payment.ambiguous</Code>, 'Could not be matched unambiguously'],
            ]}
          />

          <H3>Delivery headers &amp; signature</H3>
          <Table
            head={['Header', 'Value']}
            rows={[
              [<Code key="1">X-RSend-Signature</Code>, <span key="v1">HMAC-SHA256(secret, raw_body) hex digest</span>],
              [<Code key="2">X-RSend-Event</Code>, 'The event type'],
              [<Code key="3">X-RSend-Delivery</Code>, 'Per-delivery UUID'],
              [<Code key="4">X-RSend-Delivery-Id</Code>, 'Idempotency key: {intent_id}:{event}:{webhook_id}'],
              [<Code key="5">User-Agent</Code>, 'RSend-Webhook/1.0'],
            ]}
          />
          <Callout variant="info" title="Verify every delivery">
            Recompute <Code>HMAC_SHA256(secret, raw_request_body)</Code> and compare it, in
            constant time, against <Code>X-RSend-Signature</Code> before trusting the payload.
            Use <Code>X-RSend-Delivery-Id</Code> for idempotency.
          </Callout>

          <H3>Stored objects</H3>
          <P><strong>Webhook</strong> (<Code>merchant_webhooks</Code>):</P>
          <Table
            head={['Field', 'Type']}
            rows={[
              [<Code key="1">id</Code>, 'int'],
              [<Code key="2">merchant_id</Code>, 'string'],
              [<Code key="3">url</Code>, 'string'],
              [<Code key="4">secret</Code>, 'string (HMAC secret)'],
              [<Code key="5">events</Code>, 'string[]'],
              [<Code key="6">is_active</Code>, 'bool'],
              [<Code key="7">created_at</Code>, 'datetime'],
            ]}
          />
          <P><strong>Delivery</strong> (<Code>webhook_deliveries</Code>):</P>
          <Table
            head={['Field', 'Type']}
            rows={[
              [<Code key="1">id</Code>, 'int'],
              [<Code key="2">webhook_id</Code>, 'int (FK)'],
              [<Code key="3">idempotency_key</Code>, 'string (unique)'],
              [<Code key="4">event_type</Code>, 'string'],
              [<Code key="5">payload</Code>, 'json'],
              [<Code key="6">status</Code>, 'enum (pending / …)'],
              [<Code key="7">response_code</Code>, 'int?'],
              [<Code key="8">response_body</Code>, 'text?'],
              [<Code key="9">retries</Code>, 'int'],
              [<Code key="10">next_retry_at</Code>, 'datetime?'],
              [<Code key="11">created_at</Code>, 'datetime'],
              [<Code key="12">delivered_at</Code>, 'datetime?'],
            ]}
          />
        </Section>

        {/* 8 ── ERRORS ────────────────────────────────────────── */}
        <Section id="errors" title="Errors">
          <P>
            Errors return a JSON envelope with a machine-readable <Code>error</Code> code, a
            human-readable <Code>message</Code>, and optional <Code>detail</Code> context.
          </P>
          <CodeBlock
            label="error envelope"
            code={`{
  "error": "INVALID_SIGNATURE",
  "message": "HMAC signature verification failed",
  "detail": null
}`}
          />
          <P>
            Status conventions follow HTTP: <Code>2xx</Code> success, <Code>4xx</Code> client
            error, <Code>5xx</Code> server / upstream error.
          </P>
          <Table
            head={['Code', 'HTTP', 'Message']}
            rows={[
              [<Code key="1">INVALID_ADDRESS</Code>, '400', 'Invalid Ethereum address format or checksum'],
              [<Code key="2">INVALID_AMOUNT</Code>, '400', 'Amount must be positive and within valid range'],
              [<Code key="3">INVALID_CHAIN_ID</Code>, '400', 'Unsupported chain ID'],
              [<Code key="4">MISSING_REQUIRED_FIELD</Code>, '400', 'Required field is missing'],
              [<Code key="5">DUPLICATE_TRANSACTION</Code>, '409', 'Transaction already processed'],
              [<Code key="6">DUPLICATE_WEBHOOK</Code>, '200', 'Webhook already processed'],
              [<Code key="7">INVALID_SIGNATURE</Code>, '401', 'HMAC signature verification failed'],
              [<Code key="8">INVALID_API_KEY</Code>, '401', 'Invalid or missing API key'],
              [<Code key="9">RATE_LIMITED</Code>, '429', 'Too many requests — retry after cooldown'],
              [<Code key="10">INSUFFICIENT_BALANCE</Code>, '402', 'Insufficient balance for this operation'],
              [<Code key="11">GAS_TOO_HIGH</Code>, '503', 'Gas price exceeds configured limit — retry later'],
              [<Code key="12">DAILY_LIMIT_EXCEEDED</Code>, '403', 'Daily volume limit exceeded'],
              [<Code key="13">RULE_NOT_FOUND</Code>, '404', 'Forwarding rule not found'],
              [<Code key="14">RULE_PAUSED</Code>, '403', 'Forwarding rule is paused'],
              [<Code key="15">COOLDOWN_ACTIVE</Code>, '429', 'Cooldown period active — retry later'],
              [<Code key="16">SERVICE_UNAVAILABLE</Code>, '503', 'Service temporarily unavailable'],
              [<Code key="17">REDIS_UNAVAILABLE</Code>, '503', 'Cache service unavailable — retry later'],
              [<Code key="18">RPC_ERROR</Code>, '502', 'Blockchain RPC error'],
              [<Code key="19">DB_ERROR</Code>, '500', 'Database error'],
              [<Code key="20">BLACKLISTED_WALLET</Code>, '403', 'Wallet address is blacklisted'],
              [<Code key="21">SUSPICIOUS_ACTIVITY</Code>, '403', 'Transaction flagged for suspicious activity'],
            ]}
          />
        </Section>
      </div>
    </div>
  )
}
