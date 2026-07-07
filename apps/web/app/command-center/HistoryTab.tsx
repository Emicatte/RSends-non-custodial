'use client'

import { useState, useEffect, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { C, EASE, BACKEND, RSEND_FEE_PCT, STATUS_COLORS, STATUS_OPTIONS, TOKEN_OPTIONS, CHAIN_NAMES, tr, ago, fmtDate, fiat, isValidAddr, Sk, TabSkeleton, PaginationBtn, inp, selectStyle, labelStyle } from './shared'
import type { LogEntry } from './shared'
import type { ChainFamily } from '../../lib/chain-adapters/types'
import { mutationHeaders } from '../../lib/rsendFetch'
import { logger } from '../../lib/logger'

function HistoryTab({ address, ethPrice, stats: overallStats, rules, activeFamily, walletAddress }: { address: string; ethPrice: number; stats: any; rules: any[]; activeFamily: ChainFamily; walletAddress: string | null }) {
  const t = useTranslations('commandCenter.history')
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [total, setTotal] = useState(0)

  const [fToken, setFToken] = useState('')
  const [fStatus, setFStatus] = useState('')
  const [fDateFrom, setFDateFrom] = useState('')
  const [fDateTo, setFDateTo] = useState('')
  const [fRoute, setFRoute] = useState('')
  const [fSearch, setFSearch] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const ownerAddr = walletAddress || address
      const params = new URLSearchParams({
        owner_address: ownerAddr.toLowerCase(),
        chain_family: activeFamily,
        page: String(page),
        per_page: '15',
      })
      if (fToken) params.set('token', fToken)
      if (fStatus) params.set('status', fStatus)
      if (fDateFrom) params.set('date_from', new Date(fDateFrom).toISOString())
      if (fDateTo) params.set('date_to', new Date(fDateTo).toISOString())
      if (fRoute) params.set('rule_id', fRoute)
      if (fSearch) params.set('search', fSearch)

      const res = await fetch(`${BACKEND}/api/v1/forwarding/logs?${params}`, {
        signal: AbortSignal.timeout(15000),
      })
      if (res.ok) {
        const data = await res.json()
        setLogs(data.logs ?? [])
        setTotalPages(data.pagination?.pages ?? 0)
        setTotal(data.pagination?.total ?? 0)
      }
    } catch (err) {
      logger.error('CommandCenter', 'Fetch logs failed', { error: String(err) })
    }
    setLoading(false)
  }, [address, walletAddress, activeFamily, page, fToken, fStatus, fDateFrom, fDateTo, fRoute, fSearch])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  const exportUrl = (fmt: string) => {
    const ownerAddr = walletAddress || address
    const params = new URLSearchParams({
      owner_address: ownerAddr.toLowerCase(),
      chain_family: activeFamily,
      format: fmt,
    })
    if (fToken) params.set('token', fToken)
    if (fStatus) params.set('status', fStatus)
    if (fDateFrom) params.set('date_from', new Date(fDateFrom).toISOString())
    if (fDateTo) params.set('date_to', new Date(fDateTo).toISOString())
    if (fRoute) params.set('rule_id', fRoute)
    if (fSearch) params.set('search', fSearch)
    return `${BACKEND}/api/v1/forwarding/logs/export?${params}`
  }

  return (
    <div>
      {/* Summary */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.sub }}>
          {total} transaction{total !== 1 ? 's' : ''}
        </span>
        <div style={{ display: 'flex', gap: 4 }}>
          <a href={exportUrl('csv')} target="_blank" rel="noopener noreferrer" style={{
            padding: '4px 10px', borderRadius: 8,
            background: `${C.blue}10`, border: `1px solid ${C.blue}20`,
            color: C.blue, fontFamily: C.M, fontSize: 9, fontWeight: 600,
            textDecoration: 'none', cursor: 'pointer',
          }}>CSV</a>
          <a href={exportUrl('json')} target="_blank" rel="noopener noreferrer" style={{
            padding: '4px 10px', borderRadius: 8,
            background: `${C.purple}10`, border: `1px solid ${C.purple}20`,
            color: C.purple, fontFamily: C.M, fontSize: 9, fontWeight: 600,
            textDecoration: 'none', cursor: 'pointer',
          }}>JSON</a>
        </div>
      </div>

      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 6, marginBottom: 10 }}>
        {[
          { label: t('totalRouted'), val: overallStats ? `${overallStats.total_volume_eth.toFixed(4)} ETH` : '--', sub: overallStats ? fiat(overallStats.total_volume_eth, ethPrice) : '', color: C.purple },
          { label: t('fees'), val: overallStats ? `${(overallStats.total_volume_eth * RSEND_FEE_PCT / 100).toFixed(6)} ETH` : '--', sub: overallStats ? fiat(overallStats.total_volume_eth * RSEND_FEE_PCT / 100, ethPrice) : '', color: C.amber },
          { label: t('gasSpent'), val: overallStats ? `${overallStats.total_gas_spent_eth.toFixed(6)} ETH` : '--', sub: overallStats ? fiat(overallStats.total_gas_spent_eth, ethPrice) : '', color: C.blue },
          { label: t('successRate'), val: overallStats ? `${overallStats.success_rate}%` : '--', sub: overallStats ? `${overallStats.completed}/${overallStats.total_sweeps}` : '', color: overallStats?.success_rate >= 90 ? C.green : overallStats?.success_rate >= 70 ? C.amber : C.red },
        ].map(c => (
          <div key={c.label} style={{
            background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
            borderRadius: 10, padding: '8px 10px',
          }}>
            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{c.label}</div>
            <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 700, color: c.color }}>{c.val}</div>
            {c.sub && <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, marginTop: 1 }}>{c.sub}</div>}
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr 1fr 1fr', gap: 6, marginBottom: 10 }}>
        <div>
          <label style={labelStyle}>Route</label>
          <select value={fRoute} onChange={e => { setFRoute(e.target.value); setPage(1) }} style={selectStyle}>
            <option value="">All</option>
            {rules.map((r: any) => <option key={r.id} value={r.id}>{r.label || `#${r.id}`}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Token</label>
          <select value={fToken} onChange={e => { setFToken(e.target.value); setPage(1) }} style={selectStyle}>
            <option value="">All</option>
            {TOKEN_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Status</label>
          <select value={fStatus} onChange={e => { setFStatus(e.target.value); setPage(1) }} style={selectStyle}>
            <option value="">All</option>
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>From</label>
          <input type="date" value={fDateFrom} onChange={e => { setFDateFrom(e.target.value); setPage(1) }} style={inp} />
        </div>
        <div>
          <label style={labelStyle}>To</label>
          <input type="date" value={fDateTo} onChange={e => { setFDateTo(e.target.value); setPage(1) }} style={inp} />
        </div>
        <div>
          <label style={labelStyle}>TX Hash</label>
          <input value={fSearch} onChange={e => { setFSearch(e.target.value); setPage(1) }} placeholder="0x..." style={inp} />
        </div>
      </div>

      {/* Table */}
      <div style={{
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${C.border}`,
        borderRadius: 14, overflow: 'hidden',
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '32px 78px 44px 80px 1fr 60px 55px',
          gap: 4, padding: '8px 12px',
          borderBottom: `1px solid ${C.border}`,
          background: 'rgba(10,10,10,0.04)',
        }}>
          {[t('columns.id'), t('columns.time'), t('columns.token'), t('columns.amount'), t('columns.route'), t('columns.tx'), t('columns.status')].map(h => (
            <span key={h} style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              {h}
            </span>
          ))}
        </div>

        {loading && logs.length === 0 ? (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[1, 2, 3].map(i => <Sk key={i} w="100%" h={28} r={6} />)}
          </div>
        ) : logs.length === 0 ? (
          <div style={{ padding: 28, textAlign: 'center' }}>
            <div style={{ fontFamily: C.D, fontSize: 12, color: C.dim }}>No transactions found</div>
          </div>
        ) : (
          logs.map((l, i) => {
            const sc = STATUS_COLORS[l.status] ?? C.dim
            const amtUsd = l.amount_usd != null ? l.amount_usd : (l.amount_human || 0) * ethPrice
            const isExpanded = expanded === l.id
            return (
              <div key={l.id}>
                <div
                  onClick={() => setExpanded(isExpanded ? null : l.id)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '32px 78px 44px 80px 1fr 60px 55px',
                    gap: 4, padding: '8px 12px',
                    borderBottom: (i < logs.length - 1 && !isExpanded) ? `1px solid ${C.border}` : 'none',
                    alignItems: 'center',
                    cursor: 'pointer',
                    background: isExpanded ? 'rgba(10,10,10,0.04)' : 'transparent',
                    transition: 'background 0.15s',
                  }}
                >
                  <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>#{l.rule_id}</span>
                  <span style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>{fmtDate(l.created_at)}</span>
                  <span style={{ fontFamily: C.M, fontSize: 10, color: C.text, fontWeight: 600 }}>{l.token_symbol}</span>
                  <div>
                    <div style={{ fontFamily: C.M, fontSize: 10, color: C.text }}>
                      {l.amount_human?.toFixed(4)}
                    </div>
                    <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim }}>
                      {fiat(amtUsd / ethPrice, ethPrice)}
                    </div>
                  </div>
                  <span style={{ fontFamily: C.M, fontSize: 9, color: C.sub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {tr(l.source_wallet)} {'\u2192'} {tr(l.destination_wallet)}
                  </span>
                  <span>
                    {l.tx_hash ? (
                      <a
                        href={`https://basescan.org/tx/${l.tx_hash}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={e => e.stopPropagation()}
                        style={{ fontFamily: C.M, fontSize: 9, color: C.blue, textDecoration: 'none' }}
                      >
                        {l.tx_hash.slice(0, 8)}...
                      </a>
                    ) : (
                      <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>--</span>
                    )}
                  </span>
                  <span style={{
                    fontFamily: C.M, fontSize: 8, fontWeight: 600, color: sc,
                    textTransform: 'uppercase',
                    background: `${sc}10`, padding: '2px 6px', borderRadius: 4,
                    textAlign: 'center',
                  }}>
                    {l.status}
                  </span>
                </div>
                {/* Expanded detail row */}
                <AnimatePresence>
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ type: 'spring', bounce: 0, duration: 0.3 }}
                      style={{ overflow: 'hidden' }}
                    >
                      <div style={{
                        padding: '10px 14px',
                        background: 'rgba(10,10,10,0.03)',
                        borderBottom: `1px solid ${C.border}`,
                        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
                      }}>
                        <div>
                          <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', marginBottom: 3 }}>Recipients</div>
                          <div style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
                            {tr(l.destination_wallet, 10, 6)}
                            {l.is_split && <span style={{ color: C.purple, marginLeft: 6 }}>{l.split_percent}%</span>}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', marginBottom: 3 }}>Gas</div>
                          <div style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
                            {l.gas_cost_eth != null ? `${l.gas_cost_eth.toFixed(6)} ETH (${fiat(l.gas_cost_eth, ethPrice)})` : '--'}
                            {l.gas_percent != null && <span style={{ color: C.dim, marginLeft: 6 }}>{l.gas_percent.toFixed(1)}%</span>}
                          </div>
                        </div>
                        {l.error_message && (
                          <div style={{ gridColumn: '1 / -1' }}>
                            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', marginBottom: 3 }}>Error</div>
                            <div style={{ fontFamily: C.M, fontSize: 10, color: C.red }}>{l.error_message}</div>
                          </div>
                        )}
                        {l.retry_count > 0 && (
                          <div>
                            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', marginBottom: 3 }}>Retries</div>
                            <div style={{ fontFamily: C.M, fontSize: 10, color: C.amber }}>{l.retry_count}</div>
                          </div>
                        )}
                        {l.executed_at && (
                          <div>
                            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', marginBottom: 3 }}>Executed</div>
                            <div style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>{fmtDate(l.executed_at)}</div>
                          </div>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 10 }}>
          <PaginationBtn label={"\u2190"} disabled={page <= 1} onClick={() => setPage(p => p - 1)} />
          <span style={{ fontFamily: C.M, fontSize: 11, color: C.sub }}>{page} / {totalPages}</span>
          <PaginationBtn label={"\u2192"} disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} />
        </div>
      )}
    </div>
  )
}

export default HistoryTab
