/**
 * Shared wagmi mock for hook tests.
 *
 * Usage (per test file — the factory keeps the real ESM `wagmi` package from
 * ever loading under jest, and the module-level `wagmiState` singleton avoids
 * jest.mock hoisting/TDZ issues):
 *
 *   jest.mock('wagmi', () => {
 *     const m = require('@/test-utils/wagmiMock')
 *     return m.wagmiModuleMock(m.wagmiState)
 *   })
 *   import { resetWagmiState, wagmiState } from '@/test-utils/wagmiMock'
 *
 * Tests call `resetWagmiState(overrides)` in setup, mutate `wagmiState`,
 * then `rerender()`.
 *
 * Contract with the hook under test (useHostedCheckout):
 * - `useAccount` is the FIRST wagmi hook called per render (it resets the
 *   round-robin used to tell the two `useWriteContract` instances apart);
 * - each render calls `useWriteContract` exactly twice, approve first,
 *   pay second.
 * - `useReadContract` results are keyed by `functionName`.
 */

export interface WriteController {
  writeContract: jest.Mock
  data: `0x${string}` | undefined
  isPending: boolean
  error: unknown
  reset: jest.Mock
}

export interface WagmiState {
  address: `0x${string}` | undefined
  isConnected: boolean
  chainId: number
  switchChain: jest.Mock
  switchPending: boolean
  /** useSwitchChain ERROR — a wallet that refuses to go to this chain */
  switchError: unknown
  switchReset: jest.Mock
  disconnect: jest.Mock
  /** useReadContract results keyed by functionName */
  reads: Record<string, unknown>
  /** useReadContract ERRORS keyed by functionName (chain unreachable) */
  readErrors: Record<string, unknown>
  /** last args each read was issued with, keyed by functionName — proves a
   *  read was re-issued FOR a new address, not merely re-rendered */
  readArgs: Record<string, readonly unknown[] | undefined>
  /** refetch spies keyed by functionName */
  refetch: Record<string, jest.Mock>
  approveWrite: WriteController
  payWrite: WriteController
  /** receipt per tx hash: status drives mined/reverted */
  receipts: Record<string, { status: 'success' | 'reverted' } | undefined>
  /** receipt LOOKUP errors per tx hash: the chain cannot be read, so whether
   *  the tx succeeded is unknown — never the same thing as a revert */
  receiptErrors: Record<string, unknown>
  signTypedDataAsync: jest.Mock
  signPending: boolean
  signError: unknown
  signReset: jest.Mock
  /** useBalance (native path) */
  nativeBalance: { value: bigint } | undefined
}

function makeWrite(): WriteController {
  const controller: WriteController = {
    writeContract: jest.fn(),
    data: undefined,
    isPending: false,
    error: undefined,
    reset: jest.fn(() => {
      controller.data = undefined
      controller.isPending = false
      controller.error = undefined
    }),
  }
  return controller
}

export function createWagmiState(
  overrides: Partial<WagmiState> = {},
): WagmiState {
  return {
    address: '0x1111111111111111111111111111111111111111',
    isConnected: true,
    chainId: 84532,
    switchChain: jest.fn(),
    switchPending: false,
    switchError: undefined,
    // Mirrors the real mutation reset (and makeWrite's below): calling it
    // clears the error. It targets the singleton on purpose — resetWagmiState
    // Object.assigns a fresh object ONTO it, so a closure over the fresh
    // object would clear a copy nobody reads.
    switchReset: jest.fn(() => {
      wagmiState.switchError = undefined
    }),
    disconnect: jest.fn(),
    reads: {},
    readErrors: {},
    readArgs: {},
    refetch: {},
    approveWrite: makeWrite(),
    payWrite: makeWrite(),
    receipts: {},
    receiptErrors: {},
    signTypedDataAsync: jest.fn(),
    signPending: false,
    signError: undefined,
    signReset: jest.fn(),
    nativeBalance: undefined,
    ...overrides,
  }
}

/** Module-level singleton: safe to reference from a hoisted jest.mock factory. */
export const wagmiState: WagmiState = createWagmiState()

export function resetWagmiState(overrides: Partial<WagmiState> = {}): WagmiState {
  Object.assign(wagmiState, createWagmiState(overrides))
  return wagmiState
}

export function wagmiModuleMock(state: WagmiState) {
  let writeCallIndex = 0

  return {
    useAccount: () => {
      writeCallIndex = 0 // render boundary: reset the write round-robin
      return { address: state.address, isConnected: state.isConnected }
    },
    useChainId: () => state.chainId,
    useSwitchChain: () => ({
      switchChain: state.switchChain,
      isPending: state.switchPending,
      error: state.switchError,
      reset: state.switchReset,
    }),
    useDisconnect: () => ({ disconnect: state.disconnect }),
    useReadContract: (config: {
      functionName: string
      args?: readonly unknown[]
      query?: { enabled?: boolean }
    }) => {
      const enabled = config.query?.enabled !== false
      const key = config.functionName
      if (!state.refetch[key]) state.refetch[key] = jest.fn()
      if (enabled) state.readArgs[key] = config.args
      const error = enabled ? state.readErrors[key] : undefined
      return {
        data: enabled && !error ? state.reads[key] : undefined,
        error,
        refetch: state.refetch[key],
        isLoading: false,
      }
    },
    useWriteContract: () => {
      const controller =
        writeCallIndex++ === 0 ? state.approveWrite : state.payWrite
      return {
        writeContract: controller.writeContract,
        data: controller.data,
        isPending: controller.isPending,
        error: controller.error,
        reset: controller.reset,
      }
    },
    useWaitForTransactionReceipt: ({ hash }: { hash?: `0x${string}` }) => {
      const receipt = hash ? state.receipts[hash] : undefined
      const error = hash ? state.receiptErrors[hash] : undefined
      return {
        data: receipt,
        error,
        isLoading: !!hash && !receipt && !error,
        isSuccess: !!receipt,
      }
    },
    useSignTypedData: () => ({
      signTypedDataAsync: state.signTypedDataAsync,
      isPending: state.signPending,
      error: state.signError,
      reset: state.signReset,
    }),
    useBalance: ({ query }: { query?: { enabled?: boolean } } = {}) => {
      const enabled = query?.enabled !== false
      const error = enabled ? state.readErrors.nativeBalance : undefined
      return {
        data: enabled && !error ? state.nativeBalance : undefined,
        error,
      }
    },
  }
}
