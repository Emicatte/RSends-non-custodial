import type { Metadata } from 'next'
import { CodeBlock } from '../_components/CodeBlock'
import { Callout } from '../_components/Callout'
import { H2, H3, P, A, Code, Table, UL, LI, PageHeader, PageNav } from '../_components/primitives'

export const metadata: Metadata = {
  title: 'Testing',
  description:
    'Test RSends end-to-end on Base Sepolia with a wallet funded from public faucets. No real value moves. Swap your key and webhook secret to go live.',
}

export default function TestingPage() {
  return (
    <>
      <PageHeader
        eyebrow="Testing"
        title="Testing"
        lead={
          <>
            You integrate against <strong>Base Sepolia</strong>, a public testnet, using tokens that
            carry <strong>no real value</strong>. Everything works exactly as it will in
            production — the only difference is the network and the keys.
          </>
        }
      />

      <H2>Testnet vs mainnet</H2>
      <P>
        RSends mirrors the classic test/live split onto chains. Your <Code>rk_test_</Code> key drives
        the testnet router on Base Sepolia; your <Code>rk_live_</Code> key drives mainnet once it is
        enabled for your jurisdiction.
      </P>
      <Table
        head={['', 'Test', 'Live']}
        rows={[
          [<strong key="k">API key</strong>, <Code key="t">rk_test_…</Code>, <Code key="l">rk_live_…</Code>],
          [<strong key="n">Network</strong>, 'Base Sepolia (chain 84532)', 'Mainnet, per jurisdiction'],
          [<strong key="v">Token value</strong>, 'None — faucet test tokens', 'Real funds'],
          [<strong key="t2">Tokens</strong>, 'Test USDC', 'USDC (more rolling out)'],
        ]}
      />

      <H2>Fund a test wallet</H2>
      <P>
        Instead of a test card number, you fund a real wallet with free testnet tokens, then pay
        yourself end-to-end. You need two things:
      </P>
      <UL>
        <LI>
          <strong>Test USDC</strong> to pay with — mint it at{' '}
          <A href="https://faucet.circle.com">faucet.circle.com</A> (select Base Sepolia).
        </LI>
        <LI>
          <strong>A little Base Sepolia ETH</strong> for gas — grab it from the{' '}
          <A href="https://docs.base.org/tools/network-faucets">Base network faucets</A>.
        </LI>
      </UL>
      <Callout variant="info" title="USDC is the enabled token today">
        On the deployed Base Sepolia router, <strong>USDC is the one payable token</strong>. Its test
        contract is below. Other stablecoins (e.g. EURC) are carried as “coming soon” until enabled
        on-chain, so a test payment with them will not go through yet.
      </Callout>
      <CodeBlock
        label="Base Sepolia — test USDC"
        code={`Token:    USDC (6 decimals)
Address:  0x036CbD53842c5426634e7929541eC2318f3dCF7e
Faucet:   https://faucet.circle.com`}
      />

      <H2>A full test run</H2>
      <Table
        head={['Step', 'Action']}
        rows={[
          ['1', <>Fund a wallet with test USDC + Base Sepolia ETH (above).</>],
          ['2', <>Create a payment intent with your <Code>rk_test_</Code> key — see <A href="/docs/payment-intents">Payment intents</A>.</>],
          ['3', <>Open the returned <Code>checkout_url</Code>, connect the funded wallet, and pay.</>],
          ['4', <>Confirm you receive a <Code>payment.completed</Code> <A href="/docs/webhooks">webhook</A> and that the funds landed in your destination wallet.</>],
          ['5', <>Verify the <Code>PaymentMade</Code> event on <A href="https://sepolia.basescan.org">sepolia.basescan.org</A>.</>],
        ]}
      />

      <H3>Going live</H3>
      <P>
        To move to mainnet, <strong>swap both secrets</strong>: replace your <Code>rk_test_</Code>{' '}
        key with the <Code>rk_live_</Code> key, and replace the webhook signing secret with the one
        issued for your live webhook. Point your integration at the same endpoints — only the
        credentials and network change.
      </P>
      <Callout variant="warn" title="Mainnet is gated">
        Live access rolls out per jurisdiction during the private beta. Until your live key is
        enabled, treat the testnet flow as the complete, representative integration.
      </Callout>

      <PageNav
        prev={{ href: '/docs/authentication', label: 'Authentication' }}
        next={{ href: '/docs/payment-intents', label: 'Payment intents' }}
      />
    </>
  )
}
