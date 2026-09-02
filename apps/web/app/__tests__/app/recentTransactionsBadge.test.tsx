/**
 * The /app recent-settlements table's CHAIN badge.
 *
 * The badge lookup is a partial function over a `Record<string, …>`: a chain the
 * map does not know reads back `undefined`, and the very next line dereferences
 * `.bg` on it. Today that never happens, because `page.tsx` coerces every
 * unrecognised chain to the literal `'Base'` before the row ever arrives — so
 * the crash is masked by a bug rather than prevented by the code.
 *
 * Removing that coercion is the point of this branch, which makes the lookup's
 * totality load-bearing. This file pins it FIRST, so the commit that deletes the
 * coercion cannot be the commit that discovers the table throws.
 *
 * "Total" here has a second requirement beyond not throwing: an unknown chain
 * must not borrow a KNOWN network's colour. A row silently painted Base blue is
 * the same class of lie as a row labelled "Base" — it asserts a network we did
 * not identify. So the neutral badge is asserted to differ from Base's, not
 * merely to exist.
 */
import { render } from '@testing-library/react'

jest.mock('next-intl', () =>
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  require('@/test-utils/intlMock').intlModuleMock(),
)

import {
  CHAIN_BADGE,
  RecentTransactionsTable,
  type TxRow,
} from '@/components/app/RecentTransactionsTable'

const row = (chain: string): TxRow => ({
  id: 1,
  time: '18:08',
  type: 'transfer',
  amount: '$1,240',
  chain,
  status: 'confirmed',
})

/** The backend's honest fallback for a chain id it has no name for. */
const UNKNOWN_CHAIN = 'chain:3448148188'

/**
 * jsdom rewrites colours as it parses them (`#0052ff` reads back
 * `rgb(0, 82, 255)`), so a raw string compare against the source map fails on
 * notation rather than on value. Push both sides through the same parser and
 * compare what the DOM actually holds.
 */
const asDom = (property: 'color' | 'background', value: string): string => {
  const probe = document.createElement('span')
  probe.style[property] = value
  return probe.style[property]
}

describe('the chain badge is a total function', () => {
  it('renders a chain it does not recognise instead of throwing', () => {
    // RED before this commit: CHAIN_BADGE[UNKNOWN_CHAIN] is undefined and
    // `chainBadge.bg` throws "Cannot read properties of undefined".
    const { getByText } = render(
      <RecentTransactionsTable rows={[row(UNKNOWN_CHAIN)]} />,
    )
    expect(getByText(UNKNOWN_CHAIN)).toBeTruthy()
  })

  it('does not paint an unrecognised chain in a known network colour', () => {
    const { getByText } = render(
      <RecentTransactionsTable rows={[row(UNKNOWN_CHAIN)]} />,
    )
    const badge = getByText(UNKNOWN_CHAIN)
    const { color, background } = (badge as HTMLElement).style

    // Base's blue is the specific lie this guards against: it is what the
    // deleted coercion produced for every unidentified chain.
    expect(color).not.toBe(asDom('color', CHAIN_BADGE.Base.text))
    expect(background).not.toBe(asDom('background', CHAIN_BADGE.Base.bg))
    // A colour is still required — an unstyled badge would be a rendering bug
    // of its own, not a neutral one.
    expect(color).toBeTruthy()
  })

  it('leaves a recognised chain exactly as it was', () => {
    const { getByText } = render(<RecentTransactionsTable rows={[row('Base')]} />)
    const badge = getByText('Base') as HTMLElement
    expect(badge.style.color).toBe(asDom('color', CHAIN_BADGE.Base.text))
    expect(badge.style.background).toBe(asDom('background', CHAIN_BADGE.Base.bg))
  })
})
