/**
 * The wallet provider owns connection and session, and these are the
 * behaviours that are easy to get wrong and invisible until a real payer hits
 * them.
 *
 * The adapters are injected, so no real wallet package is loaded and nothing
 * touches window.tronLink — which is also the point of the production code:
 * every probe happens in an effect, after mount.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  TronWalletProvider,
  useTronWallet,
  type CreateAdapters,
} from '@/app/pay/[intentId]/_components/TronWalletProvider'
import { tronNetworkFor } from '@/lib/web3/tron/tronNetwork'

const NILE = tronNetworkFor('tron_nile')!
const PAYER = 'TWd4WrZ9wn84f5x1hZhL4DHvk738ns5jwb'

type Listener = (...args: never[]) => void

function makeAdapter(
  name: string,
  opts: {
    /** Only TronLink has one. Omitting it models WalletConnect exactly. */
    network?: () => Promise<{ chainId: string }>
    connect?: (o?: { onUri?: (uri: string) => void }) => Promise<void>
    switchChain?: (chainId: string) => Promise<void>
    readyState?: string
  } = {},
) {
  const listeners = new Map<string, Set<Listener>>()
  const adapter: Record<string, unknown> = {
    name,
    address: null as string | null,
    readyState: opts.readyState ?? 'Found',
    connect:
      opts.connect ??
      (async () => {
        adapter.address = PAYER
      }),
    disconnect: async () => {
      adapter.address = null
    },
    signTransaction: async (tx: unknown) => tx,
    on: (event: string, fn: Listener) => {
      if (!listeners.has(event)) listeners.set(event, new Set())
      listeners.get(event)!.add(fn)
    },
    off: (event: string, fn: Listener) => listeners.get(event)?.delete(fn),
    emit: (event: string, ...args: never[]) =>
      listeners.get(event)?.forEach((fn) => fn(...args)),
  }
  if (opts.network) adapter.network = opts.network
  if (opts.switchChain) adapter.switchChain = opts.switchChain
  return adapter
}

function Probe() {
  const w = useTronWallet()
  return (
    <div>
      <span data-testid="status">{w.status}</span>
      <span data-testid="address">{w.address ?? '-'}</span>
      <span data-testid="chainId">{w.chainId ?? '-'}</span>
      <span data-testid="chainReadable">{String(w.chainReadable)}</span>
      <span data-testid="canSwitch">{String(w.canSwitchChain)}</span>
      <span data-testid="wcUri">{w.wcUri ?? '-'}</span>
      <span data-testid="error">{w.error?.kind ?? '-'}</span>
      <span data-testid="options">
        {w.options.map((o) => `${o.kind}:${o.availability}`).join(',')}
      </span>
      <button onClick={() => void w.connect('tronlink')}>tronlink</button>
      <button onClick={() => void w.connect('walletconnect')}>walletconnect</button>
      <button onClick={() => void w.switchChain(NILE.chainId)}>switch</button>
      <button onClick={() => void w.disconnect()}>disconnect</button>
    </div>
  )
}

function renderProvider(create: CreateAdapters) {
  return render(
    <TronWalletProvider network={NILE} createAdapters={create}>
      <Probe />
    </TronWalletProvider>,
  )
}

/**
 * Desktop unless a test says otherwise: `pointer: coarse` decides the path.
 *
 * Assigned rather than redefined — jest.setup.ts already installs a matchMedia
 * stub as `writable: true` without `configurable`, so defineProperty throws
 * here while a plain assignment is fine.
 */
function setPointer(coarse: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('coarse') ? coarse : false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => setPointer(false))

it('connects TronLink and reads the chain back', async () => {
  const tronlink = makeAdapter('TronLink', {
    network: async () => ({ chainId: NILE.chainId }),
    switchChain: async () => {},
  })
  renderProvider(async () => ({ tronlink: tronlink as never, walletconnect: null }))

  await userEvent.click(await screen.findByText('tronlink'))

  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
  expect(screen.getByTestId('address')).toHaveTextContent(PAYER)
  expect(screen.getByTestId('chainId')).toHaveTextContent(NILE.chainId)
  // TronLink can be asked, and can switch.
  expect(screen.getByTestId('chainReadable')).toHaveTextContent('true')
  expect(screen.getByTestId('canSwitch')).toHaveTextContent('true')
})

it('reports a WalletConnect session as unreadable rather than as agreeing', async () => {
  // WalletConnectAdapter has no network() method at all. The distinction this
  // asserts is the safety-critical one: a null chainId must never read as "the
  // chain checked out". chainReadable false says the guarantee came from the
  // requested namespace at session time, not from a read-back.
  const wc = makeAdapter('WalletConnect')
  renderProvider(async () => ({
    tronlink: makeAdapter('TronLink') as never,
    walletconnect: wc as never,
  }))

  await userEvent.click(await screen.findByText('walletconnect'))

  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
  expect(screen.getByTestId('chainId')).toHaveTextContent('-')
  expect(screen.getByTestId('chainReadable')).toHaveTextContent('false')
  // And no dead switch button is offered on a path whose switchChain rejects.
  expect(screen.getByTestId('canSwitch')).toHaveTextContent('false')
})

