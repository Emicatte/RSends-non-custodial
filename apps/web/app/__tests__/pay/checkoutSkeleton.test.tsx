/**
 * CheckoutSkeleton + CheckoutFrame: the skeleton reserves the final layout
 * (both render the SAME frame slots — the zero-shift proxy), pulses opacity
 * only, and surfaces the slow-retry notice.
 */
import { render, screen } from '@testing-library/react'

jest.mock('next-intl', () => require('@/test-utils/intlMock').intlModuleMock())

import { CheckoutFrame } from '@/app/pay/[intentId]/_components/CheckoutFrame'
import { CheckoutSkeleton } from '@/app/pay/[intentId]/_components/CheckoutSkeleton'
import { NetworkErrorView } from '@/app/pay/[intentId]/_components/StatusViews'

const FRAME_SLOTS = [
  'frame-header',
  'frame-amount',
  'frame-summary',
  'frame-action',
  'frame-notice',
  'frame-footer',
]

describe('CheckoutSkeleton', () => {
  it('renders every frame slot the loaded view uses (reserved layout)', () => {
    render(<CheckoutSkeleton slow={false} />)
    for (const slot of FRAME_SLOTS) {
      expect(screen.getByTestId(slot)).toBeInTheDocument()
    }
  })

  it('shows the slow-retry notice only when slow', () => {
    const { rerender } = render(<CheckoutSkeleton slow={false} />)
    expect(screen.queryByText('Taking longer than usual. Retrying.')).toBeNull()

    rerender(<CheckoutSkeleton slow />)
    expect(
      screen.getByText('Taking longer than usual. Retrying.'),
    ).toBeInTheDocument()
  })
})

describe('CheckoutFrame', () => {
  it('exposes the same slot structure for live content', () => {
    render(
      <CheckoutFrame
        header={<span>h</span>}
        amount={<span>a</span>}
        summary={<span>s</span>}
        action={<span>x</span>}
        notice={<span>n</span>}
        footer={<span>f</span>}
      />,
    )
    for (const slot of FRAME_SLOTS) {
      expect(screen.getByTestId(slot)).toBeInTheDocument()
    }
  })

  it('reserves a minimum action height (touch target) and notice line', () => {
    render(
      <CheckoutFrame
        header={null}
        amount={null}
        summary={null}
        action={null}
        notice={null}
        footer={null}
      />,
    )
    expect(screen.getByTestId('frame-action')).toHaveStyle({ minHeight: '48px' })
    expect(screen.getByTestId('frame-notice')).toHaveStyle({ minHeight: '18px' })
  })
})

describe('NetworkErrorView', () => {
  it('renders every frame slot, so an outage never shifts or blanks the card', () => {
    render(<NetworkErrorView onRetry={jest.fn()} detail={null} />)
    for (const slot of FRAME_SLOTS) {
      expect(screen.getByTestId(slot)).toBeInTheDocument()
    }
  })

  it('says the payment service is unreachable and charges nothing', () => {
    render(<NetworkErrorView onRetry={jest.fn()} detail={null} />)
    expect(
      screen.getByText(
        'We cannot reach the payment service right now. Nothing has been charged.',
      ),
    ).toBeInTheDocument()
  })

  it('offers a working manual retry', () => {
    const onRetry = jest.fn()
    render(<NetworkErrorView onRetry={onRetry} detail={null} />)
    screen.getByRole('button', { name: 'Try again' }).click()
    expect(onRetry).toHaveBeenCalled()
  })

  it('keeps the raw error out of the headline, in a collapsed detail', () => {
    render(<NetworkErrorView onRetry={jest.fn()} detail="HTTP 503 -32011" />)
    const details = screen.getByText('Technical details')
    expect(details).toBeInTheDocument()
    // Collapsed by default: the payer sees plain language, support can expand.
    expect(details.closest('details')).not.toHaveAttribute('open')
    expect(screen.getByText('HTTP 503 -32011')).toBeInTheDocument()
  })

  it('omits the detail block entirely when there is nothing to show', () => {
    render(<NetworkErrorView onRetry={jest.fn()} detail={null} />)
    expect(screen.queryByText('Technical details')).toBeNull()
  })
})
