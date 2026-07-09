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
  /** useReadContract results keyed by functionName */
  reads: Record<string, unknown>
  /** refetch spies keyed by functionName */
  refetch: Record<string, jest.Mock>
  approveWrite: WriteController
  payWrite: WriteController
  /** receipt per tx hash: status drives mined/reverted */
  receipts: Record<string, { status: 'success' | 'reverted' } | undefined>
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
    reads: {},
    refetch: {},
    approveWrite: makeWrite(),
    payWrite: makeWrite(),
    receipts: {},
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
    }),
    useReadContract: (config: { functionName: string; query?: { enabled?: boolean } }) => {
      const enabled = config.query?.enabled !== false
      const key = config.functionName
      if (!state.refetch[key]) state.refetch[key] = jest.fn()
      return {
        data: enabled ? state.reads[key] : undefined,
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
      return {
        data: receipt,
        isLoading: !!hash && !receipt,
        isSuccess: !!receipt,
      }
    },
    useSignTypedData: () => ({
      signTypedDataAsync: state.signTypedDataAsync,
      isPending: state.signPending,
      error: state.signError,
      reset: state.signReset,
    }),
    useBalance: ({ query }: { query?: { enabled?: boolean } } = {}) => ({
      data: query?.enabled === false ? undefined : state.nativeBalance,
    }),
  }
}
