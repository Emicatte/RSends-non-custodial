/**
 * lib/web3/tron/tronWallet — the wallet abstraction the checkout programs
 * against. CONNECTION AND SESSION ONLY.
 *
 * The deliberate boundary: nothing here builds, signs or broadcasts a
 * transaction. That lives in `tronTransfer.ts`, in one implementation shared by
 * every wallet. This module owns only the things that genuinely differ between
 * TronLink and WalletConnect — how a session is established, whether the chain
 * can be read back, and whether it can be switched — and it exposes the result
 * uniformly so the payment hook never branches on which wallet is connected.
 */

import type { Adapter } from '@tronweb3/tronwallet-abstract-adapter'

import type { TronCheckoutError } from './tronErrors'

export type TronWalletKind = 'tronlink' | 'walletconnect'

export type TronConnectionStatus = 'idle' | 'connecting' | 'connected'

export interface TronWalletOption {
  kind: TronWalletKind
  label: string
  /**
   * `installed`   — the extension is present and can be connected right now.
   * `absent`      — TronLink is not installed; offer the install page AND
   *                 WalletConnect, never a dead button.
   * `universal`   — WalletConnect, which needs nothing installed.
   * `checking`    — the adapter has not finished its readyState probe. Rendered
   *                 as a disabled control rather than as absent, so a slow
   *                 probe never tells a payer their wallet is missing.
   */
  availability: 'installed' | 'absent' | 'universal' | 'checking'
}

export interface TronWalletSession {
  status: TronConnectionStatus
  /** base58 payer address, exactly as the wallet reports it. Never folded. */
  address: string | null
  kind: TronWalletKind | null
  /**
   * The chain id the connected wallet reports, or null when this adapter
   * cannot be asked.
   *
   * Null is NOT "no opinion" and must never be treated as a pass. Only
   * TronLink implements `network()`; `WalletConnectAdapter` has no such method,
   * so on that path the chain is constrained at session-request time instead
   * (the adapter is constructed with the intent's chain id, and WalletConnect
   * will not establish a session that fails the requested namespace).
   * `chainReadable` says which of the two guarantees is in force, so the
   * preflight can be explicit rather than reading a null as agreement.
   */
  chainId: string | null
  chainReadable: boolean
  /**
   * The `wc:` URI for a desktop QR, when the connection is being made without
   * the adapter's own modal. Null on mobile, where the modal runs and performs
   * the wallet deep link itself.
   */
  wcUri: string | null
  error: TronCheckoutError | null
  options: TronWalletOption[]
  /** The connected adapter, for `tronTransfer.payWithWallet`. Null until connected. */
  adapter: Adapter | null
  /** True only when the connected adapter can actually switch chains. */
  canSwitchChain: boolean
  connect(kind: TronWalletKind): Promise<void>
  disconnect(): Promise<void>
  switchChain(chainId: string): Promise<void>
  clearError(): void
}
