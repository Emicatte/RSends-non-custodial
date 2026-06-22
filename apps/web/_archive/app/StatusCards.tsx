'use client'

import { motion } from 'framer-motion'
import { C } from '@/app/designTokens'

interface Props {
  gas: number | null
  sweeps24h: number
  volume24h: string
  activeRules: number
}

function gasLevel(g: number | null) {
  if (g === null) return { label: '--', color: C.dim }
  if (g < 0.01) return { label: 'Optimal', color: C.green }
  if (g < 0.1) return { label: 'Normal', color: C.amber }
  return { label: 'High', color: C.red }
}

const cardStyle: React.CSSProperties = {
  background: 'rgba(10,10,10,0.03)',
  border: `1px solid ${C.border}`,
  borderRadius: 14,
  padding: '14px 16px',
  flex: 1,
  minWidth: 0,
}

export default function StatusCards({ gas, sweeps24h, volume24h, activeRules }: Props) {
  const gl = gasLevel(gas)

  const cards = [
    {
      label: 'Gas',
      value: gas !== null ? `${gas.toFixed(4)}` : '--',
      unit: 'Gwei',
      color: gl.color,
      badge: gl.label,
    },
    {
      label: 'Sweeps 24h',
      value: String(sweeps24h),
      unit: '',
      color: C.blue,
      badge: null,
    },
    {
      label: 'Volume 24h',
      value: volume24h,
      unit: 'ETH',
      color: C.purple,
      badge: null,
    },
    {
      label: 'Active Rules',
      value: String(activeRules),
      unit: '',
      color: C.green,
      badge: null,
    },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
      {cards.map((c, i) => (
        <motion.div
          key={c.label}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05, type: 'spring', bounce: 0, duration: 0.5 }}
          style={cardStyle}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              {c.label}
            </span>
            {c.badge && (
              <span style={{
                fontFamily: C.M, fontSize: 8, fontWeight: 600,
                color: c.color, background: `${c.color}12`,
                padding: '2px 6px', borderRadius: 6,
              }}>
                {c.badge}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <div style={{ width: 5, height: 5, borderRadius: '50%', background: c.color, boxShadow: `0 0 6px ${c.color}50`, flexShrink: 0, marginBottom: 1 }} />
            <span style={{ fontFamily: C.D, fontSize: 18, fontWeight: 700, color: C.text, lineHeight: 1 }}>
              {c.value}
            </span>
            {c.unit && (
              <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>{c.unit}</span>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  )
}
