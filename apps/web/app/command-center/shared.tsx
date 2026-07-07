'use client'

import { useState } from 'react'
import type React from 'react'
import type { ChainFamily } from '../../lib/chain-adapters/types'

// ═══════════════════════════════════════════════════════════
//  PALETTE & CONSTANTS
// ═══════════════════════════════════════════════════════════

import { C, EASE } from '../designTokens'
export { C, EASE }

// Same-origin proxy → see app/api/backend/[...path]/route.ts
export const BACKEND = '/api/backend'
export const RSEND_FEE_PCT = 0.1

// ═══════════════════════════════════════════════════════════
//  TYPES
// ═══════════════════════════════════════════════════════════

export type Tab = 'routes' | 'splits' | 'monitor' | 'history' | 'analytics' | 'groups' | 'settings'
export type WizardStep = 1 | 2 | 3
export type DestMode = 'quick' | 'bulk'

export interface Destination {
  address: string
  label: string
  percent: number      // Display (es: 95.00) — usato per UI
  shareBps: number     // Canonical (es: 9500) — usato per API
  role?: 'primary' | 'commission' | 'fee'
}

export interface AdvancedSettings {
  threshold: string
  tokenFilter: string[]
  speed: 'economy' | 'normal' | 'fast'
  maxGas: string
  cooldown: string
  dailyLimit: string
  autoSwap: boolean
  swapTo: string
  scheduleEnabled: boolean
  schedDays: string[]
  schedFrom: string
  schedTo: string
  notifyEnabled: boolean
  notifyChannel: string
  chatId: string
  email: string
}

export const DEFAULT_ADVANCED: AdvancedSettings = {
  threshold: '0.001', tokenFilter: [], speed: 'normal',
  maxGas: '50', cooldown: '60', dailyLimit: '',
  autoSwap: false, swapTo: '',
  scheduleEnabled: false, schedDays: [], schedFrom: '09:00', schedTo: '18:00',
  notifyEnabled: true, notifyChannel: 'telegram', chatId: '', email: '',
}

export interface LogEntry {
  id: number
  rule_id: number
  source_wallet: string
  destination_wallet: string
  amount_human: number
  amount_usd: number | null
  token_symbol: string
  gas_cost_eth: number | null
  gas_percent: number | null
  status: string
  tx_hash: string | null
  created_at: string | null
  executed_at: string | null
  is_split: boolean
  split_percent: number
  error_message: string | null
  retry_count: number
}

// ═══════════════════════════════════════════════════════════
//  CONSTANTS
// ═══════════════════════════════════════════════════════════

export const CHAIN_NAMES: Record<number, string> = {
  1: 'Ethereum', 8453: 'Base', 10: 'Optimism', 42161: 'Arbitrum',
  137: 'Polygon', 84532: 'Base Sepolia', 11155111: 'Sepolia',
}

export const TOKEN_OPTIONS = ['ETH', 'USDC', 'USDT', 'DAI', 'WETH', 'cbBTC']
export const STATUS_OPTIONS = ['completed', 'failed', 'pending', 'executing', 'gas_too_high', 'skipped']

export const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: 'routes',    label: 'Routes',    icon: '\u27D0' },
  { key: 'splits',    label: 'Splits',    icon: '\u2982' },
  { key: 'monitor',   label: 'Monitor',   icon: '\u25C9' },
  { key: 'history',   label: 'History',   icon: '\u2630' },
  { key: 'analytics', label: 'Analytics', icon: '\u2197' },
  { key: 'groups',    label: 'Groups',    icon: '\u229E' },
  { key: 'settings',  label: 'Settings',  icon: '\u2699' },
]

export const STATUS_COLORS: Record<string, string> = {
  pending: '#FFB547', executing: '#3B82F6', completed: '#00D68F',
  failed: '#FF4C6A', gas_too_high: '#FF8C00', skipped: '#8A8FA8',
}

export const PIE_COLORS = [C.blue, C.green, C.purple, C.amber, C.red, '#06B6D4']

// ═══════════════════════════════════════════════════════════
//  ANIMATION CONFIG
// ═══════════════════════════════════════════════════════════

export const smooth = { type: 'spring' as const, bounce: 0, duration: 0.5 }
export const tabContent = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit:    { opacity: 0, y: -8 },
}

