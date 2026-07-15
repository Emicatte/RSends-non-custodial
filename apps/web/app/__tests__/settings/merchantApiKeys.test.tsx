/**
 * MerchantApiKeys — the session-minted rsend_ section on /app/api-keys
 * (Option B, 2026-07-15). Pins:
 *   • fresh merchant (409 no_primary_wallet) → actionable "set your
 *     settlement wallet" card, mint button disabled;
 *   • keys render prefix-only; admins get Revoke (confirm-first), viewers
 *     get neither mint nor revoke;
 *   • contested identity (settlement_wallet_conflict) renders the loud
 *     error card, not a retry loop.
 */

import { render, screen } from '@testing-library/react'
import { MerchantApiKeys } from '@/components/settings/MerchantApiKeys'
import type { MerchantKeyItem } from '@/hooks/useMerchantApiKeys'

const mockHook = jest.fn()
jest.mock('@/hooks/useMerchantApiKeys', () => ({
  useMerchantApiKeys: () => mockHook(),
}))

const KEY: MerchantKeyItem = {
  id: 1,
  prefix: 'rsend_test_abcd1234',
  label: 'Demo store',
  scope: 'write',
  environment: 'test',
  is_active: true,
  session_minted: true,
  created_at: '2026-07-15T00:00:00Z',
  last_used_at: null,
  revoked_at: null,
}

function hookState(overrides: Record<string, unknown> = {}) {
  return {
    keys: [],
    maxAllowed: 5,
    remainingSlots: 5,
    ownerAddress: null,
    loading: false,
    saving: false,
    error: null,
    isAuthed: true,
    activeOrg: { id: 'org_1' },
    currentUserRole: 'admin',
    reload: jest.fn(),
    createKey: jest.fn(),
    revokeKey: jest.fn(),
    ...overrides,
  }
}

beforeEach(() => mockHook.mockReset())

it('fresh merchant: no_primary_wallet renders the set-settlement-wallet card and disables mint', () => {
  mockHook.mockReturnValue(hookState({ error: 'no_primary_wallet' }))
  render(<MerchantApiKeys />)

  expect(
    screen.getByText(/set your settlement wallet first/i),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: /create merchant key/i }),
  ).toBeDisabled()
})

it('admin sees prefix-only keys with a revoke button', () => {
  mockHook.mockReturnValue(
    hookState({ keys: [KEY], remainingSlots: 4, ownerAddress: '0x' + 'a'.repeat(40) }),
  )
  render(<MerchantApiKeys />)

  expect(screen.getByText(/rsend_test_abcd1234/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument()
  // never any full-key material in the list
  expect(document.body.textContent).not.toMatch(/rsend_test_[a-f0-9]{48}/)
})

it('viewer gets neither mint nor revoke', () => {
  mockHook.mockReturnValue(hookState({ keys: [KEY], currentUserRole: 'viewer' }))
  render(<MerchantApiKeys />)

  expect(
    screen.queryByRole('button', { name: /create merchant key/i }),
  ).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument()
  expect(screen.getByText(/only org admins/i)).toBeInTheDocument()
})

it('contested identity renders the conflict card', () => {
  mockHook.mockReturnValue(hookState({ error: 'settlement_wallet_conflict' }))
  render(<MerchantApiKeys />)

  expect(
    screen.getByText(/already claimed by another account/i),
  ).toBeInTheDocument()
})