it('takes the WalletConnect URI for its own QR on desktop, and drops it once connected', async () => {
  setPointer(false)
  // A real connect() stays pending until the wallet approves — that pending
  // window IS when the QR is on screen — so the fake has to model it rather
  // than resolve instantly.
  let approve!: () => void
  const approved = new Promise<void>((resolve) => {
    approve = resolve
  })
  const wc = makeAdapter('WalletConnect', {
    connect: async (o) => {
      o?.onUri?.('wc:topic@2?relay-protocol=irn&symKey=abc')
      await approved
      wc.address = PAYER
    },
  })
  renderProvider(async () => ({
    tronlink: makeAdapter('TronLink') as never,
    walletconnect: wc as never,
  }))

  await userEvent.click(await screen.findByText('walletconnect'))

  // The URI reaches the page while the session is pending, so the checkout can
  // draw the QR itself instead of opening the adapter's modal beside
  // RainbowKit.
  await waitFor(() =>
    expect(screen.getByTestId('wcUri')).toHaveTextContent('wc:topic@2'),
  )
  expect(screen.getByTestId('status')).toHaveTextContent('connecting')

  await act(async () => {
    approve()
    await approved
  })

  // And it is dropped on success: a stale QR next to a connected wallet would
  // invite a second, orphaned session.
  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))
  expect(screen.getByTestId('wcUri')).toHaveTextContent('-')
})

it('lets the adapter modal run on a touch device, and asks for no URI', async () => {
  setPointer(true)
  let sawOptions: unknown = 'never called'
  const wc = makeAdapter('WalletConnect', {
    connect: async (o) => {
      sawOptions = o
    },
  })
  renderProvider(async () => ({
    tronlink: makeAdapter('TronLink') as never,
    walletconnect: wc as never,
  }))

  await userEvent.click(await screen.findByText('walletconnect'))

  // A QR is useless on a phone, and onUri would skip the modal that performs
  // the wallet deep link. So connect() is called with nothing.
  await waitFor(() => expect(sawOptions).toBeUndefined())
  expect(screen.getByTestId('wcUri')).toHaveTextContent('-')
})

it('turns the bare-string switchChain rejection into wrong_network', async () => {
  // The literal value the base Adapter rejects with. A naive err.message read
  // would throw here, inside a click handler, during a payment.
  const tronlink = makeAdapter('TronLink', {
    network: async () => ({ chainId: '0x2b6653dc' }),
    switchChain: async () => {
      throw "The current wallet doesn't support switch chain."
    },
  })
  renderProvider(async () => ({ tronlink: tronlink as never, walletconnect: null }))

  await userEvent.click(await screen.findByText('tronlink'))
  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))

  await userEvent.click(screen.getByText('switch'))

  await waitFor(() =>
    expect(screen.getByTestId('error')).toHaveTextContent('wrong_network'),
  )
  // Still connected: a refused switch is not a lost session.
  expect(screen.getByTestId('status')).toHaveTextContent('connected')
})

it('surfaces an account switch as a new payer', async () => {
  const tronlink = makeAdapter('TronLink', {
    network: async () => ({ chainId: NILE.chainId }),
  })
  renderProvider(async () => ({ tronlink: tronlink as never, walletconnect: null }))

  await userEvent.click(await screen.findByText('tronlink'))
  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))

  const OTHER = 'TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE'
  act(() => {
    ;(tronlink.emit as (e: string, ...a: unknown[]) => void)('accountsChanged', OTHER)
  })

  // Who is paying changed. The preflight keys off this, so it must not be
  // silently absorbed.
  await waitFor(() => expect(screen.getByTestId('address')).toHaveTextContent(OTHER))
})

it('drops the session when the wallet disconnects underneath us', async () => {
  const tronlink = makeAdapter('TronLink', {
    network: async () => ({ chainId: NILE.chainId }),
  })
  renderProvider(async () => ({ tronlink: tronlink as never, walletconnect: null }))

  await userEvent.click(await screen.findByText('tronlink'))
  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('connected'))

  act(() => {
    ;(tronlink.emit as (e: string, ...a: unknown[]) => void)('disconnect')
  })

  await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('idle'))
  expect(screen.getByTestId('address')).toHaveTextContent('-')
})

it('offers WalletConnect even when TronLink is absent', async () => {
  const tronlink = makeAdapter('TronLink', { readyState: 'NotFound' })
  renderProvider(async () => ({
    tronlink: tronlink as never,
    walletconnect: makeAdapter('WalletConnect') as never,
  }))

  // A payer without the extension must never see a dead end — the absent
  // wallet is reported as absent AND the universal path stays on offer.
  await waitFor(() =>
    expect(screen.getByTestId('options')).toHaveTextContent(
      'tronlink:absent,walletconnect:universal',
    ),
  )
})

it('omits WalletConnect entirely when no projectId configured it', async () => {
  renderProvider(async () => ({
    tronlink: makeAdapter('TronLink') as never,
    walletconnect: null,
  }))
  await waitFor(() =>
    expect(screen.getByTestId('options')).toHaveTextContent('tronlink:installed'),
  )
  expect(screen.getByTestId('options')).not.toHaveTextContent('walletconnect')
})

it('reports a failed connection without leaving the UI stuck on connecting', async () => {
  const tronlink = makeAdapter('TronLink', {
    connect: async () => {
      throw new Error('fetch failed')
    },
  })
  renderProvider(async () => ({ tronlink: tronlink as never, walletconnect: null }))

  await userEvent.click(await screen.findByText('tronlink'))

  await waitFor(() =>
    expect(screen.getByTestId('error')).toHaveTextContent('network_error'),
  )
  expect(screen.getByTestId('status')).toHaveTextContent('idle')
})
