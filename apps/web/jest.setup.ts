import '@testing-library/jest-dom'

// jsdom lacks TextEncoder/TextDecoder, which viem (and other web3 libs) need at
// module load. Polyfill from Node's util so tests importing viem can run.
import { TextEncoder, TextDecoder } from 'util'
if (typeof globalThis.TextEncoder === 'undefined') {
  Object.assign(globalThis, { TextEncoder, TextDecoder })
}

// jsdom lacks matchMedia; the hero video and typewriter components read
// prefers-reduced-motion through it. Default: no reduction.
if (typeof window !== 'undefined' && typeof window.matchMedia === 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

// jsdom's HTMLMediaElement.play() is unimplemented (logs an error, returns
// undefined); the hero video calls it on mount and chains .catch().
if (typeof window !== 'undefined') {
  Object.defineProperty(window.HTMLMediaElement.prototype, 'play', {
    writable: true,
    value: () => Promise.resolve(),
  })
  Object.defineProperty(window.HTMLMediaElement.prototype, 'pause', {
    writable: true,
    value: () => {},
  })
}
