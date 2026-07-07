'use client'

import { motion, AnimatePresence } from 'framer-motion'
import type { SweepEvent } from '../lib/useSweepWebSocket'
import { C } from '@/app/designTokens'

const EVENT_COLORS: Record<string, string> = {
  sweep_completed: C.green,
  sweep_started: C.blue,
  sweep_failed: C.red,
  sweep_queued: C.amber,
  emergency_stop: C.red,
  rule_created: C.purple,
  rule_updated: C.purple,
  rule_paused: C.amber,
  rule_resumed: C.green,
}

const EVENT_LABELS: Record<string, string> = {
  sweep_completed: 'Sweep Completed',
  sweep_started: 'Sweep Started',
  sweep_failed: 'Sweep Failed',
  sweep_queued: 'Sweep Queued',
  emergency_stop: 'Emergency Stop',
  rule_created: 'Rule Created',
  rule_updated: 'Rule Updated',
  rule_paused: 'Rule Paused',
  rule_resumed: 'Rule Resumed',
}

function timeAgo(ts: string): string {
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  return `${Math.floor(m / 60)}h ago`
}

interface Props {
  events: SweepEvent[]
  connected: boolean
}

export default function SweepFeed({ events, connected }: Props) {
  return (
    <div style={{
      background: 'rgba(10,10,10,0.03)',
      border: `1px solid ${C.border}`,
      borderRadius: 14,
      overflow: 'hidden',
      marginBottom: 12,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px',
        borderBottom: `1px solid ${C.border}`,
      }}>
        <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub }}>Live Feed</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            width: 5, height: 5, borderRadius: '50%',
            background: connected ? C.green : C.red,
            boxShadow: connected ? `0 0 6px ${C.green}60` : 'none',
            animation: connected ? 'rpPulse 2s ease infinite' : 'none',
          }} />
          <span style={{ fontFamily: C.M, fontSize: 9, color: connected ? C.green : C.dim }}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
      </div>

      {/* Events list */}
      <div style={{ maxHeight: 260, overflowY: 'auto' }}>
        {events.length === 0 ? (
          <div style={{ padding: '28px 16px', textAlign: 'center' }}>
            <div style={{ fontFamily: C.D, fontSize: 12, color: C.dim, marginBottom: 4 }}>Waiting for events</div>
            <div style={{ fontFamily: C.M, fontSize: 10, color: `${C.dim}80` }}>
              Activity will appear here in real-time
            </div>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {events.slice(0, 20).map((ev, i) => {
              const color = EVENT_COLORS[ev.type] ?? C.sub
              const label = EVENT_LABELS[ev.type] ?? ev.type
              const d = ev.data ?? {}
              return (
                <motion.div
                  key={`${ev.timestamp}-${i}`}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ type: 'spring', bounce: 0, duration: 0.35 }}
                  style={{ overflow: 'hidden' }}
                >
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 14px',
                    borderBottom: `1px solid ${C.border}`,
                  }}>
                    <div style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: color, flexShrink: 0,
                      boxShadow: `0 0 4px ${color}40`,
                    }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color }}>
                        {label}
                      </div>
                      {d.amount_human != null && (
                        <div style={{ fontFamily: C.M, fontSize: 10, color: C.sub, marginTop: 1 }}>
                          {Number(d.amount_human).toFixed(4)} {d.token_symbol ?? 'ETH'}
                          {d.destination_wallet && ` -> ${d.destination_wallet.slice(0, 8)}...`}
                        </div>
                      )}
                      {d.tx_hash && (
                        <a
                          href={`https://basescan.org/tx/${d.tx_hash}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ fontFamily: C.M, fontSize: 9, color: C.blue, textDecoration: 'none' }}
                        >
                          {d.tx_hash.slice(0, 10)}...
                        </a>
                      )}
                    </div>
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, flexShrink: 0 }}>
                      {timeAgo(ev.timestamp)}
                    </span>
                  </div>
                </motion.div>
              )
            })}
          </AnimatePresence>
        )}
      </div>
    </div>
  )
}
