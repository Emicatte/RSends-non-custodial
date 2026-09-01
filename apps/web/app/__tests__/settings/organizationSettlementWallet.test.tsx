/**
 * OrganizationSettings — the two settlement wallets (EVM + TRON).
 *
 * The TRON payout address is base58check: case-SENSITIVE, checksummed, and
 * unrecoverable if wrong, because TRON is watch-only here and no contract in
 * the path can reject a bad payee for us. So these pin the properties that
 * would silently lose a merchant's money:
 *   • a saved T-address goes over the wire byte-identical, casing intact;
 *   • the two fields refuse each other's address family, by name;
 *   • the TRON zero address is refused (its checksum is valid — nothing else
 *     catches it);
 *   • patching one wallet never touches the other;
 *   • an org with no TRON wallet renders an empty field, not a broken one.
 *
 * `intlMock` resolves against messages/en.json and throws on a missing key, so
 * rendering this component also guards the new i18n keys.
 */

import { render, screen, fireEvent, within } from '@testing-library/react'
import { OrganizationSettings } from '@/components/settings/OrganizationSettings'
import type { OrganizationListItem } from '@/hooks/useOrganizations'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())
jest.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'u1' } }, status: 'authenticated' }),
}))
jest.mock('@/hooks/useOrgMembers', () => ({
  useOrgMembers: () => ({
    members: [],
    maxAllowed: 5,
    invites: [],
    loading: false,
    saving: false,
    error: null,
    reload: jest.fn(),
    inviteMember: jest.fn(),
    changeRole: jest.fn(),
    removeMember: jest.fn(),
    revokeInvite: jest.fn(),
    clearError: jest.fn(),
  }),
}))

const mockOrgsHook = jest.fn()
jest.mock('@/hooks/useOrganizations', () => ({
  useOrganizations: () => mockOrgsHook(),
}))

// A real TRC-20 address (USDT on TRON): valid base58check, mixed case.
const TRON_WALLET = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'
const TRON_ZERO = 'T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb'
const EVM_WALLET = '0xabc0000000000000000000000000000000000001'

