/**
 * The vertical space around the device showcase, asserted as the declarations
 * that produce it rather than as measured pixels — jsdom lays nothing out, and a
 * pixel assertion on layout is brittle even where it can be made to work.
 *
 * Two separate gaps were confused in the original report, and it is worth
 * keeping them apart here:
 *
 *  - The one under the section header. Flat 64px on a desktop and 40px on a
 *    phone at every viewport size, and never the problem — but it is the gap a
 *    reader can point at, so it gets the blame.
 *  - The one ABOVE the header, between the hero and this section. `main` used to
 *    carry `min-height: 100dvh` around a hero that is a fixed ~750px tall, so
 *    every pixel of viewport beyond the content became empty background: 255px
 *    at 900px of viewport height, 555px at 1200px, 787px at 1440px. That is the
 *    "roughly a full viewport of empty background" that was reported, and it is
 *    invisible on a short laptop screen, which is why it was attributed to the
 *    section below it.
 */
import fs from 'node:fs'
import path from 'node:path'

import { act, render } from '@testing-library/react'

import DeviceShowcase from '@/components/landing/DeviceShowcase'

jest.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string) => `showcase.${key}`
    t.rich = (key: string) => `showcase.${key}`
    return t
  },
  useLocale: () => 'en',
  useFormatter: () => ({ dateTime: () => '', number: () => '' }),
}))

/** The component ships its CSS in a `<style>` literal; read it back from the DOM. */
async function showcaseStyles(): Promise<string> {
  let container: HTMLElement
  await act(async () => {
    ;({ container } = render(<DeviceShowcase />))
  })
  const style = container!.querySelector('style')
  expect(style).not.toBeNull()
  return style!.textContent ?? ''
}

describe('the gap between the section header and the frame', () => {
  it('is 64px on a desktop — intra-section space, not a section break', async () => {
    const css = await showcaseStyles()
    expect(css).toMatch(/\.rs-showcase-head\s*\{[^}]*margin:\s*0 auto 64px;/)
  })

  it('is 40px below 768px', async () => {
    const css = await showcaseStyles()
    const phone = /@media \(max-width: 767px\) \{([\s\S]*?)\n\s{8}\}/.exec(css)?.[1] ?? ''
    expect(phone).toMatch(/\.rs-showcase-head\s*\{\s*margin-bottom:\s*40px;\s*\}/)
  })

  it('adds no top padding or margin of its own to the stage', async () => {
    const css = await showcaseStyles()
    const stage = /\.rs-showcase-stage\s*\{([^}]*)\}/.exec(css)?.[1] ?? ''
    expect(stage).not.toMatch(/padding-top|margin-top/)
    expect(stage).toMatch(/margin:\s*0 auto;/)
  })
})

describe('the group contains what it displays', () => {
  it('reserves the phone caption instead of leaving it hanging outside the box', async () => {
    const css = await showcaseStyles()
    // On `.rs-showcase-browser`, not the stage: that is the element the phone
    // and its caption are anchored to (`position: relative`), so it is the box
    // whose height has to account for them. Reserving one level up left the
    // overhang between the browser's box and the stage's padding, where an
    // in-flow sibling would have landed on top of the caption.
    const browser = /\.rs-showcase-browser\s*\{([^}]*)\}/.exec(css)?.[1] ?? ''
    // Without the reservation the phone and its caption hang below every box in
    // the section, so anything downstream measures from a box that ends above
    // what the reader sees — and the only way to clear them was a fixed number
    // that could not scale with the zoom bands. Reserved here it holds in every
    // band by construction, and the anchors are offset by the same amount so the
    // devices do not move.
    expect(browser).toMatch(/padding-bottom:\s*\d+px/)
  })

  it('drops the reservation where the phone is in flow and needs none', async () => {
    const css = await showcaseStyles()
    const stacked = /@media \(max-width: 1023px\) \{([\s\S]*?)\n\s{8}\}/.exec(css)?.[1] ?? ''
    expect(stacked).toMatch(/\.rs-showcase-browser\s*\{[^}]*padding-bottom:\s*0/)
  })

  it('carries no dead height floor on the stage', async () => {
    // `minHeight: 620` never bound: the in-flow content measures 631px at 1440
    // and 782px at 390, at every viewport height. A floor that is never reached
    // reserves nothing and only reads as if it does.
    let container: HTMLElement
    await act(async () => {
      ;({ container } = render(<DeviceShowcase />))
    })
    const stage = container!.querySelector<HTMLElement>('[data-showcase-stage]')
    expect(stage).not.toBeNull()
    expect(stage!.style.minHeight).toBe('')
  })

  it('keeps the demo-data note inside the group it describes', async () => {
    let container: HTMLElement
    await act(async () => {
      ;({ container } = render(<DeviceShowcase />))
    })
    const stage = container!.querySelector('[data-showcase-stage]')!
    const note = Array.from(container!.querySelectorAll('p')).find((p) =>
      /showcase\.demoDataLabel|DEMO DATA/i.test(p.textContent ?? ''),
    )
    expect(note).toBeDefined()
    // It used to be a sibling of the stage, two levels above the captions and
    // outside the box they are positioned in — so it read as a stray line
    // between two sections rather than as a note on the mockup.
    expect(stage.contains(note!)).toBe(true)
  })

  it('spaces that note with a token, not with a number that clears an overhang', async () => {
    const css = await showcaseStyles()
    const source = fs.readFileSync(
      path.resolve(__dirname, '../../../components/landing/DeviceShowcase.tsx'),
      'utf8',
    )
    // The 128px was never spacing: it was clearance for the phone's unreserved
    // overhang, which is why it drifted across the zoom bands. C1 reserved the
    // overhang, so this can be what it always should have been.
    expect(source).not.toMatch(/margin:\s*'128px 0 0'/)
    expect(css + source).toMatch(/rs-showcase-note|demoData/i)
  })

  it('gives both captions an explicit line box', async () => {
    // Without one, the caption's height is whatever the font metrics say, and
    // the phone caption's `bottom` anchor is computed against it. The arithmetic
    // that positions a caption should not move when a font loads.
    const source = fs.readFileSync(
      path.resolve(__dirname, '../../../components/landing/DeviceShowcase.tsx'),
      'utf8',
    )
    const label = /function DeviceLabel[\s\S]*?\}\)\s*\{[\s\S]*?style=\{\{([\s\S]*?)\}\}/.exec(source)?.[1] ?? ''
    expect(label).toMatch(/lineHeight/)
  })
})

describe('the gap between the hero and this section', () => {
  const page = fs.readFileSync(
    path.resolve(__dirname, '../../[locale]/page.tsx'),
    'utf8',
  )
  const mainStyle = /<main className="main-content" style=\{\{([\s\S]*?)\}\}>/.exec(page)?.[1] ?? ''

  it('finds the landing page main element, so the assertions below mean something', () => {
    expect(mainStyle).toMatch(/paddingBottom/)
  })

  it('puts no viewport-height floor on a box that holds only the hero', () => {
    // A floor here does not make the hero fill the screen — the hero is a fixed
    // height — it pads dead background underneath it, one pixel per pixel of
    // viewport. Re-adding it re-opens the reported gap on tall displays only.
    expect(mainStyle).not.toMatch(/minHeight/)
    expect(mainStyle).not.toMatch(/100dvh|100vh/)
  })
})
