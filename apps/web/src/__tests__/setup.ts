/**
 * src/__tests__/setup.ts — Test setup: mock providers, DOM APIs, wagmi helpers
 */

import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// ── Cleanup after each test ────────────────────────────────────
// NOTE: Only clean up DOM. Each test file must manage its own mock
// lifecycle in beforeEach to avoid vi.restoreAllMocks() breaking
// vi.mock() factory defaults.
afterEach(() => {
  cleanup();
});

// ── Mock localStorage ──────────────────────────────────────────
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: vi.fn((key: string) => store[key] ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key];
    }),
    clear: vi.fn(() => {
      store = {};
    }),
    get length() {
      return Object.keys(store).length;
    },
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
  };
})();
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

// ── Mock window.matchMedia ─────────────────────────────────────
Object.defineProperty(globalThis, 'matchMedia', {
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// ── Mock IntersectionObserver ──────────────────────────────────
class MockIntersectionObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
Object.defineProperty(globalThis, 'IntersectionObserver', {
  value: MockIntersectionObserver,
});

// ── Mock ResizeObserver ────────────────────────────────────────
class MockResizeObserver {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}
Object.defineProperty(globalThis, 'ResizeObserver', {
  value: MockResizeObserver,
});

// ── Wagmi test helpers (exported for hook/component tests) ─────

/** Default mock values for wagmi hooks */
export const defaultWagmiMocks = {
  useAccount: {
    address: undefined as `0x${string}` | undefined,
    chainId: 1,
    isConnected: false,
    isConnecting: false,
    connector: undefined as { id: string; name: string } | undefined,
  },
  useConnect: {
    connect: vi.fn(),
    connectors: [
      { id: 'injected', name: 'MetaMask' },
      { id: 'walletConnect', name: 'WalletConnect' },
    ],
    error: null as Error | null,
  },
  useDisconnect: {
    disconnect: vi.fn(),
  },
  useSwitchChain: {
    switchChain: vi.fn(),
  },
  useBalance: {
    data: undefined as
      | { value: bigint; formatted: string; symbol: string }
      | undefined,
    isLoading: false,
    refetch: vi.fn(),
  },
  useChainId: 1,
};

/** Create a connected wallet mock */
export function createConnectedMock(
  overrides?: Partial<typeof defaultWagmiMocks.useAccount>,
) {
  return {
    ...defaultWagmiMocks.useAccount,
    address: '0x1234567890abcdef1234567890abcdef12345678' as `0x${string}`,
    chainId: 1,
    isConnected: true,
    isConnecting: false,
    connector: { id: 'injected', name: 'MetaMask' },
    ...overrides,
  };
}
