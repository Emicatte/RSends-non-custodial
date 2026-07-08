/**
 * Phase D — the /app create-payment-request flow.
 *
 * Two layers:
 *   (a) CreatePaymentModal (prop-driven, no session/fetch): the recipient-gate UX
 *       (banner + disabled submit when no settlement wallet and no override), and
 *       the shareable /pay link surfaced on success.
 *   (b) useOrgPayments.createIntent: the POST carries a Bearer token, NO
 *       wallet-signature headers, and never sends `environment` (hard-lock test).
 *
 * The next-intl mock throws on any missing key → guards the create i18n too.
 */
import { render, screen, fireEvent, waitFor, renderHook, act } from '@testing-library/react'

jest.mock('next-intl', () => ({
  useTranslations: (namespace: string) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const messages = require('@/messages/en.json')
    const ns = namespace
      .split('.')
      .reduce((node: any, part: string) => node?.[part], messages)
    return (key: string) => {
      const value = key
        .split('.')
        .reduce((node: any, part: string) => node?.[part], ns)
      if (typeof value !== 'string') {
        throw new Error(`Missing message ${namespace}.${key}`)
      }
      return value
    }
  },
}))

jest.mock('@/i18n/navigation', () => ({
  Link: ({ href, children, ...rest }: any) => (
    <a href={typeof href === 'string' ? href : String(href)} {...rest}>
      {children}
    </a>
  ),
}))

jest.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { access_token: 'tok' },
    status: 'authenticated',
  }),
}))

import { CreatePaymentModal } from '@/components/app/CreatePaymentModal'
import { useOrgPayments } from '@/hooks/useOrgPayments'

const WALLET = '0xabc0000000000000000000000000000000000001'

afterEach(() => {
  jest.resetAllMocks()
})

// ── (a) Modal: recipient-gate UX ─────────────────────────────────

it('blocks submit + guides to Settings when no settlement wallet and no override', () => {
  render(
    <CreatePaymentModal settlementWallet={null} onCreate={jest.fn()} onClose={jest.fn()} />,
  )

  expect(
    screen.getByText(
      "Set your organization's settlement wallet to receive payments.",
    ),
  ).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Set settlement wallet' })).toHaveAttribute(
    'href',
    '/settings',
  )

  // Even with a valid amount, submit stays disabled (no resolvable recipient).
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  expect(
    screen.getByRole('button', { name: 'Create payment request' }),
  ).toBeDisabled()
})

it('creates with the org default and surfaces the shareable /pay link', async () => {
  const onCreate = jest.fn().mockResolvedValue({
    intent_id: 'pi_new',
    recipient: null,
    amount: 100,
    currency: 'USDC',
    chain: 'base_sepolia',
    status: 'pending',
  })

  render(
    <CreatePaymentModal settlementWallet={WALLET} onCreate={onCreate} onClose={jest.fn()} />,
  )

  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '100' } })
  const submit = screen.getByRole('button', { name: 'Create payment request' })
  expect(submit).toBeEnabled()
  fireEvent.click(submit)

  // Testnet-locked payload; no explicit recipient (uses the org default).
  await waitFor(() =>
    expect(onCreate).toHaveBeenCalledWith({
      amount: 100,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
    }),
  )

  // The /pay link is surfaced for the merchant to share.
  await waitFor(() =>
    expect(screen.getByText('http://localhost/pay/pi_new')).toBeInTheDocument(),
  )
})

// ── (b) Hook: the create POST is session-authed, testnet-locked ──

it('createIntent POSTs with a Bearer token, no wallet headers, and no environment', async () => {
  const fn = jest.fn().mockImplementation((_url: unknown, opts: any) => {
    const body =
      opts?.method === 'POST'
        ? { intent_id: 'pi_x', recipient: null, amount: 10, currency: 'USDC', chain: 'base_sepolia', status: 'pending' }
        : { total: 0, page: 1, per_page: 20, records: [] }
    return Promise.resolve({ ok: true, status: 200, json: async () => body })
  })
  global.fetch = fn as unknown as typeof fetch

  const { result } = renderHook(() => useOrgPayments())

  await act(async () => {
    await result.current.createIntent({
      amount: 10,
      currency: 'USDC',
      chain: 'base_sepolia',
      expires_in_minutes: 30,
    })
  })

  const post = fn.mock.calls.find(([, o]: any[]) => o?.method === 'POST') as [
    string,
    RequestInit,
  ]
  expect(post).toBeDefined()
  const [url, options] = post
  expect(String(url)).toContain('/api/v1/user/org/payment-intents')
  expect(String(url)).not.toContain('environment')
  expect(String(options.body)).not.toContain('environment')

  const headers = new Headers(options.headers)
  expect(headers.get('authorization')).toBe('Bearer tok')
  for (const key of headers.keys()) {
    expect(key.toLowerCase().startsWith('x-wallet')).toBe(false)
  }
})
