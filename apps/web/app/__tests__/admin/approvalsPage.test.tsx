/**
 * /admin/approvals fail-loud rendering: a failed read must show ONLY the
 * error — never the "Queue is empty" state (which implies a successful read
 * of an empty queue) and never a stale list.
 */
import { render, screen, waitFor } from '@testing-library/react'

const mockPush = jest.fn()
// Stable router reference, like the real useRouter — a new object each render
// would change the fetchQueue useCallback and re-fire its effect forever.
const mockRouter = { push: mockPush }
jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
}))

import AdminApprovalsPage from '@/app/admin/approvals/page'

const ROW = {
  org_id: 'org-1',
  name: 'Acme Srl',
  slug: 'acme-xyz',
  created_at: null,
  approval_requested_at: null,
  profile_submitted_at: '2026-07-14T00:00:00Z',
  company_profile: { legal_name: 'Acme Srl' },
}

function mockFetch(impl: () => Promise<Partial<Response>>) {
  global.fetch = jest.fn(impl) as unknown as typeof fetch
}

beforeEach(() => {
  mockPush.mockClear()
})

describe('AdminApprovalsPage fail-loud', () => {
  it('shows ONLY the error on a failed read — never the empty-state', async () => {
    mockFetch(async () => ({
      status: 403,
      ok: false,
      json: async () => ({ error: 'ADMIN_TOKEN_MISMATCH' }),
    }))

    render(<AdminApprovalsPage />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('ADMIN_TOKEN_MISMATCH')
    expect(screen.queryByText(/Queue is empty/)).not.toBeInTheDocument()
  })

  it('shows the empty-state only on a genuinely successful empty read', async () => {
    mockFetch(async () => ({ status: 200, ok: true, json: async () => [] }))

    render(<AdminApprovalsPage />)

    await screen.findByText(/Queue is empty/)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the queue when the read returns rows', async () => {
    mockFetch(async () => ({ status: 200, ok: true, json: async () => [ROW] }))

    render(<AdminApprovalsPage />)

    await screen.findByRole('heading', { name: 'Acme Srl', level: 2 })
    expect(screen.queryByText(/Queue is empty/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('redirects to the admin login on 401', async () => {
    mockFetch(async () => ({ status: 401, ok: false, json: async () => ({}) }))

    render(<AdminApprovalsPage />)

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/admin/login'))
  })
})
