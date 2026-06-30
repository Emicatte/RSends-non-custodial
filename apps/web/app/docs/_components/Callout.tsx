import type { ReactNode } from 'react'

type Variant = 'info' | 'warn' | 'chain'

type Props = {
  variant?: Variant
  title?: string
  children: ReactNode
}

const STYLES: Record<Variant, { bar: string; bg: string }> = {
  info:  { bar: 'bg-terracotta', bg: 'bg-wash/40' },
  warn:  { bar: 'bg-ink',        bg: 'bg-ink/[0.03]' },
  chain: { bar: 'bg-terracotta', bg: 'bg-terracotta/[0.06]' },
}

/**
 * Editorial callout with a left side-bar. Used for the "always verify the
 * signature" rule, "shown once" warnings, and the "verify on-chain yourself"
 * note. `chain` is the trustless / on-chain-proof variant.
 */
export function Callout({ variant = 'info', title, children }: Props) {
  const s = STYLES[variant]
  return (
    <div className={`my-5 flex gap-0 overflow-hidden rounded-lg ${s.bg}`}>
      <div className={`w-1 shrink-0 ${s.bar}`} aria-hidden />
      <div className="px-4 py-3.5">
        {title && (
          <p className="mb-1 font-display text-[13px] font-semibold text-ink">{title}</p>
        )}
        <div className="font-display text-[13.5px] leading-relaxed text-ink/70">{children}</div>
      </div>
    </div>
  )
}
