/**
 * Blank-screen recovery — the contract for lib/hydrationRecovery.ts.
 *
 * WHAT IS BEING PINNED. A wedged React root (#329, thrown from `finishConcurrentRender`
 * inside the Scheduler, catchable by no error boundary) never commits, so `clearContainer`
 * never runs and the server HTML stays on screen. On /pay that HTML is an empty <body>, so
 * the payer sees white forever. Two layers rescue that, and BOTH of their thresholds came
 * out of 71 measured runs against the deployed build, not out of taste:
 *
 *   layer 1  the wedged FiberRoot fingerprint, held for a 1.5s dwell   → fires ~3.2s
 *   layer 2  a DOM backstop: nothing rendered at all by 12s
 *
 * The most important thing here is what must NOT fire. React recovers from #418/#423 on its
 * own — 33 of 35 instrumented runs painted after exactly that pair — so a fallback that
 * appeared on those would replace a working page with an error card. Case 2 is the one that
 * matters most and it is the one with the least evidence behind it (see the caveat block in
 * lib/hydrationRecovery.ts).
 *
 * WHY new Function AND NOT AN IMPORT: the recovery logic ships as an inline <head> script,
 * so it exists only as a source string. Evaluating that exact string is what makes these
 * tests cover the shipped bytes instead of a parallel re-implementation that could drift.
 *
 * SCOPE NOTE: this proves the state machine, not the integration. It does not prove that
 * Next puts the script in <head>, that CSP admits it, or that a real wedged root in a real
 * browser presents the fingerprint — the last of those is measurement, and it is in the D5
 * study (`results.md`), not here.
 */
import { HYDRATION_RECOVERY_SCRIPT } from '@/lib/hydrationRecovery'

const KEY = '__reactContainer$rstest'
const FALLBACK = '#rs-hydration-recovery'

const DWELL = 1500
const BACKSTOP = 12000

type Doc = Record<string, unknown>

/** A HostRoot fiber that has completed a render and never committed a child. */
const WEDGED = { child: null, stateNode: { finishedWork: {} } }
/** A healthy root: committed a child, nothing pending. */
const LIVE = { child: {}, stateNode: { finishedWork: null } }

const installRoot = (fiber: unknown) => {
  ;(document as unknown as Doc)[KEY] = fiber
}

const boot = () => {
  // The script is an IIFE; new Function evaluates it in global scope, which is where an
  // inline <head> script would run.
  new Function(HYDRATION_RECOVERY_SCRIPT)()
}

const fallback = () => document.querySelector(FALLBACK)

const reactError = (code: string) => {
  const err = new Error(
    `Minified React error #${code}; visit https://react.dev/errors/${code} for the full message`,
  )
  window.dispatchEvent(new ErrorEvent('error', { error: err, message: err.message }))
}

/** Something — anything — renders into <body>. */
const paint = () => {
  const el = document.createElement('div')
  el.textContent = 'checkout'
  document.body.appendChild(el)
}

beforeEach(() => {
  jest.useFakeTimers()
})

afterEach(() => {
  jest.clearAllTimers()
  jest.useRealTimers()
  delete (document as unknown as Doc)[KEY]
  document.body.innerHTML = ''
})

// ── 1. The wedged fingerprint, held past the dwell ───────────────────────────

it('reveals the fallback when the wedged fingerprint holds past the dwell', () => {
  installRoot(WEDGED)
  boot()
  reactError('329')

  // Fixture guard: nothing before the dwell has elapsed, or the test would pass for the
  // wrong reason (e.g. firing instantly and being credited to the dwell).
  jest.advanceTimersByTime(DWELL - 250)
  expect(fallback()).toBeNull()

  jest.advanceTimersByTime(DWELL)
  const el = fallback()
  expect(el).not.toBeNull()
  expect(el!.getAttribute('data-reason')).toBe('wedged')
  expect(el!.textContent).toContain('Reload')
})

it('fires layer 1 well before the backstop would have', () => {
  installRoot(WEDGED)
  boot()
  reactError('329')

  jest.advanceTimersByTime(4000)
  expect(fallback()!.getAttribute('data-reason')).toBe('wedged')
  expect(4000).toBeLessThan(BACKSTOP)
})

// ── 2. Suppression — a retry after the #329 ──────────────────────────────────
//
// The single most important negative case, and the least evidenced one. See the caveat
// block in lib/hydrationRecovery.ts before changing anything here.

it('does NOT reveal when a 418 arrives after the 329, even with the fingerprint held', () => {
  installRoot(WEDGED)
  boot()
  reactError('329')
  reactError('418') // React is retrying — this page is going to recover

  jest.advanceTimersByTime(BACKSTOP - 500)
  expect(fallback()).toBeNull()
})

