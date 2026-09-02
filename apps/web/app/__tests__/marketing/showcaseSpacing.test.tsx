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

  it('adds nothing else between the subheading and the frame', async () => {
    const css = await showcaseStyles()
    // The stage is the frame's own box: no top padding or margin of its own, so
    // the 64px above is the whole gap and there is one number to change.
    expect(css).toMatch(
      /\.rs-showcase-stage\s*\{\s*position:\s*relative;\s*margin:\s*0 auto;\s*max-width:\s*1356px;\s*\}/,
    )
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