function org(overrides: Partial<OrganizationListItem> = {}): OrganizationListItem {
  return {
    id: 'org_1',
    name: 'Acme',
    slug: 'acme',
    owner_user_id: 'u1',
    is_personal: false,
    plan: 'free',
    settlement_wallet: EVM_WALLET,
    settlement_wallet_tron: null,
    role: 'admin',
    member_count: 1,
    created_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

function mountWith(updateOrganization: jest.Mock, o = org()) {
  mockOrgsHook.mockReturnValue({
    organizations: [o],
    activeOrgId: o.id,
    loading: false,
    saving: false,
    error: null,
    updateOrganization,
  })
  return render(<OrganizationSettings />)
}

/**
 * The settlement card only. The org *name* field above it has its own "Edit"
 * button, so an unscoped query would match two.
 */
function settlementSection(): HTMLElement {
  const section = screen.getByText('EVM payout address').closest('section')
  if (!section) throw new Error('settlement section not found')
  return section
}

/** Open the TRON field's editor and type `value` into it. */
function typeIntoTronField(value: string) {
  fireEvent.click(screen.getByRole('button', { name: /set tron wallet/i }))
  const input = screen.getByPlaceholderText('T…')
  fireEvent.change(input, { target: { value } })
  return input
}

beforeEach(() => mockOrgsHook.mockReset())

it('a valid T-address saves and round-trips byte-identical, case intact', () => {
  const updateOrganization = jest.fn().mockResolvedValue(undefined)
  const { rerender } = mountWith(updateOrganization)

  const input = typeIntoTronField(TRON_WALLET)
  fireEvent.keyDown(input, { key: 'Enter' })

  // Exact string, not a case-insensitive match: base58check is case-sensitive.
  expect(updateOrganization).toHaveBeenCalledWith('org_1', {
    settlement_wallet_tron: TRON_WALLET,
  })

  // And it comes back out of the hook rendered exactly as stored.
  mockOrgsHook.mockReturnValue({
    organizations: [org({ settlement_wallet_tron: TRON_WALLET })],
    activeOrgId: 'org_1',
    loading: false,
    saving: false,
    error: null,
    updateOrganization,
  })
  rerender(<OrganizationSettings />)
  expect(screen.getByText(TRON_WALLET)).toBeInTheDocument()
})

it('a 0x address on the TRON field is blocked client-side', () => {
  const updateOrganization = jest.fn()
  mountWith(updateOrganization)

  const input = typeIntoTronField(EVM_WALLET)
  fireEvent.keyDown(input, { key: 'Enter' })

  expect(updateOrganization).not.toHaveBeenCalled()
  expect(screen.getByText(/that’s an EVM address/i)).toBeInTheDocument()
})

it('a T-address on the EVM field is blocked client-side', () => {
  const updateOrganization = jest.fn()
  mountWith(updateOrganization)

  fireEvent.click(
    within(settlementSection()).getByRole('button', { name: /^edit$/i }),
  )
  const input = screen.getByPlaceholderText('0x…')
  fireEvent.change(input, { target: { value: TRON_WALLET } })
  fireEvent.keyDown(input, { key: 'Enter' })

  expect(updateOrganization).not.toHaveBeenCalled()
  expect(screen.getByText(/that’s a TRON address/i)).toBeInTheDocument()
})

it('the TRON zero address is blocked, even though its checksum is valid', () => {
  const updateOrganization = jest.fn()
  mountWith(updateOrganization)

  const input = typeIntoTronField(TRON_ZERO)
  fireEvent.keyDown(input, { key: 'Enter' })

  expect(updateOrganization).not.toHaveBeenCalled()
  expect(screen.getByText(/zero address/i)).toBeInTheDocument()
})

it('a bad checksum is caught here, not sent to the server', () => {
  const updateOrganization = jest.fn()
  mountWith(updateOrganization)

  // Shape-valid, one character off — the case a regex-only check would pass.
  const input = typeIntoTronField('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u')
  fireEvent.keyDown(input, { key: 'Enter' })

  expect(updateOrganization).not.toHaveBeenCalled()
  expect(screen.getByText(/enter a valid TRON address/i)).toBeInTheDocument()
})

it('setting one wallet leaves the other untouched', () => {
  const updateOrganization = jest.fn().mockResolvedValue(undefined)
  mountWith(updateOrganization)

  const input = typeIntoTronField(TRON_WALLET)
  fireEvent.keyDown(input, { key: 'Enter' })

  // Omitted means unchanged on the server, so the patch must carry exactly the
  // field being edited — never the other wallet, and never a null to clear it.
  const [, patch] = updateOrganization.mock.calls[0]
  expect(Object.keys(patch)).toEqual(['settlement_wallet_tron'])

  // The EVM address is still on screen, unchanged.
  expect(screen.getByText(EVM_WALLET)).toBeInTheDocument()
})

it('an org with no TRON wallet renders the field empty, not broken', () => {
  mountWith(jest.fn(), org({ settlement_wallet_tron: null }))

  // Empty, and deliberately not alarming: TRON is an extra rail.
  expect(screen.getByText('Not set')).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: /set tron wallet/i }),
  ).toBeInTheDocument()
  // The EVM half still renders normally beside it.
  expect(screen.getByText(EVM_WALLET)).toBeInTheDocument()
  expect(screen.getByText('TRON payout address')).toBeInTheDocument()
  expect(screen.getByText('EVM payout address')).toBeInTheDocument()
})

it('a viewer gets no way to edit either payout address', () => {
  mountWith(jest.fn(), org({ role: 'viewer', settlement_wallet_tron: TRON_WALLET }))

  expect(
    screen.queryByRole('button', { name: /set tron wallet/i }),
  ).not.toBeInTheDocument()
  expect(
    within(settlementSection()).queryByRole('button', { name: /^edit$/i }),
  ).not.toBeInTheDocument()
  // …but both addresses are still readable.
  expect(screen.getByText(TRON_WALLET)).toBeInTheDocument()
  expect(screen.getByText(EVM_WALLET)).toBeInTheDocument()
})
