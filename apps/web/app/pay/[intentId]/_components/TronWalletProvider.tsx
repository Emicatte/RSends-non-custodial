'use client'

/**
 * TronWalletProvider — adapter lifecycle for the TRON checkout, and nothing else.
 *
 * MOUNTING. This provider is rendered only inside the TRON branch of
 * HostedCheckout, behind `dynamic(..., { ssr: false })`. The EVM branch never
 * loads it, so its bundle and its hydration are unchanged. Nothing here touches
 * `window.tronLink` or `window.tronWeb`: adapter construction and every probe
 * happen in effects, after mount, so the extension's injection cannot race
 * hydration — the failure mode this route has been bitten by before.
 *
 * WHY THE ADAPTERS ARE DRIVEN DIRECTLY, WITHOUT
 * `@tronweb3/tronwallet-adapter-react-hooks`. That package's `useWallet()`
 * declares `connect(): Promise<void>` — no options parameter — so it cannot
 * pass `{ onUri }`. On desktop we need that URI to render the QR in the
 * checkout's own style; without it the AppKit modal opens instead, which is a
 * second modal system beside RainbowKit on the same route and a look this
 * checkout deliberately does not have. The hook package would remove maybe
 * thirty lines of adapter bookkeeping and take the desktop design with it, so
 * it is not a dependency.
 *
 * DESKTOP AND MOBILE ARE GENUINELY DIFFERENT PATHS, and the split is the whole
 * of it: on desktop we take the URI and draw our own QR; on mobile we let the
 * adapter's modal run, because a QR on a phone is useless and the modal is what
 * resolves a wallet's deep link out of the WalletConnect registry. Taking
 * `onUri` on mobile would strip exactly the machinery that turns a `wc:` URI
 * into a wallet launch. (The adapter's `enableMobileDeepLink` option is
 * declared and documented but never read in its implementation, so there is no
 * supported way to keep the linking while replacing the UI.)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { Adapter } from '@tronweb3/tronwallet-abstract-adapter'

import { toCheckoutError, type TronCheckoutError } from '@/lib/web3/tron/tronErrors'
import type { TronNetworkConfig } from '@/lib/web3/tron/tronNetwork'
import type {
  TronConnectionStatus,
  TronWalletKind,
  TronWalletOption,
  TronWalletSession,
} from '@/lib/web3/tron/tronWallet'

/**
 * How long the TronLink adapter waits for the extension to inject before it
 * reports NotFound. 5s rather than the adapter's 30s default — a payer without
 * the extension should reach the WalletConnect path quickly.
 */
const TRONLINK_PROBE_TIMEOUT_MS = 5_000

/** Built lazily so the adapter packages stay out of the EVM route's graph. */
export interface TronAdapterSet {
  tronlink: Adapter
  walletconnect: Adapter | null
}

export type CreateAdapters = (
  network: TronNetworkConfig,
) => Promise<TronAdapterSet>

const defaultCreateAdapters: CreateAdapters = async (network) => {
  const [{ TronLinkAdapter }, wc] = await Promise.all([
    import('@tronweb3/tronwallet-adapter-tronlink'),
    import('@tronweb3/tronwallet-adapter-walletconnect'),
  ])

  const projectId = process.env.NEXT_PUBLIC_WC_PROJECT_ID
  return {
    tronlink: new TronLinkAdapter({
      // Bounds the readyState probe, so "is TronLink here?" always gets an
      // answer instead of sitting in `checking` forever on a browser where the
      // extension will never inject. Shorter than the adapter's 30s default:
      // this is a checkout, and a payer without the extension needs to be shown
      // the WalletConnect path quickly rather than watching a disabled button.
      checkTimeout: TRONLINK_PROBE_TIMEOUT_MS,
      // The page renders its own picker and its own install guidance, so the
      // adapter must not navigate away on its own when the wallet is missing.
      openUrlWhenWalletNotFound: false,
    }),
    // WalletConnect is offered only when a projectId is configured. Building
    // the adapter without one throws inside its own constructor, which would
    // take TronLink down with it — so it is omitted instead, and the picker
    // simply does not list it.
    walletconnect: projectId
      ? new wc.WalletConnectAdapter({
          // The chain id derived from the intent, never a display name and
          // never a default. WalletConnect will not establish a session that
          // fails the requested namespace, so this is what constrains the
          // approved chain on a path where it cannot be read back.
          network: network.chainId,
          options: {
            projectId,
            metadata: {
              name: 'RSends',
              description: 'RSends checkout',
              url: typeof window === 'undefined' ? '' : window.location.origin,
              icons: [],
            },
          },
        })
      : null,
  }
}

