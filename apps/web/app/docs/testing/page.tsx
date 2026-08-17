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
        RSends mirrors the classic test/live split onto chains. Your <Code>rsend_test_</Code> key
        drives the router on Base Sepolia; a <Code>rsend_live_</Code> key drives mainnet once it is
        enabled for your jurisdiction.
      </P>
      <Table
        head={['', 'Sandbox (test)', 'Production (live)']}
        rows={[
          [<strong key="k">API key</strong>, <Code key="t">rsend_test_…</Code>, <Code key="l">rsend_live_…</Code>],
          [<strong key="n">Network</strong>, 'Base Sepolia (chain 84532)', 'Base mainnet (chain 8453), per jurisdiction'],
          [<strong key="v">Token value</strong>, 'None — faucet test tokens', 'Real funds'],
          [<strong key="t2">Tokens</strong>, 'Test USDC and native ETH', <em key="tp">Enabled at rollout</em>],
          [<strong key="r">Router</strong>, <>Deployed — <Code>routerVersion 1</Code> (charges an on-chain flat fee)</>, <em key="rp">Not deployed yet — fee-less <Code>routerVersion 2</Code></em>],
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
      <Callout variant="info" title="Two enabled tokens on Base Sepolia">
        <Code>USDC</Code> and native <Code>ETH</Code> are the payable tokens on the sandbox — USDC
        is what you&apos;ll want for a realistic run. Anything else (EURC, USDT, DAI …) is not
        enabled on this chain and creating an intent with it returns{' '}
        <Code>400 UNSUPPORTED_TOKEN</Code>.
      </Callout>
      <CodeBlock
        label="Base Sepolia — enabled tokens"
        code={`USDC   6 decimals   0x036CbD53842c5426634e7929541eC2318f3dCF7e
                    faucet: https://faucet.circle.com

ETH   18 decimals   native (token address 0x0000…0000)
                    faucet: https://docs.base.org/tools/network-faucets`}
      />

      <H2>A full test run</H2>
      <Table
        head={['Step', 'Action']}
        rows={[
          ['1', <>Fund a wallet with test USDC + Base Sepolia ETH (above).</>],
          ['2', <>Create a payment intent with your <Code>rsend_test_</Code> key — see <A href="/docs/payment-intents">Payment intents</A>.</>],
          ['3', <>Open <Code>https://demo.rsends.io/pay/{'{intent_id}'}</Code>, connect the funded wallet, and pay. Note the payer is asked for <Code>onchain.total</Code>, which on this router is the amount plus a small flat fee.</>],
          ['4', <>Confirm you receive a <Code>payment.completed</Code> <A href="/docs/webhooks">webhook</A> and that the funds landed in your destination wallet.</>],
          ['5', <>Verify the <Code>PaymentMade</Code> event on <A href="https://sepolia.basescan.org">sepolia.basescan.org</A>.</>],
        ]}
      />
      <P>
        The <A href="/docs/quickstart">Quickstart</A> has this same run with copyable calls.
      </P>

      <H3>Going live</H3>
      <P>
        Mainnet is <strong>not deployed yet</strong> — the production router has not been published,
        so there is no live environment to point at today. When it opens, moving over means
        swapping three things: the API key (<Code>rsend_test_</Code> → <Code>rsend_live_</Code>),
        the chain (<Code>base_sepolia</Code> → <Code>base</Code>), and the webhook signing secret
        (register a webhook in the live environment; test and live deliveries never cross).
      </P>
      <Callout variant="warn" title="One behavioural difference to code for now">
        The production router is fee-less: <Code>onchain.fee</Code> becomes{' '}
        <Code>&quot;0&quot;</Code>, <Code>total</Code> equals <Code>amount</Code>,{' '}
        <Code>maxFee</Code> becomes <Code>null</Code>, and the call carries no fee argument. If you
        read <Code>onchain.routerVersion</Code> and use the values the API hands you rather than
        assuming, your integration needs no change at cutover. Live access also rolls out per
        jurisdiction — until your live key is enabled, the sandbox flow is the complete,
        representative integration.
      </Callout>

      <PageNav
        prev={{ href: '/docs/authentication', label: 'Authentication' }}
        next={{ href: '/docs/payment-intents', label: 'Payment intents' }}
      />
    </>
  )
}
