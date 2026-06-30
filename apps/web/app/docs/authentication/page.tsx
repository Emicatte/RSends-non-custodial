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
          [<Code key="t">rk_test_…</Code>, 'Test', 'Base Sepolia testnet (test tokens, no real value)'],
          [<Code key="l">rk_live_…</Code>, 'Live', 'Mainnet — enabled per jurisdiction as RSends rolls out'],
        ]}
      />
      <CodeBlock
        label="Authorization header"
        code={`curl https://pay.rsends.io/api/v1/merchant/transactions \\
  -H "Authorization: Bearer rk_test_YOUR_KEY"`}
      />

      <H2>How keys are issued</H2>
      <P>
        RSends is in private beta, so keys are <strong>issued by the operator</strong> — there is no
        self-serve signup or key-generation endpoint yet. You receive your key out-of-band when your
        account is provisioned.
      </P>
      <Callout variant="warn" title="Shown once, hashed at rest">
        The full secret is shown to you <strong>once</strong>, at issuance. RSends stores only a
        salted hash plus a short display prefix — it cannot recover or re-show the key. If you lose
        it, the operator rotates it for a new one. Treat it like a password: server-side only, never
        in client code or a repo.
      </Callout>

      <H2>Scopes &amp; environments</H2>
      <P>
        Each key is bound to a single environment (<Code>test</Code> or <Code>live</Code>) and a
        scope that limits what it can do. A read-only key can pull{' '}
        <A href="/docs/reporting">reporting</A> data but cannot create intents.
      </P>
      <Table
        head={['Scope', 'Grants']}
        rows={[
          [<Code key="r">read</Code>, 'Read payment intents, transactions and reporting'],
          [<Code key="w">write</Code>, 'Create and cancel payment intents, manage webhooks'],
        ]}
      />

      <H3>Authentication errors</H3>
      <P>
        A missing, malformed, or revoked key returns <Code>401</Code> with{' '}
        <Code>INVALID_API_KEY</Code>. Using a <Code>test</Code> key against live data (or the
        reverse) is rejected the same way. See <A href="/docs/errors">Errors</A>.
      </P>
      <Endpoint method="GET" path="/api/v1/merchant/transactions" />

      <PageNav
        prev={{ href: '/docs', label: 'Overview' }}
        next={{ href: '/docs/testing', label: 'Testing' }}
      />
    </>
  )
}