it('does NOT reveal when a 423 arrives after the 329', () => {
  installRoot(WEDGED)
  boot()
  reactError('329')
  reactError('423')

  jest.advanceTimersByTime(BACKSTOP - 500)
  expect(fallback()).toBeNull()
})

it('still reveals when a 418 arrived BEFORE the 329 — that is not a retry', () => {
  installRoot(WEDGED)
  boot()
  reactError('418') // ordinary hydration mismatch, before anything fatal
  reactError('329')

  jest.advanceTimersByTime(DWELL + 500)
  expect(fallback()).not.toBeNull()
})

// ── 3/4. The recoverable pair alone must never trigger anything ──────────────

it('does NOT reveal on a 418 alone', () => {
  installRoot(LIVE)
  boot()
  reactError('418')

  jest.advanceTimersByTime(2400)
  paint()
  jest.advanceTimersByTime(BACKSTOP)
  expect(fallback()).toBeNull()
})

it('does NOT reveal on a 423 alone', () => {
  installRoot(LIVE)
  boot()
  reactError('423')

  jest.advanceTimersByTime(2400)
  paint()
  jest.advanceTimersByTime(BACKSTOP)
  expect(fallback()).toBeNull()
})

// ── 5. A slow but successful paint ───────────────────────────────────────────
//
// 2.9s is past the p95 of every arm measured (2806ms on the real TronCheckout tree) and
// comfortably past the layer-1 firing point, so this is the case that would break first if
// the dwell were ever shortened without the suppression.

it('does not trigger either layer when the page paints at 2.9s', () => {
  installRoot(LIVE)
  boot()

  jest.advanceTimersByTime(2900)
  expect(fallback()).toBeNull()
  paint()

  jest.advanceTimersByTime(BACKSTOP * 2)
  expect(fallback()).toBeNull()
})

// ── 6. The backstop ──────────────────────────────────────────────────────────

it('fires the backstop when nothing renders past N, with no fingerprint and no error', () => {
  installRoot(LIVE)
  boot()

  jest.advanceTimersByTime(BACKSTOP - 500)
  expect(fallback()).toBeNull()

  jest.advanceTimersByTime(1000)
  const el = fallback()
  expect(el).not.toBeNull()
  expect(el!.getAttribute('data-reason')).toBe('backstop')
})

// ── 7. Every container-key failure mode falls to layer 2, silently ───────────
//
// Absence of the key must never read as "not wedged, therefore healthy" — that would turn
// layer 1 off without turning anything on. `key-but-null` is not hypothetical: React's own
// unmarkContainerAsRoot sets the property to null (react-dom.development.js:11502).

describe('container-key failure modes', () => {
  const CASES: Array<[string, unknown]> = [
    ['no-key (React renamed the prefix, or never hydrated)', undefined],
    ['key-but-null (a real React state: unmarkContainerAsRoot)', null],
    ['no-stateNode', { child: null }],
    ['shape-changed (FiberRoot lost finishedWork)', { child: null, stateNode: { other: 1 } }],
    ['stateNode is a primitive', { child: null, stateNode: 7 }],
  ]

  it.each(CASES)('%s → layer 2 still fires, nothing throws', (_label, fiber) => {
    if (fiber === undefined) delete (document as unknown as Doc)[KEY]
    else installRoot(fiber)

    expect(() => {
      boot()
      reactError('329') // even a fatal must not coax layer 1 into firing without a reading
      jest.advanceTimersByTime(BACKSTOP - 500)
    }).not.toThrow()

    // Layer 1 is disabled — it has no reading to act on — so nothing yet.
    expect(fallback()).toBeNull()

    jest.advanceTimersByTime(1000)
    expect(fallback()!.getAttribute('data-reason')).toBe('backstop')
  })
})

// ── 8. /pay copy must not imply the payment failed ───────────────────────────

describe('payer-facing copy', () => {
  const withPath = (path: string, fn: () => void) => {
    window.history.pushState({}, '', path)
    try {
      fn()
    } finally {
      window.history.pushState({}, '', '/')
    }
  }

  it('on /pay, says nothing was signed or submitted', () => {
    withPath('/pay/pi_0000000000000000000000000000000000', () => {
      installRoot(WEDGED)
      boot()
      reactError('329')
      jest.advanceTimersByTime(DWELL + 500)

      const text = fallback()!.textContent ?? ''
      expect(text).toContain('No payment has been sent')
      expect(text).toContain('Reload')
      // Nothing has been signed or submitted at this point, so the copy must not read as a
      // failed payment.
      expect(text.toLowerCase()).not.toContain('failed')
      expect(text.toLowerCase()).not.toContain('error')
    })
  })

  it('off /pay, carries no payment claim at all', () => {
    installRoot(WEDGED)
    boot()
    reactError('329')
    jest.advanceTimersByTime(DWELL + 500)

    expect(fallback()!.textContent).not.toContain('No payment has been sent')
  })
})
