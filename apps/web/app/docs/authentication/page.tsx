import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Endpoint, Table, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Authentication',
  description:
    'Authenticate RSends API requests with a secret API key as a Bearer token. Keys are operator-issued, scoped test or live, and hashed at rest.',
}

export default function AuthenticationPage() {
  return (
    <>
      <PageHeader
        eyebrow="Authentication"
        title="Authentication"
        lead={
          <>
            Every request to <Code>/api/v1/merchant</Code> is authenticated with a secret API key,
            sent as a Bearer token in the <Code>Authorization</Code> header.
          </>
        }
      />

      <H2>Secret API keys</H2>
      <P>
        Keys come in two environments, distinguished by their prefix. Use the test key against Base
        Sepolia while you integrate, and the live key once you go to mainnet.
      </P>
      <Table
        head={['Prefix', 'Environment', 'Settles on']}
        rows={[
          [<Code key="t">rsend_test_…</Code>, 'Test', 'Base Sepolia testnet (test tokens, no real value)'],
          [<Code key="l">rsend_live_…</Code>, 'Live', 'Mainnet — enabled per jurisdiction as RSends rolls out'],
        ]}
      />
      <CodeBlock
        label="Authorization header"
        code={`curl https://pay.rsends.io/api/backend/api/v1/merchant/transactions \\
  -H "Authorization: Bearer rsend_test_YOUR_KEY"`}
      />

      <H2>How keys are issued</H2>
      <P>
        Keys are <strong>self-serve</strong>. Sign in, open <Code>/app</Code> →{' '}
        <strong>API keys</strong> → <strong>Merchant keys</strong> and create one. You need the{' '}
        <Code>admin</Code> role in your organisation. Every key minted this way is{' '}
        <Code>rsend_test_…</Code>, scoped <Code>write</Code>, and bound to the test environment;
        live keys are issued as mainnet is enabled for your jurisdiction. You can hold up to{' '}
        <strong>5 active keys</strong> per environment — a sixth returns{' '}
        <Code>409 max_keys_reached</Code>. Revoking is immediate and idempotent.
      </P>
      <Callout variant="warn" title="Shown once, hashed at rest">
        The full secret is shown to you <strong>once</strong>, at creation. RSends stores only a
        bcrypt hash plus a short display prefix — it cannot recover or re-show the key. If you lose
        it, revoke it and mint a new one. Treat it like a password: server-side only, never in
        client code or a repo.
      </Callout>

      <H2>One prerequisite: your company profile</H2>
      <P>
        Before you can mint a key you have to submit your organisation&apos;s company profile, in{' '}
        <Code>/app</Code>. It is a single self-serve form —{' '}
        <strong>nobody has to approve you to use the sandbox</strong>. Submit it and testnet access
        is immediate.
      </P>
      <Table
        head={['Field', 'Notes']}
        rows={[
          [<Code key="1">legal_name</Code>, 'Registered company name'],
          [<Code key="2">country</Code>, 'Country of registration'],
          [<Code key="3">registration_number</Code>, 'Company registration number'],
          [<Code key="4">tax_or_vat_number</Code>, 'Tax or VAT number'],
          [<Code key="5">business_category</Code>, 'What the business does'],
          [<Code key="6">expected_monthly_volume</Code>, 'Rough band, not a commitment'],
          [<Code key="7">countries_served</Code>, 'Where your customers are'],
          [<Code key="8">primary_stablecoin</Code>, 'The token you expect to settle in'],
          [
            <em key="9">declarations</em>,
            <>Two must be affirmed (no sanctioned countries, no prohibited activities) plus a PEP disclosure. <Code>trading_name</Code> and <Code>website</Code> are optional.</>,
          ],
        ]}
      />
      <P>
        Until it is submitted, every <Code>/api/v1/merchant/*</Code> call returns <Code>403</Code>{' '}
        — with a valid key, too. That is the first thing to check when a fresh integration answers
        403 to everything.
      </P>
      <CodeBlock
        label="403 — profile not submitted yet"
        code={`{ "detail": { "code": "company_profile_required" } }

// If your organisation was explicitly declined:
{ "detail": { "code": "approval_declined", "reason": "…" } }`}
      />
      <Callout variant="info" title="Going live is where a human looks">
        Manual approval still applies to mainnet: a <Code>rsend_live_</Code> key requires an
        approved organisation, and the same call with a live key returns{' '}
        <Code>403 approval_pending</Code> until that happens. The sandbox deliberately does not
        wait on anyone — it settles faucet tokens on a testnet.
      </Callout>

      <H2>Scopes &amp; environments</H2>
      <P>
        Each key is bound to a single environment (<Code>test</Code> or <Code>live</Code>) and a
        scope. Enforcement is by <strong>HTTP method</strong>: any non-<Code>GET</Code> request made
        with a <Code>read</Code> key is rejected with <Code>403 INSUFFICIENT_SCOPE</Code>. A
        read-only key can pull <A href="/docs/reporting">reporting</A> data but cannot create
        intents.
      </P>
      <Table
        head={['Scope', 'Grants']}
        rows={[
          [<Code key="r">read</Code>, 'GET only — payment intents, transactions and reporting'],
          [<Code key="w">write</Code>, 'Everything read does, plus create/cancel/resolve intents and manage webhooks. This is what self-serve keys get'],
          [<Code key="a">admin</Code>, 'Everything write does. Not self-provisionable'],
        ]}
      />
      <P>
        The environment binding is enforced on both reads and writes: a <Code>test</Code> key
        creating an intent on a mainnet chain gets <Code>400 TESTNET_ONLY</Code>, and a{' '}
        <Code>live</Code> key on a testnet chain gets <Code>400 MAINNET_ONLY</Code>. Test and live
        data never mix — that includes webhook deliveries.
      </P>

      <H3>Retrying safely</H3>
      <P>
        Send an <Code>X-Idempotency-Key</Code> header on any <Code>POST</Code> and a retry with the
        same key replays the original response instead of re-running the operation. The record is
        kept for 24 hours, and it is scoped to your account and environment — no other merchant&apos;s
        key can collide with yours. Resend the original body unchanged: the same key with a
        different body is <Code>409 IDEMPOTENCY_KEY_REUSED</Code>. A retry that arrives while the
        first request is still in flight gets <Code>409 DUPLICATE_REQUEST_IN_FLIGHT</Code>. See{' '}
        <A href="/docs/errors">Errors</A>.
      </P>

      <H3>Authentication errors</H3>
      <P>
        A missing, malformed, or revoked key returns <Code>401</Code> with{' '}
        <Code>INVALID_API_KEY</Code>. See <A href="/docs/errors">Errors</A> for the full table.
      </P>
      <Endpoint method="GET" path="/api/v1/merchant/transactions" />

      <PageNav
        prev={{ href: '/docs/quickstart', label: 'Quickstart' }}
        next={{ href: '/docs/testing', label: 'Testing' }}
      />
    </>
  )
}
