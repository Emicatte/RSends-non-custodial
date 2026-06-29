import '@testing-library/jest-dom'

// jsdom lacks TextEncoder/TextDecoder, which viem (and other web3 libs) need at
// module load. Polyfill from Node's util so tests importing viem can run.
import { TextEncoder, TextDecoder } from 'util'
if (typeof globalThis.TextEncoder === 'undefined') {
  Object.assign(globalThis, { TextEncoder, TextDecoder })
}