/**
 * Coarse pointer means "no hover, finger-sized targets" — a phone or tablet.
 * Read after mount, never during render, and never from the user-agent string.
 * Undefined until measured, so the UI can offer both affordances rather than
 * guess wrong on the first paint.
 */
function useIsTouchDevice(): boolean | undefined {
  const [coarse, setCoarse] = useState<boolean | undefined>(undefined)
  useEffect(() => {
    setCoarse(
      typeof window.matchMedia === 'function' &&
        window.matchMedia('(pointer: coarse)').matches,
    )
  }, [])
  return coarse
}

/**
 * The adapter's own probe result, mapped to what the picker shows.
 *
 * `Loading` MUST NOT collapse into "absent". The adapter starts in `Loading`
 * and resolves asynchronously — TronLink injects its provider after page load
 * and the adapter waits `checkTimeout` for it — so reading the state once at
 * construction and treating anything-but-Found as missing told a payer who has
 * the extension that they do not. `checking` renders as a disabled control; only
 * `NotFound`, which the adapter reports once its own timeout elapses, is
 * allowed to say the wallet is not there.
 */
function mapReadyState(state: string): 'installed' | 'absent' | 'checking' {
  if (state === 'Found') return 'installed'
  if (state === 'NotFound') return 'absent'
  return 'checking'
}

/** Only TronLink implements `network()`; the base Adapter type does not declare it. */
function readsNetwork(
  adapter: Adapter,
): adapter is Adapter & { network(): Promise<{ chainId: string }> } {
  return typeof (adapter as { network?: unknown }).network === 'function'
}

const TronWalletContext = createContext<TronWalletSession | null>(null)

export function useTronWallet(): TronWalletSession {
  const session = useContext(TronWalletContext)
  if (!session) {
    throw new Error('useTronWallet must be used inside a TronWalletProvider')
  }
  return session
}

