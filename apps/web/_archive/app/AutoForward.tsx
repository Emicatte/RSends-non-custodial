'use client'

/**
 * AutoForward.tsx — Sweeper Pipeline Visualization
 *
 * UI per creare regole di auto-forwarding e visualizzare
 * lo stato dei trasferimenti con animazione pipeline.
 */

import { useState, useEffect, useCallback } from 'react'
import { useAccount, useChainId } from 'wagmi'
import { motion, AnimatePresence } from 'framer-motion'
import { useForwardingRules } from '../lib/useForwardingRules'
import { logger } from '../lib/logger'

// Same-origin proxy → see app/api/backend/[...path]/route.ts
const BACKEND = '/api/backend'

import { C as BaseC } from '@/app/designTokens'
const C = { ...BaseC, pink: '#C8512C', card: 'rgba(255,255,255,0.92)' }

interface SweepLog {
  id: number; destination: string; amount: number; token: string
  gas_percent: number | null; status: string; tx_hash: string | null
  trigger_tx: string | null; created_at: string | null
}

function tr(a: string, s=6, e=4): string {
  return !a || a.length < s+e+2 ? a : `${a.slice(0,s)}…${a.slice(-e)}`
}
function ago(ts: string|null): string {
  if (!ts) return '—'
  const m = Math.floor((Date.now()-new Date(ts).getTime())/60000)
  if (m<1) return 'now'
  if (m<60) return `${m}m`
  const h = Math.floor(m/60)
  return h<24 ? `${h}h` : `${Math.floor(h/24)}d`
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#ffb800', executing: C.blue, completed: C.green,
  failed: C.red, gas_too_high: '#FF8C00',
}

