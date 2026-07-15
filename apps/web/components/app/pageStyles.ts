/**
 * Shared spacing primitives for the /app dashboard surface.
 *
 * The rhythm: the page gutter is the only UNIFORM spacing; inside it, sections
 * sit 32px apart (`space-y-8` on the page `<main>`) while a heading stays
 * within 16px of its own body — unequal spacing is what groups related things.
 * All values live on the stock Tailwind 4px scale; never add a hand-typed px
 * spacing value or a `[Npx]` utility on this surface.
 */

/** Page container: centered column with the uniform gutter (20px sides on
 *  mobile, 32px from md up; 32px top; 80px bottom clears the mobile bottom
 *  nav). Compose as `className={`${appPage} space-y-8`}` when the page's
 *  sections should share the 32px rhythm. */
export const appPage = 'mx-auto w-full max-w-6xl px-5 pt-8 pb-20 md:px-8'

/** Standard card surface: one padding (20px) and one radius (12px) for every
 *  card on the dashboard. Full-bleed variants (e.g. a table card) should keep
 *  the border/radius/bg but not the padding. */
export const card = 'rounded-xl border border-[#e5e4e0] bg-surface p-5'