export function TronWalletProvider({
  network,
  children,
  createAdapters = defaultCreateAdapters,
}: {
  network: TronNetworkConfig
  children: ReactNode
  createAdapters?: CreateAdapters
}) {
  const [adapters, setAdapters] = useState<TronAdapterSet | null>(null)
  const [status, setStatus] = useState<TronConnectionStatus>('idle')
  const [kind, setKind] = useState<TronWalletKind | null>(null)
  const [address, setAddress] = useState<string | null>(null)
  const [chainId, setChainId] = useState<string | null>(null)
  const [wcUri, setWcUri] = useState<string | null>(null)
  const [error, setError] = useState<TronCheckoutError | null>(null)
  const [tronlinkReady, setTronlinkReady] = useState<
    'checking' | 'installed' | 'absent'
  >('checking')
  const isTouch = useIsTouchDevice()

  // Guards every setState that follows an await, so a payer who closes the
  // page mid-connect does not get a React warning or a resurrected session.
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  // Adapters are constructed here — in an effect, after mount — and never
  // during render. This is the hydration guard: TronLink injects its provider
  // asynchronously, and probing for it while React is reconciling is what
  // produced the mismatch errors this route has seen before.
  useEffect(() => {
    let cancelled = false
    // Held so the cleanup can actually detach. Setting a `cancelled` flag
    // silences the setState but leaves the subscription attached for the life
    // of the adapter, which leaks one listener per mount.
    let detach: (() => void) | null = null

    createAdapters(network)
      .then((built) => {
        if (cancelled) return
        setAdapters(built)
        setTronlinkReady(mapReadyState(built.tronlink.readyState))

        const onReadyState = (state: string) => {
          if (!cancelled) setTronlinkReady(mapReadyState(state))
        }
        built.tronlink.on('readyStateChanged', onReadyState)
        detach = () => built.tronlink.off('readyStateChanged', onReadyState)
      })
      .catch((err) => {
        if (!cancelled) setError(toCheckoutError(err))
      })

    return () => {
      cancelled = true
      detach?.()
    }
  }, [network, createAdapters])

  const active = useMemo(() => {
    if (!adapters || !kind) return null
    return kind === 'tronlink' ? adapters.tronlink : adapters.walletconnect
  }, [adapters, kind])

  // Session events. An account switch changes who is paying and a chain change
  // can invalidate the whole preflight, so both are surfaced rather than
  // silently absorbed — the payment hook re-runs its checks off this state.
  useEffect(() => {
    if (!active) return
    const onAccounts = (next: string) => {
      if (!alive.current) return
      setAddress(next || null)
      if (!next) setStatus('idle')
    }
    const onChain = (data: { chainId: string }) => {
      if (alive.current) setChainId(data?.chainId ?? null)
    }
    const onDisconnect = () => {
      if (!alive.current) return
      setStatus('idle')
      setAddress(null)
      setChainId(null)
      setKind(null)
    }
    const onError = (err: unknown) => {
      if (alive.current) setError(toCheckoutError(err))
    }

    active.on('accountsChanged', onAccounts)
    active.on('chainChanged', onChain)
    active.on('disconnect', onDisconnect)
    active.on('error', onError)
    return () => {
      active.off('accountsChanged', onAccounts)
      active.off('chainChanged', onChain)
      active.off('disconnect', onDisconnect)
      active.off('error', onError)
    }
  }, [active])

  const connect = useCallback(
    async (which: TronWalletKind) => {
      if (!adapters) return
      const adapter =
        which === 'tronlink' ? adapters.tronlink : adapters.walletconnect
      if (!adapter) return

      setError(null)
      setWcUri(null)
      setKind(which)
      setStatus('connecting')
      try {
        // The desktop/mobile split. `onUri` skips the adapter's modal, which is
        // what we want on desktop (own QR, own styling) and exactly what we
        // must not do on mobile, where that modal performs the deep link.
        const wantsOwnQr = which === 'walletconnect' && isTouch === false
        await (wantsOwnQr
          ? (adapter as Adapter & {
              connect(o?: { onUri?: (uri: string) => void }): Promise<void>
            }).connect({
              onUri: (uri: string) => {
                if (alive.current) setWcUri(uri)
              },
            })
          : adapter.connect())

        if (!alive.current) return
        setAddress(adapter.address ?? null)
        setWcUri(null)

        // Read the chain back where the adapter can be asked. Where it cannot,
        // `chainId` stays null and `chainReadable` reports false — the
        // preflight must treat that as "constrained at request time", never as
        // "the chain checked out".
        if (readsNetwork(adapter)) {
          const net = await adapter.network()
          if (alive.current) setChainId(net?.chainId ?? null)
        } else {
          setChainId(null)
        }
        if (alive.current) setStatus('connected')
      } catch (err) {
        if (!alive.current) return
        setError(toCheckoutError(err))
        setStatus('idle')
        setKind(null)
        setWcUri(null)
      }
    },
    [adapters, isTouch],
  )

  const disconnect = useCallback(async () => {
    if (!active) return
    try {
      await active.disconnect()
    } catch (err) {
      // Never leave the page stuck on a connected screen because the wallet
      // refused to let go. TronLink cannot be disconnected by a DApp at all —
      // its own adapter says so — so the local session is what we clear, and
      // the copy says exactly that rather than claiming more.
      setError(toCheckoutError(err))
    } finally {
      if (alive.current) {
        setStatus('idle')
        setAddress(null)
        setChainId(null)
        setKind(null)
        setWcUri(null)
      }
    }
  }, [active])

  const switchChain = useCallback(
    async (target: string) => {
      if (!active) return
      try {
        await active.switchChain(target)
        if (readsNetwork(active)) {
          const net = await active.network()
          if (alive.current) setChainId(net?.chainId ?? null)
        }
      } catch (err) {
        // The WalletConnect path rejects here with a BARE STRING from the base
        // adapter, not an Error. toCheckoutError is what makes that survivable,
        // and it maps to wrong_network so the payer is told to switch in their
        // wallet instead of being shown a dead retry.
        if (alive.current) setError(toCheckoutError(err))
      }
    },
    [active],
  )

  const options = useMemo<TronWalletOption[]>(() => {
    const list: TronWalletOption[] = [
      { kind: 'tronlink', label: 'TronLink', availability: tronlinkReady },
    ]
    if (!adapters || adapters.walletconnect) {
      list.push({
        kind: 'walletconnect',
        label: 'WalletConnect',
        availability: 'universal',
      })
    }
    return list
  }, [adapters, tronlinkReady])

  const value = useMemo<TronWalletSession>(
    () => ({
      status,
      address,
      kind,
      chainId,
      chainReadable: active ? readsNetwork(active) : false,
      wcUri,
      error,
      options,
      adapter: status === 'connected' ? active : null,
      // Only claim a switch is possible where the adapter really implements
      // one. WalletConnect inherits a base method that always rejects, so
      // offering the button there would be offering a dead control.
      canSwitchChain: kind === 'tronlink',
      connect,
      disconnect,
      switchChain,
      clearError: () => setError(null),
    }),
    [
      status,
      address,
      kind,
      chainId,
      active,
      wcUri,
      error,
      options,
      connect,
      disconnect,
      switchChain,
    ],
  )

  return (
    <TronWalletContext.Provider value={value}>
      {children}
    </TronWalletContext.Provider>
  )
}
