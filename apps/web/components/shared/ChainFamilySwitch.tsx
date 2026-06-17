/**
 * components/shared/ChainFamilySwitch.tsx — Segmented pill per switchare
 * tra EVM / Solana / Tron.
 */
'use client'

import type { ChainFamily } from '../../lib/chain-adapters/types'

const FAMILIES: { key: ChainFamily; label: string; dot: string }[] = [
  { key: 'evm',    label: 'EVM', dot: '#378ADD' },
  { key: 'solana', label: 'SOL', dot: '#7F77DD' },
  { key: 'tron',   label: 'TRX', dot: '#E24B4A' },
]

export function ChainFamilySwitch({
  active,
  onSelect,
  connections,
}: {
  active: ChainFamily
  onSelect: (f: ChainFamily) => void
  connections: Record<ChainFamily, { isConnected: boolean }>
}) {
  return (
    <div className="flex items-center gap-1">
      {FAMILIES.map(f => {
        const isActive = active === f.key
        const isConn = connections[f.key]?.isConnected
        const isLocked = f.key === 'solana'
        return (
          <button
            key={f.key}
            onClick={isLocked ? undefined : () => onSelect(f.key)}
            aria-current={isActive ? 'true' : undefined}
            aria-disabled={isLocked || undefined}
            title={isLocked ? 'Coming soon' : undefined}
            className={[
              'flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors font-display',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-black/20 focus-visible:ring-offset-0',
              isActive
                ? 'bg-neutral-100 text-black font-medium'
                : 'text-black/55 hover:text-black hover:bg-black/[0.03]',
              !isActive && !isConn ? 'opacity-70' : '',
              isLocked ? 'pointer-events-none opacity-60' : '',
            ].join(' ')}
          >
            <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: f.dot }} />
            {f.label}
            {isLocked && (
              <span
                className="ml-1 inline-block rounded-full font-display"
                style={{
                  padding: '1px 5px',
                  fontSize: 8,
                  fontWeight: 700,
                  background: 'rgba(10,10,10,0.06)',
                  color: 'rgba(10,10,10,0.5)',
                  letterSpacing: '0.04em',
                  textTransform: 'uppercase',
                }}
              >
                Soon
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
