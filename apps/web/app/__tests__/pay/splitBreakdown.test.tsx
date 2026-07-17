/**
 * SplitBreakdown — the payer-facing fan-out panel: every leg shows its
 * truncated address, share percentage, and the server-resolved amount (all
 * numeric/technical values in DM Mono via the Mono atom); the proportional
 * bar carries one segment per leg weighted by bps.
 */
import { render, screen } from '@testing-library/react'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())

import { SplitBreakdown } from '@/app/pay/[intentId]/_components/SummarySection'

const ALICE = '0x1111111111111111111111111111111111111111' as const
const BOB = '0x3333333333333333333333333333333333333333' as const

const SPLIT = {
  recipients: [ALICE, BOB] as `0x${string}`[],
  sharesBps: [7000, 3000],
  amounts: [70_000_000n, 30_000_000n],
}

it('renders one row per leg: truncated address, share %, resolved amount', () => {
  render(<SplitBreakdown split={SPLIT} currency="USDC" decimals={6} />)

  expect(screen.getByTestId('split-breakdown')).toBeInTheDocument()
  expect(screen.getByText('0x1111…1111')).toBeInTheDocument()
  expect(screen.getByText('0x3333…3333')).toBeInTheDocument()
  expect(screen.getByText('70%')).toBeInTheDocument()
  expect(screen.getByText('30%')).toBeInTheDocument()
  expect(screen.getByText(/70(\.0*)?\s*USDC/)).toBeInTheDocument()
  expect(screen.getByText(/30(\.0*)?\s*USDC/)).toBeInTheDocument()
})
