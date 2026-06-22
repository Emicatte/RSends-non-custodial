'use client'

import { useState, useRef, useCallback } from 'react'

import { C } from '@/app/designTokens'
const T = { ...C, muted: C.sub }

const GAS_LABELS: Record<string, { label: string; color: string }> = {
  low:     { label: 'Basso',   color: '#00D68F' },
  normal:  { label: 'Normale', color: '#00D68F' },
  high:    { label: 'Alto',    color: '#FFB547' },
  extreme: { label: 'Critico', color: '#FF4C6A' },
}

interface GasTooltipProps {
  gasGwei: number
  estimatedSeconds: number
  gasLevel: 'low' | 'normal' | 'high' | 'extreme'
  children: React.ReactNode
}

export default function GasHoverTooltip({ gasGwei, estimatedSeconds, gasLevel, children }: GasTooltipProps) {
  const [visible, setVisible] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setVisible(true)
  }, [])

  const hide = useCallback(() => {
    timeoutRef.current = setTimeout(() => setVisible(false), 120)
  }, [])

  const toggle = useCallback(() => setVisible(v => !v), [])

  const info = GAS_LABELS[gasLevel] ?? GAS_LABELS.normal
  const costUsd = (gasGwei * 21000 * 1e-9 * 2500).toFixed(4) // rough ETH price estimate

  return (
    <div
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={show}
      onMouseLeave={hide}
      onClick={toggle}
    >
      {children}
      {visible && (
        <div style={{
          position: 'absolute',
          bottom: 'calc(100% + 8px)',
          left: '50%',
          transform: 'translateX(-50%)',
          zIndex: 9999,
          background: T.card,
          border: `1px solid ${T.border}`,
          borderRadius: 12,
          padding: 12,
          minWidth: 200,
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          animation: 'fadeIn 150ms ease',
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Row label="Gas" value={`${gasGwei.toFixed(4)} Gwei`} />
            <Row label="Costo stimato" value={`~$${costUsd}`} />
            <Row label="Tempo conferma" value={`~${estimatedSeconds}s`} />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontFamily: T.M, fontSize: 10, color: T.muted }}>Stato rete</span>
              <span style={{ fontFamily: T.D, fontSize: 11, fontWeight: 600, color: info.color }}>
                {info.label}
              </span>
            </div>
          </div>
          {/* Arrow */}
          <div style={{
            position: 'absolute', bottom: -5, left: '50%',
            width: 10, height: 10, background: T.card,
            border: `1px solid ${T.border}`,
            borderTop: 'none', borderLeft: 'none',
            transform: 'translateX(-50%) rotate(45deg)',
          }} />
        </div>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
      <span style={{ fontFamily: T.M, fontSize: 10, color: T.muted }}>{label}</span>
      <span style={{ fontFamily: T.M, fontSize: 11, color: T.text }}>{value}</span>
    </div>
  )
}
