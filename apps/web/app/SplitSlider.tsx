'use client'

import { useRef, useCallback } from 'react'
import { C } from '@/app/designTokens'

interface Props {
  value: number
  onChange: (value: number) => void
  dest1?: string
  dest2?: string
}

function tr(a: string, n = 6): string {
  return !a || a.length < n + 6 ? a : `${a.slice(0, n)}...${a.slice(-4)}`
}

export default function SplitSlider({ value, onChange, dest1, dest2 }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)

  const handlePointer = useCallback((e: React.PointerEvent) => {
    const track = trackRef.current
    if (!track) return
    const rect = track.getBoundingClientRect()
    const update = (clientX: number) => {
      const pct = Math.round(Math.max(1, Math.min(99, ((clientX - rect.left) / rect.width) * 100)))
      onChange(pct)
    }
    update(e.clientX)
    const onMove = (ev: PointerEvent) => update(ev.clientX)
    const onUp = () => { document.removeEventListener('pointermove', onMove); document.removeEventListener('pointerup', onUp) }
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
  }, [onChange])

  return (
    <div style={{ marginBottom: 10 }}>
      {/* Preview labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ fontFamily: C.M, fontSize: 10, color: C.purple }}>
          {value}% {dest1 ? `-> ${tr(dest1)}` : '-> Wallet A'}
        </div>
        <div style={{ fontFamily: C.M, fontSize: 10, color: C.blue }}>
          {100 - value}% {dest2 ? `-> ${tr(dest2)}` : '-> Wallet B'}
        </div>
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        onPointerDown={handlePointer}
        style={{
          position: 'relative', height: 28, cursor: 'pointer',
          background: 'rgba(10,10,10,0.04)', borderRadius: 8,
          border: `1px solid ${C.border}`, overflow: 'hidden',
          touchAction: 'none', userSelect: 'none',
        }}
      >
        {/* Primary fill */}
        <div style={{
          position: 'absolute', top: 0, left: 0, bottom: 0,
          width: `${value}%`,
          background: `linear-gradient(90deg, ${C.purple}30, ${C.purple}15)`,
          borderRight: `2px solid ${C.purple}`,
          transition: 'width 0.05s linear',
        }} />

        {/* Secondary fill */}
        <div style={{
          position: 'absolute', top: 0, right: 0, bottom: 0,
          width: `${100 - value}%`,
          background: `linear-gradient(90deg, ${C.blue}15, ${C.blue}30)`,
          transition: 'width 0.05s linear',
        }} />

        {/* Thumb */}
        <div style={{
          position: 'absolute', top: '50%', left: `${value}%`,
          transform: 'translate(-50%, -50%)',
          width: 16, height: 16, borderRadius: '50%',
          background: '#fff', border: `2px solid ${C.purple}`,
          boxShadow: `0 0 8px ${C.purple}40`,
          transition: 'left 0.05s linear',
        }} />

        {/* Center label */}
        <div style={{
          position: 'absolute', top: '50%', left: `${value}%`,
          transform: 'translate(-50%, -50%)',
          fontFamily: C.M, fontSize: 9, fontWeight: 700,
          color: '#fff', pointerEvents: 'none',
          textShadow: '0 1px 4px rgba(0,0,0,0.8)',
          marginTop: -18,
        }}>
          {value}%
        </div>
      </div>
    </div>
  )
}
