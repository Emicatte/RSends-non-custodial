// app/docs/_components/primitives.tsx
//
// Shared, brand-wired docs primitives for the RSends docs site.
// Extracted from the previous single-page ApiDocs hub so the new multi-page
// tree is self-contained. All styling uses the RSends Tailwind palette
// (text-terracotta, bg-ink, border-ink/…, font-mono = DM Mono) which reads
// from the --rs-* CSS variables in app/globals.css. No client hooks here —
// these render in server components.

import type { ReactNode } from 'react'

/* ── Inline mono code (field / value names), terracotta ──────── */
export function Code({ children }: { children: ReactNode }) {
  return <code className="font-mono text-[12.5px] text-terracotta">{children}</code>
}

/* ── Body paragraph ──────────────────────────────────────────── */
export function P({ children }: { children: ReactNode }) {
  return (
    <p className="my-3.5 font-display text-[14.5px] leading-relaxed text-ink/70">{children}</p>
  )
}

/* ── Larger intro paragraph under a page title ───────────────── */
export function Lead({ children }: { children: ReactNode }) {
  return (
    <p className="mb-2 mt-0 max-w-[640px] font-display text-[16px] leading-relaxed text-ink/60">
      {children}
    </p>
  )
}

/* ── Section headings ────────────────────────────────────────── */
export function H2({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2
      id={id}
      className="mb-3 mt-14 scroll-mt-24 border-t border-ink/[0.08] pt-12 font-display text-[24px] font-bold tracking-tight text-ink first:mt-0 first:border-t-0 first:pt-0"
    >
      {children}
    </h2>
  )
}

export function H3({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-2 mt-8 font-display text-[17px] font-semibold tracking-tight text-ink">
      {children}
    </h3>
  )
}

/* ── Brand link (terracotta) ─────────────────────────────────── */
export function A({ href, children }: { href: string; children: ReactNode }) {
  const external = /^https?:\/\//.test(href)
  return (
    <a
      href={href}
      {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
      className="font-medium text-terracotta underline decoration-terracotta/30 underline-offset-2 transition-colors hover:decoration-terracotta"
    >
      {children}
    </a>
  )
}

/* ── Bulleted list ───────────────────────────────────────────── */
export function UL({ children }: { children: ReactNode }) {
  return (
    <ul className="my-3.5 space-y-2 pl-1 font-display text-[14.5px] leading-relaxed text-ink/70">
      {children}
    </ul>
  )
}

export function LI({ children }: { children: ReactNode }) {
  return (
    <li className="relative pl-5 before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-terracotta/60">
      {children}
    </li>
  )
}

/* ── HTTP method badge ───────────────────────────────────────── */
const METHOD_BG: Record<string, string> = {
  GET:    '#3B82F6',
  POST:   '#C8512C',
  PUT:    '#FFB547',
  DELETE: '#FF4C6A',
}

export function Method({ m }: { m: string }) {
  return (
    <span
      className="inline-block rounded-md px-2 py-0.5 font-mono text-[10.5px] font-semibold tracking-wide text-white"
      style={{ background: METHOD_BG[m] ?? '#0A0A0A' }}
    >
      {m}
    </span>
  )
}

/* ── Endpoint row: method badge + monospace path ─────────────── */
export function Endpoint({ method, path }: { method: string; path: string }) {
  return (
    <div className="my-3 flex items-center gap-3 rounded-lg border border-ink/10 bg-surface px-3.5 py-2.5">
      <Method m={method} />
      <code className="font-mono text-[13px] text-ink">{path}</code>
    </div>
  )
}

/* ── Generic table with a thin border ────────────────────────── */
export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="my-5 overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th
                key={i}
                className="border-b border-ink/15 pb-2 pr-4 font-mono text-[10.5px] font-semibold uppercase tracking-wider text-ink/45"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              {r.map((cell, j) => (
                <td
                  key={j}
                  className="border-b border-ink/[0.07] py-2.5 pr-4 font-display text-[13px] leading-relaxed text-ink/75"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Page header: eyebrow + title + lead ─────────────────────── */
export function PageHeader({
  eyebrow,
  title,
  lead,
}: {
  eyebrow: string
  title: string
  lead: ReactNode
}) {
  return (
    <header className="mb-10">
      <p className="mb-3 font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-terracotta">
        {eyebrow}
      </p>
      <h1 className="mb-4 font-display text-[clamp(32px,5vw,46px)] font-bold leading-[1.1] tracking-tight text-ink">
        {title}
      </h1>
      <Lead>{lead}</Lead>
    </header>
  )
}

/* ── Prev / next page footer links ───────────────────────────── */
export function PageNav({
  prev,
  next,
}: {
  prev?: { href: string; label: string }
  next?: { href: string; label: string }
}) {
  return (
    <nav className="mt-16 flex items-stretch justify-between gap-4 border-t border-ink/[0.08] pt-8">
      {prev ? (
        <a
          href={prev.href}
          className="group flex flex-col gap-1 rounded-xl border border-ink/10 px-5 py-4 transition-colors hover:border-terracotta/40"
        >
          <span className="font-mono text-[10.5px] uppercase tracking-wider text-ink/40">
            ← Previous
          </span>
          <span className="font-display text-[14px] font-medium text-ink group-hover:text-terracotta">
            {prev.label}
          </span>
        </a>
      ) : (
        <span />
      )}
      {next ? (
        <a
          href={next.href}
          className="group flex flex-col items-end gap-1 rounded-xl border border-ink/10 px-5 py-4 text-right transition-colors hover:border-terracotta/40"
        >
          <span className="font-mono text-[10.5px] uppercase tracking-wider text-ink/40">
            Next →
          </span>
          <span className="font-display text-[14px] font-medium text-ink group-hover:text-terracotta">
            {next.label}
          </span>
        </a>
      ) : (
        <span />
      )}
    </nav>
  )
}
