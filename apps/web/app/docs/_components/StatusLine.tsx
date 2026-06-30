// app/docs/_components/StatusLine.tsx
//
// Site-wide honesty banner, shown on every docs page via DocsLayout.
// Non-negotiable posture: private beta · Base Sepolia testnet (test tokens,
// no real value) · USDC only currently · mainnet rolls out per jurisdiction.
// Nothing here may imply production / mainnet / licensing.

const ITEMS = [
  'Private beta',
  'Base Sepolia testnet — test tokens, no real value',
  'USDC only currently',
  'Mainnet rolls out per jurisdiction',
] as const

export function StatusLine() {
  return (
    <div className="mb-10 flex flex-wrap items-center gap-x-2.5 gap-y-1.5 rounded-lg border border-terracotta/20 bg-wash/40 px-4 py-2.5">
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-terracotta" aria-hidden />
        <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-terracotta">
          Status
        </span>
      </span>
      {ITEMS.map((item, i) => (
        <span key={i} className="flex items-center gap-2.5">
          {i > 0 && <span className="text-ink/20" aria-hidden>·</span>}
          <span className="font-display text-[12px] text-ink/60">{item}</span>
        </span>
      ))}
    </div>
  )
}