// ═══════════════════════════════════════════════════════════
//  PIPELINE VISUALIZATION
// ═══════════════════════════════════════════════════════════
function Pipeline({ source, dest, status, amount, token }: {
  source: string; dest: string; status: string; amount?: number; token?: string
}) {
  const color = STATUS_COLORS[status] ?? C.dim
  const isActive = ['pending', 'executing'].includes(status)

  return (
    <div style={{ display:'flex', alignItems:'center', gap:0, padding:'16px 0' }}>
      {/* Source box */}
      <div style={{
        padding:'10px 14px', borderRadius:12,
        background:C.card, border:`1px solid ${C.border}`,
        minWidth:110, textAlign:'center' as const,
      }}>
        <div style={{ fontFamily:C.M, fontSize:9, color:C.dim, marginBottom:3 }}>SOURCE</div>
        <div style={{ fontFamily:C.M, fontSize:11, fontWeight:600, color:C.text }}>{tr(source)}</div>
        {amount && <div style={{ fontFamily:C.M, fontSize:10, color:C.sub, marginTop:2 }}>{amount.toFixed(4)} {token}</div>}
      </div>

      {/* Animated pipeline */}
      <div style={{ flex:1, position:'relative', height:4, margin:'0 -2px' }}>
        <div style={{ position:'absolute', inset:0, background:'rgba(10,10,10,0.04)', borderRadius:2 }} />
        {isActive ? (
          <motion.div
            style={{
              position:'absolute', top:0, left:0, height:'100%', borderRadius:2,
              background:`linear-gradient(90deg, transparent, ${color}, transparent)`,
              width:'40%',
            }}
            animate={{ x: ['0%', '150%'] }}
            transition={{ duration:1.5, repeat:Infinity, ease:'linear' }}
          />
        ) : status === 'completed' ? (
          <motion.div
            style={{
              position:'absolute', top:0, left:0, height:'100%', borderRadius:2,
              background:color, width:'100%',
            }}
            initial={{ scaleX:0, originX:0 }}
            animate={{ scaleX:1 }}
            transition={{ duration:0.5, ease:'easeOut' }}
          />
        ) : (
          <div style={{
            position:'absolute', top:0, left:0, height:'100%',
            background:color, opacity:0.3, width:'100%', borderRadius:2,
          }} />
        )}
      </div>

      {/* Dest box */}
      <div style={{
        padding:'10px 14px', borderRadius:12,
        background: status === 'completed' ? `${C.green}08` : C.card,
        border:`1px solid ${status === 'completed' ? `${C.green}20` : C.border}`,
        minWidth:110, textAlign:'center' as const,
      }}>
        <div style={{ fontFamily:C.M, fontSize:9, color:C.dim, marginBottom:3 }}>DEST</div>
        <div style={{ fontFamily:C.M, fontSize:11, fontWeight:600, color:C.text }}>{tr(dest)}</div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
//  MAIN COMPONENT
// ═══════════════════════════════════════════════════════════
interface Props { onClose?: () => void }

export default function AutoForward({ onClose }: Props) {
  const { address } = useAccount()
  const chainId = useChainId()
  const {
    rules, loading,
    createRule: createRuleSigned,
    updateRule,
  } = useForwardingRules(address)
  const [logs, setLogs] = useState<SweepLog[]>([])
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [dest, setDest] = useState('')
  const [threshold, setThreshold] = useState('0.001')
  const [gasStrategy, setGasStrategy] = useState('normal')
  const [maxGas, setMaxGas] = useState('10')

  const loadData = useCallback(async () => {
    if (!address) return
    try {
      const logsRes = await fetch(
        `${BACKEND}/api/v1/forwarding/logs?owner_address=${address.toLowerCase()}&per_page=10`
      )
      if (logsRes.ok) setLogs((await logsRes.json()).logs ?? [])
    } catch {}
  }, [address])

  useEffect(() => { loadData() }, [loadData])

  // Auto-refresh every 15s
  useEffect(() => {
    const iv = setInterval(loadData, 15000)
    return () => clearInterval(iv)
  }, [loadData])

  const handleCreateRule = async () => {
    if (!address || !dest) return
    setErrorMsg(null)
    try {
      await createRuleSigned({
        owner_address: address,
        source_wallet: address,
        destination_wallet: dest,
        min_threshold: parseFloat(threshold),
        gas_strategy: gasStrategy,
        max_gas_percent: parseFloat(maxGas),
        token_symbol: 'ETH',
        chain_id: chainId,
      })
      setShowCreate(false)
      setDest('')
      loadData()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setErrorMsg(msg)
      logger.error('AutoForward', 'createRule failed', { error: msg })
    }
  }

  const handleToggle = async (id: number, active: boolean) => {
    setErrorMsg(null)
    try {
      await updateRule(id, { is_active: !active })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setErrorMsg(msg)
      logger.error('AutoForward', 'toggleRule failed', { id: String(id), error: msg })
    }
  }

  if (!address) return null

  return (
    <div>
      {/* New Rule toggle — compact */}
      <div className="rp-anim-1" style={{ display:'flex', alignItems:'center', justifyContent:'flex-end', marginBottom:10 }}>
        <button onClick={() => setShowCreate(s => !s)} style={{
          padding:'6px 14px', borderRadius:10,
          background: showCreate ? 'rgba(10,10,10,0.06)' : `${C.purple}10`,
          border:`1px solid ${showCreate ? C.border : `${C.purple}25`}`,
          color: showCreate ? C.dim : C.purple,
          fontFamily:C.D, fontSize:11, fontWeight:600, cursor:'pointer',
          transition:'all 0.15s',
        }}>
          {showCreate ? '✕' : '+ Nuova Regola'}
        </button>
      </div>

      {errorMsg && (
        <div role="alert" style={{
          padding: '8px 12px', borderRadius: 8, marginBottom: 10,
          background: `${C.red}10`,
          border: `1px solid ${C.red}25`,
          color: C.red,
          fontFamily: C.M, fontSize: 11,
        }}>
          {errorMsg}
        </div>
      )}

      {/* Create form */}
      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity:0, height:0 }} animate={{ opacity:1, height:'auto' }} exit={{ opacity:0, height:0 }}
            transition={{ type:'spring', bounce:0, duration:0.4 }}
            style={{ overflow:'hidden', marginBottom:10 }}
          >
            <div className="bf-blur-32s" style={{ background:C.card, border:'1px solid rgba(10,10,10,0.12)', borderRadius:14, padding:14, boxShadow:'0 8px 48px rgba(0,0,0,0.08), inset 0 1px 0 rgba(10,10,10,0.04)' }}>
              {/* Destination */}
              <div style={{ marginBottom:8 }}>
                <label style={{ fontFamily:C.D, fontSize:10, fontWeight:700, color:C.dim, textTransform:'uppercase' as const, letterSpacing:'0.08em', display:'block', marginBottom:4 }}>Destinazione</label>
                <input value={dest} onChange={e => setDest(e.target.value)} placeholder="0x..." style={{
                  width:'100%', padding:'10px 12px', borderRadius:10, boxSizing:'border-box' as const,
                  background:'rgba(10,10,10,0.04)', border:'1px solid rgba(10,10,10,0.12)', color:C.text,
                  fontFamily:C.M, fontSize:12, outline:'none',
                }} />
              </div>

              {/* Threshold + Gas */}
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:6, marginBottom:10 }}>
                <div>
                  <label style={{ fontFamily:C.M, fontSize:9, color:C.dim, display:'block', marginBottom:3 }}>Min ETH</label>
                  <input type="number" value={threshold} onChange={e => setThreshold(e.target.value)} style={{
                    width:'100%', padding:'8px 10px', borderRadius:8, boxSizing:'border-box' as const,
                    background:'rgba(10,10,10,0.04)', border:'1px solid rgba(10,10,10,0.12)', color:C.text,
                    fontFamily:C.M, fontSize:11, outline:'none',
                  }} />
                </div>
                <div>
                  <label style={{ fontFamily:C.M, fontSize:9, color:C.dim, display:'block', marginBottom:3 }}>Gas</label>
                  <select value={gasStrategy} onChange={e => setGasStrategy(e.target.value)} style={{
                    width:'100%', padding:'8px 10px', borderRadius:8, boxSizing:'border-box' as const,
                    background:'rgba(10,10,10,0.04)', border:'1px solid rgba(10,10,10,0.12)', color:C.text,
                    fontFamily:C.M, fontSize:11, outline:'none',
                  }}>
                    <option value="fast">Fast</option>
                    <option value="normal">Normal</option>
                    <option value="slow">Slow</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontFamily:C.M, fontSize:9, color:C.dim, display:'block', marginBottom:3 }}>Max %</label>
                  <input type="number" value={maxGas} onChange={e => setMaxGas(e.target.value)} style={{
                    width:'100%', padding:'8px 10px', borderRadius:8, boxSizing:'border-box' as const,
                    background:'rgba(10,10,10,0.04)', border:'1px solid rgba(10,10,10,0.12)', color:C.text,
                    fontFamily:C.M, fontSize:11, outline:'none',
                  }} />
                </div>
              </div>

              <button onClick={handleCreateRule} disabled={!dest.startsWith('0x')} style={{
                width:'100%', padding:'14px', borderRadius:14, border:'none',
                background: dest.startsWith('0x') ? `linear-gradient(135deg, ${C.purple}, #D4724A)` : 'rgba(10,10,10,0.04)',
                color: dest.startsWith('0x') ? '#fff' : 'rgba(10,10,10,0.35)',
                fontFamily:C.D, fontSize:14, fontWeight:700, letterSpacing:'-0.01em',
                cursor: dest.startsWith('0x') ? 'pointer' : 'not-allowed',
                transition:'all 0.2s',
                boxShadow: dest.startsWith('0x') ? `0 4px 20px ${C.purple}25` : 'none',
              }}>
                Crea Regola
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Active Rules */}
      {rules.length > 0 && (
        <div style={{ marginBottom:10 }}>
          {rules.map(r => (
            <div key={r.id} className="bf-blur-24s160" style={{
              display:'flex', alignItems:'center', gap:10,
              padding:'11px 14px', borderRadius:12,
              background:C.card, border:'1px solid rgba(10,10,10,0.12)',
              marginBottom:4, opacity: r.is_active ? 1 : 0.4, boxShadow:'inset 0 1px 0 rgba(10,10,10,0.04)',
            }}>
              <div style={{ flex:1 }}>
                <div style={{ fontFamily:C.M, fontSize:11, color:C.text }}>
                  {tr(r.source_wallet)} → {tr(r.destination_wallet)}
                </div>
                <div style={{ fontFamily:C.M, fontSize:9, color:C.dim, marginTop:2 }}>
                  Min: {r.min_threshold} {r.token_symbol} · {r.gas_strategy}
                </div>
              </div>
              <button onClick={() => handleToggle(r.id, r.is_active)} style={{
                padding:'4px 10px', borderRadius:8,
                background: r.is_active ? `${C.green}10` : 'rgba(10,10,10,0.04)',
                border:`1px solid ${r.is_active ? `${C.green}25` : C.border}`,
                color: r.is_active ? C.green : C.dim,
                fontFamily:C.M, fontSize:10, fontWeight:600, cursor:'pointer',
              }}>
                {r.is_active ? 'ON' : 'OFF'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Recent Sweeps */}
      <div>
        {loading && logs.length === 0 ? (
          <div style={{ padding:20, textAlign:'center' as const, fontFamily:C.D, fontSize:12, color:C.dim }}>
            Caricamento…
          </div>
        ) : logs.length === 0 ? (
          <div className="bf-blur-32s" style={{
            padding:28, textAlign:'center' as const,
            background:C.card, borderRadius:14, border:'1px solid rgba(10,10,10,0.12)', boxShadow:'0 8px 48px rgba(0,0,0,0.08), inset 0 1px 0 rgba(10,10,10,0.04)',
          }}>
            <div style={{ fontFamily:C.D, fontSize:13, color:C.dim }}>Nessuno sweep</div>
            <div style={{ fontFamily:C.M, fontSize:10, color:`${C.dim}`, marginTop:4 }}>
              Crea una regola e invia fondi al wallet sorgente
            </div>
          </div>
        ) : (
          <div>
            {logs.map((log, i) => (
              <motion.div
                key={log.id}
                initial={{ opacity:0, y:10 }}
                animate={{ opacity:1, y:0 }}
                transition={{ delay: i*0.05 }}
              >
                <Pipeline source={address!} dest={log.destination} status={log.status} amount={log.amount} token={log.token} />
                <div style={{
                  display:'flex', alignItems:'center', justifyContent:'space-between',
                  padding:'0 8px 10px',
                  borderBottom: i < logs.length-1 ? `1px solid ${C.border}` : 'none',
                }}>
                  <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                    <div style={{ width:6, height:6, borderRadius:'50%', background: STATUS_COLORS[log.status] ?? C.dim }} />
                    <span style={{ fontFamily:C.M, fontSize:10, fontWeight:600, color: STATUS_COLORS[log.status] ?? C.dim, textTransform:'uppercase' as const }}>{log.status}</span>
                  </div>
                  <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                    <span style={{ fontFamily:C.M, fontSize:9, color:C.dim }}>{ago(log.created_at)}</span>
                    {log.tx_hash && (
                      <a href={`https://basescan.org/tx/${log.tx_hash}`} target="_blank" rel="noopener noreferrer"
                        style={{ fontFamily:C.M, fontSize:9, color:C.sub, textDecoration:'none' }}>↗</a>
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}