/**
 * The browser talks to TronGrid without an API key, and that is a decision, not
 * an oversight.
 *
 * A TronGrid key in the client would have to arrive through a `NEXT_PUBLIC_*`
 * variable, and those are not secrets: Next inlines them into the JavaScript
 * every payer downloads, so "our" key would immediately be everybody's. The
 * backend holds `TRONGRID_API_KEY` and uses it from the poller, where it is
 * actually private.
 *
 * If keyless rate limits ever bite on mainnet, the fix is a backend proxy —
 * tracked as its own task — never a key in the bundle. This file is what makes
 * that a rule rather than a comment somebody deletes: it fails if a key ever
 * reaches the browser build, which no runtime test would catch because the flow
 * works perfectly well with a key in it.
 */
import fs from 'fs'
import path from 'path'

const WEB = path.resolve(__dirname, '../../..')
const CLIENT = path.join(WEB, 'lib/web3/tron/tronClient.ts')

/**
 * Comments stripped, so these assertions are about CODE.
 *
 * Without this the file fails on its own prose: tronClient.ts explains in a
 * docstring why it passes no `privateKey`, and this test names the exact
 * variable it forbids. A grep test that cannot survive being described is a
 * grep test people delete.
 */
function code(file: string): string {
  return fs
    .readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '')
}

/** Every source file that could plausibly carry client config. */
function sourceFiles(): string[] {
  const roots = ['lib', 'app', 'components', 'hooks']
  const found: string[] = []
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        // Tests name the things they forbid; scanning them is self-detection.
        if (['node_modules', '_archive', '__tests__'].includes(entry.name)) continue
        walk(full)
      } else if (/\.(ts|tsx|mjs|js)$/.test(entry.name)) {
        found.push(full)
      }
    }
  }
  roots.forEach((r) => walk(path.join(WEB, r)))
  return found
}

it('builds the TronWeb client with no key material of any kind', () => {
  const src = code(CLIENT)
  // `headers` is how a TronGrid key would be passed to the TronWeb constructor
  // (TRON-PRO-API-KEY), so its absence is the assertion.
  expect(src).not.toMatch(/headers\s*:/i)
  expect(src).not.toMatch(/TRON-PRO-API-KEY/i)
  expect(src).not.toMatch(/apiKey/i)
  // And no private key, ever — that would make the platform custodial.
  expect(src).not.toMatch(/privateKey/i)
})

it('never reads a TronGrid key from a NEXT_PUBLIC variable', () => {
  // The specific mistake this catches: someone hits a 403 from TronGrid on
  // mainnet, sees the backend has TRONGRID_API_KEY, and reaches for
  // NEXT_PUBLIC_TRONGRID_API_KEY because it is the quickest thing that works.
  const offenders: string[] = []
  for (const file of sourceFiles()) {
    const src = code(file)
    for (const match of src.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)) {
      if (/TRON|TRONGRID/i.test(match[0])) {
        offenders.push(`${path.relative(WEB, file)}: ${match[0]}`)
      }
    }
  }
  expect(offenders).toEqual([])
})

it('keeps the TronGrid key out of the web app’s environment surface', () => {
  const envExample = path.join(WEB, '.env.example')
  if (!fs.existsSync(envExample)) return
  const src = fs.readFileSync(envExample, 'utf8')
  // The backend's .env may hold TRONGRID_API_KEY; the web app's must not, or
  // the next person wires it into the bundle in good faith.
  expect(src).not.toMatch(/TRONGRID/i)
})
