'use client'

import { useState, useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { C, EASE, STATUS_COLORS, smooth, tr, ago, fiat, Sk } from './shared'
import StatusCards from '../StatusCards'
import SweepFeed from '../SweepFeed'
import EmergencyStop from '../EmergencyStop'
import type { ChainFamily } from '../../lib/chain-adapters/types'

function MonitorTab({ gas, stats, activeRules, events, connected, emergencyStop, ethPrice, rules, wsStats, activeFamily }: {
  gas: number | null
  stats: any
  activeRules: number
  events: any[]
  connected: boolean
  emergencyStop: () => Promise<any>
  ethPrice: number
  rules: any[]
  wsStats: { totalEvents: number; reconnects: number }
  activeFamily: ChainFamily
}) {
  const t = useTranslations('commandCenter.monitor')

  // ── Non-EVM guard: sweep monitor is EVM-only ──
  if (activeFamily !== 'evm') {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>
          {activeFamily === 'solana' ? '◎' : '◆'}
        </div>
        <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>
          {t('nonEvmTitle', { chain: activeFamily === 'solana' ? 'Solana' : 'TRON' })}
        </div>
        <div style={{ fontFamily: C.M, fontSize: 11, color: C.dim, lineHeight: 1.5 }}>
          {t('nonEvmDesc')}
        </div>
      </div>
    )
  }

  const [flash, setFlash] = useState(false)
  const prevLen = useRef(events.length)

  // Flash pipeline green on sweep_completed
  useEffect(() => {
    if (events.length > prevLen.current && events[0]?.type === 'sweep_completed') {
      setFlash(true)
    }
    prevLen.current = events.length
  }, [events.length])

  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(false), 1200)
    return () => clearTimeout(t)
  }, [flash])

  const gl = gas === null ? { label: '--', color: C.dim }
    : gas < 0.01 ? { label: t('optimal'), color: C.green }
    : gas < 0.1 ? { label: t('normal'), color: C.amber }
    : { label: t('high'), color: C.red }

  const vol = stats?.total_volume_eth ?? 0
  const cards = [
    { label: t('gas'), value: gas !== null ? gas.toFixed(4) : '--', unit: 'Gwei', badge: gl.label, color: gl.color },
    { label: t('sweeps24h'), value: String(stats?.total_sweeps ?? 0), unit: '', badge: wsStats.totalEvents > 0 ? `${wsStats.totalEvents} ws` : null, color: C.blue },
    { label: t('volume24h'), value: `${vol.toFixed(4)} ETH`, unit: '', badge: fiat(vol, ethPrice), color: C.purple },
    { label: t('activeRoutes'), value: String(activeRules), unit: '', badge: null, color: C.green },
  ]

  // Pipeline destinations
  const activeR = rules.filter((r: any) => r.is_active && !r.is_paused)
  const dests = activeR.slice(0, 5)
  const pipeH = Math.max(120, dests.length * 36 + 40)
  const midY = pipeH / 2

  return (
    <div>
      {/* Status Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
        {cards.map((c, i) => (
          <motion.div
            key={c.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, ...smooth }}
            style={{
              background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
              borderRadius: 14, padding: '14px 16px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{c.label}</span>
              {c.badge && (
                <span style={{ fontFamily: C.M, fontSize: 8, fontWeight: 600, color: c.color, background: `${c.color}12`, padding: '2px 6px', borderRadius: 6 }}>{c.badge}</span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
              <div style={{
                width: 5, height: 5, borderRadius: '50%', background: c.color,
                boxShadow: `0 0 6px ${c.color}50`, flexShrink: 0, marginBottom: 1,
              }} />
              <span style={{ fontFamily: C.D, fontSize: 18, fontWeight: 700, color: C.text, lineHeight: 1 }}>{c.value}</span>
              {c.unit && <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>{c.unit}</span>}
            </div>
          </motion.div>
        ))}
      </div>

      {/* Pipeline Visualization */}
      <div style={{
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${flash ? `${C.green}40` : C.border}`,
        borderRadius: 14, padding: '14px 12px', marginBottom: 12,
        transition: 'border-color 0.6s, box-shadow 0.6s',
        boxShadow: flash ? `0 0 20px ${C.green}15, inset 0 0 20px ${C.green}08` : 'none',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub }}>{t('pipeline')}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 5, height: 5, borderRadius: '50%',
              background: connected ? C.green : C.red,
              boxShadow: connected ? `0 0 6px ${C.green}60` : 'none',
              animation: connected ? 'rpPulse 2s ease infinite' : 'none',
            }} />
            <span style={{ fontFamily: C.M, fontSize: 9, color: connected ? C.green : C.dim }}>
              {connected ? t('live') : t('offline')}
            </span>
          </div>
        </div>
        <svg width="100%" viewBox={`0 0 360 ${pipeH}`} style={{ display: 'block' }}>
          {/* Source node */}
          <circle cx="40" cy={midY} r="18" fill={`${C.purple}12`} stroke={C.purple} strokeWidth="0.8" />
          <text x="40" y={midY + 3} textAnchor="middle" fill={C.purple} fontSize="8" fontFamily="var(--font-mono)">SRC</text>

          {/* RSends engine node */}
          <rect x="145" y={midY - 16} width="70" height="32" rx="10"
            fill={flash ? `${C.green}20` : `${C.green}08`} stroke={C.green} strokeWidth="0.8"
            style={{ transition: 'fill 0.6s' }}
          />
          <text x="180" y={midY + 4} textAnchor="middle" fill={C.green} fontSize="9" fontFamily="var(--font-display)" fontWeight="600">RSends</text>

          {/* Source → RSends line */}
          <line x1="58" y1={midY} x2="145" y2={midY} stroke={C.purple} strokeWidth="0.8" strokeDasharray="5 3" opacity="0.5">
            {connected && <animate attributeName="stroke-dashoffset" from="8" to="0" dur="1.2s" repeatCount="indefinite" />}
          </line>
          {/* Particle on source→RSends */}
          {connected && events.length > 0 && (
            <circle r="2.5" fill={C.purple} opacity="0.7">
              <animateMotion path={`M58,${midY} L145,${midY}`} dur="1.8s" repeatCount="indefinite" />
            </circle>
          )}

          {/* Destination nodes + lines */}
          {dests.length > 0 ? dests.map((d: any, i: number) => {
            const dy = (pipeH / (dests.length + 1)) * (i + 1)
            const col = [C.blue, C.green, C.purple, C.amber, C.red][i % 5]
            return (
              <g key={d.id}>
                <line x1="215" y1={midY} x2="300" y2={dy} stroke={col} strokeWidth="0.8" strokeDasharray="5 3" opacity="0.4">
                  {connected && <animate attributeName="stroke-dashoffset" from="8" to="0" dur="1.5s" repeatCount="indefinite" />}
                </line>
                {connected && events.length > 0 && (
                  <circle r="2" fill={col} opacity="0.6">
                    <animateMotion path={`M215,${midY} L300,${dy}`} dur={`${2 + i * 0.3}s`} repeatCount="indefinite" />
                  </circle>
                )}
                <circle cx="320" cy={dy} r="14" fill={`${col}10`} stroke={col} strokeWidth="0.8" />
                <text x="320" y={dy + 3} textAnchor="middle" fill={col} fontSize="7" fontFamily="var(--font-mono)">
                  {(d.label || d.destination_wallet || '').slice(0, 4).toUpperCase() || `D${i + 1}`}
                </text>
              </g>
            )
          }) : (
            <g>
              <line x1="215" y1={midY} x2="300" y2={midY} stroke={C.dim} strokeWidth="0.8" strokeDasharray="5 3" opacity="0.3" />
              <circle cx="320" cy={midY} r="14" fill="rgba(10,10,10,0.03)" stroke={C.dim} strokeWidth="0.8" />
              <text x="320" y={midY + 3} textAnchor="middle" fill={C.dim} fontSize="7" fontFamily="var(--font-mono)">---</text>
            </g>
          )}
        </svg>
      </div>

      {/* Live Feed */}
      <SweepFeed events={events} connected={connected} />

      {/* Emergency Stop */}
      <EmergencyStop onStop={emergencyStop} activeCount={activeRules} />
    </div>
  )
}

export default MonitorTab
