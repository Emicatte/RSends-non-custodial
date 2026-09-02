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
    const stage = /\.rs-showcase-stage\s*\{([^}]*)\}/.exec(css)?.[1] ?? ''
    // The phone and its caption are `position: absolute` and anchored BELOW the
    // stage's content box (`bottom: -50px` and `bottom: -86px`), so the stage's
    // height accounts for neither. Everything downstream then measures from a
    // box that ends above what the reader can see, and the only way to clear the
    // overhang was a fixed number that could not scale with it. Reserve it here
    // and the relationship holds in every zoom band by construction.
    expect(stage).toMatch(/padding-bottom:\s*\d+px/)
  })

  it('drops the reservation where the phone is in flow and needs none', async () => {
    const css = await showcaseStyles()
    const stacked = /@media \(max-width: 1023px\) \{([\s\S]*?)\n\s{8}\}/.exec(css)?.[1] ?? ''
    expect(stacked).toMatch(/\.rs-showcase-stage\s*\{[^}]*padding-bottom:\s*0/)
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