export const slideVariants = {
  enter: (dir: number) => ({ x: dir > 0 ? '60%' : '-60%', opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (dir: number) => ({ x: dir > 0 ? '-60%' : '60%', opacity: 0 }),
}

// ═══════════════════════════════════════════════════════════
//  INPUT STYLES
// ═══════════════════════════════════════════════════════════

export const inp: React.CSSProperties = {
  width: '100%', padding: '9px 12px', borderRadius: 10,
  boxSizing: 'border-box',
  background: 'rgba(10,10,10,0.05)',
  border: `1px solid ${C.border}`,
  color: C.text, fontFamily: C.M, fontSize: 12, outline: 'none',
}

export const selectStyle: React.CSSProperties = { ...inp, appearance: 'none' as const }

export const labelStyle: React.CSSProperties = {
  fontFamily: C.M, fontSize: 9, color: C.dim,
  textTransform: 'uppercase', letterSpacing: '0.08em',
  display: 'block', marginBottom: 4,
}

// ═══════════════════════════════════════════════════════════
//  HELPERS
// ═══════════════════════════════════════════════════════════

export function tr(a: string, s = 6, e = 4): string {
  return !a || a.length < s + e + 2 ? a : `${a.slice(0, s)}...${a.slice(-e)}`
}

export function ago(ts: string | null): string {
  if (!ts) return '--'
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`
}

export function fmtDate(iso: string | null): string {
  if (!iso) return '--'
  const d = new Date(iso)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function isValidAddr(a: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(a)
}

export function fiat(eth: number, price: number): string {
  const usd = eth * price
  if (usd >= 1000) return `$${(usd / 1000).toFixed(1)}k`
  if (usd >= 1) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(4)}`
}

// ═══════════════════════════════════════════════════════════
//  SKELETON
// ═══════════════════════════════════════════════════════════

export function Sk({ w, h, r = 8 }: { w: string | number; h: number; r?: number }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: r,
      background: 'linear-gradient(90deg, rgba(10,10,10,0.03) 25%, rgba(10,10,10,0.08) 50%, rgba(10,10,10,0.03) 75%)',
      backgroundSize: '200% 100%',
      animation: 'rpShimmer 1.8s ease infinite',
    }} />
  )
}

export function TabSkeleton() {
  return (
    <div style={{ padding: '12px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Sk w="100%" h={60} r={14} />
      <Sk w="100%" h={80} r={14} />
      <Sk w="60%" h={14} />
      <Sk w="100%" h={60} r={14} />
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  CHART TOOLTIP
// ═══════════════════════════════════════════════════════════

export function ChartTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#FFFFFF', border: `1px solid ${C.border}`,
      borderRadius: 10, padding: '8px 12px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
    }}>
      <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginBottom: 4 }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ fontFamily: C.M, fontSize: 11, color: p.color || C.text }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toFixed(4) : p.value}
        </div>
      ))}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  TOOLTIP COMPONENT
// ═══════════════════════════════════════════════════════════

export function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false)
  return (
    <span
      style={{ position: 'relative', cursor: 'help' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span style={{
          position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)',
          padding: '6px 10px', borderRadius: 8, marginBottom: 4,
          background: '#FFFFFF', border: `1px solid ${C.border}`,
          color: C.sub, fontFamily: C.M, fontSize: 10,
          whiteSpace: 'nowrap', zIndex: 50,
          boxShadow: '0 4px 12px rgba(0,0,0,0.5)',
          pointerEvents: 'none',
        }}>
          {text}
        </span>
      )}
    </span>
  )
}

// ═══════════════════════════════════════════════════════════
//  TOGGLE SWITCH
// ═══════════════════════════════════════════════════════════

export function ToggleSwitch({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!value)}
      style={{
        width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
        background: value ? C.green : 'rgba(10,10,10,0.08)',
        position: 'relative', transition: 'background 0.2s',
      }}
    >
      <div style={{
        width: 14, height: 14, borderRadius: '50%', background: '#fff',
        position: 'absolute', top: 3,
        left: value ? 19 : 3, transition: 'left 0.2s',
      }} />
    </button>
  )
}

// ═══════════════════════════════════════════════════════════
//  PAGINATION BUTTON
// ═══════════════════════════════════════════════════════════

export function PaginationBtn({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '6px 12px', borderRadius: 8,
        background: disabled ? 'rgba(10,10,10,0.04)' : 'rgba(10,10,10,0.08)',
        border: `1px solid ${C.border}`,
        color: disabled ? C.dim : C.text,
        fontFamily: C.M, fontSize: 12, cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {label}
    </button>
  )
}
