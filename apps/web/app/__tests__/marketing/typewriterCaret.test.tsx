/**
 * Terminal-style block caret + subline reveal for the /vision hero typewriter.
 *
 * Caret contract: 0.55ch × 1em block, blinking while idle (initial delay and
 * after completion), SOLID while characters are typed, fades out ~2s after
 * completion and unmounts. Subline occupies reserved space from first paint
 * (visibility, never display) and becomes visible only after typing completes;
 * reduced-motion shows everything immediately with no caret.
 */
import { render, act, screen } from '@testing-library/react'
import TypewriterHeadline from '@/components/vision/TypewriterHeadline'

const TEXT = 'Hi!' // 3 chars → deterministic timeline with Math.random mocked
const SUBLINE = 'Why it settles directly.'

// Each per-char delay = 45 + 0.5*20 = 55ms exactly
beforeEach(() => {
  jest.useFakeTimers()
  jest.spyOn(Math, 'random').mockReturnValue(0.5)
})
afterEach(() => {
  jest.useRealTimers()
  jest.restoreAllMocks()
})

const renderHero = () =>
  render(<TypewriterHeadline text={TEXT} subline={SUBLINE} />)

const caret = () => document.querySelector('.rs-tw-caret')
const sublineEl = () => screen.getByText(SUBLINE)

const flushFontsReady = async () => {
  // jsdom has no document.fonts; the component falls back to Promise.resolve()
  await act(async () => {})
}

describe('block caret lifecycle', () => {
  it('is a 0.55ch × 1em block', async () => {
    renderHero()
    await flushFontsReady()
    const el = caret() as HTMLElement
    expect(el).not.toBeNull()
    expect(el.style.width).toBe('0.55ch')
    expect(el.style.height).toBe('1em')
  })

  it('blinks during the initial delay, goes solid while typing, blinks again when done', async () => {
    renderHero()
    await flushFontsReady()

    // initial ~300ms delay → idle → blinking
    expect(caret()!.className).toContain('rs-tw-caret--blink')

    // mid-typing (300ms delay + 1 char) → solid
    await act(async () => { jest.advanceTimersByTime(300 + 55) })
    expect(caret()).not.toBeNull()
    expect(caret()!.className).not.toContain('rs-tw-caret--blink')

    // finish typing (2 more chars + the completing tick) → idle again → blinking
    await act(async () => { jest.advanceTimersByTime(55 * 3) })
    expect(caret()!.className).toContain('rs-tw-caret--blink')

    // ~2s linger → fading
    await act(async () => { jest.advanceTimersByTime(2000) })
    expect(caret()!.className).toContain('rs-tw-caret--fading')

    // fade over → unmounted
    await act(async () => { jest.advanceTimersByTime(400) })
    expect(caret()).toBeNull()
  })
})

describe('subline reveal', () => {
  it('reserves space from first paint and becomes visible only after typing completes', async () => {
    renderHero()
    await flushFontsReady()

    // present in the DOM but invisible while the animation runs (space reserved)
    expect(sublineEl()).toBeInTheDocument()
    expect(sublineEl().style.visibility).toBe('hidden')

    await act(async () => { jest.advanceTimersByTime(300 + 55 * 4) })
    expect(sublineEl().style.visibility).toBe('visible')
  })
})

describe('prefers-reduced-motion', () => {
  it('shows headline + subline immediately, never a caret', async () => {
    const original = window.matchMedia
    window.matchMedia = ((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as typeof window.matchMedia

    try {
      renderHero()
      await flushFontsReady()
      await act(async () => { jest.advanceTimersByTime(5000) })

      expect(caret()).toBeNull()
      expect(sublineEl().style.visibility).not.toBe('hidden')
      const h1 = document.querySelector('h1')
      expect(h1?.textContent).toContain(TEXT)
    } finally {
      window.matchMedia = original
    }
  })
})
