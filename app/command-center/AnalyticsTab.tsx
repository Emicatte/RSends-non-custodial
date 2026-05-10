'use client'

import { useState, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { motion } from 'framer-motion'
import { C, EASE, PIE_COLORS, BACKEND, smooth, fiat, Sk, ChartTip } from './shared'
import { useAccount } from 'wagmi'
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, PieChart, Pie, Cell, BarChart, Bar } from 'recharts'
import { logger } from '../../lib/logger'
import { useWalletAuth } from '../../lib/walletAuth'

function AnalyticsTab({ stats: parentStats, daily: parentDaily, loading: parentLoading, ethPrice, isVisible = true }: {
  stats: any; daily: any[]; loading: boolean; ethPrice: number; isVisible?: boolean
}) {
  const t = useTranslations('commandCenter.analytics')
  const [tokenBreakdown, setTokenBreakdown] = useState<{ name: string; value: number }[]>([])
  const [topRoutes, setTopRoutes] = useState<{ label: string; volume: number }[]>([])
  const { address } = useAccount()
  const { getAuthHeaders, clearCache } = useWalletAuth(address)

  // Period selector
  type Period = '24h' | '7d' | '30d' | 'all'
  const [period, setPeriod] = useState<Period>('30d')
  const [periodStats, setPeriodStats] = useState<any>(null)
  const [periodDaily, setPeriodDaily] = useState<any[]>([])
  const [periodLoading, setPeriodLoading] = useState(false)

  // Use parent data for 30d, fetch for other periods
  const stats = period === '30d' ? parentStats : periodStats
  const daily = period === '30d' ? parentDaily : periodDaily
  const loading = period === '30d' ? parentLoading : periodLoading

  useEffect(() => {
    if (period === '30d' || !address) return
    setPeriodLoading(true)
    const fetchPeriod = async () => {
      try {
        const days = period === '24h' ? 1 : period === '7d' ? 7 : 365
        const statsUrl = `${BACKEND}/api/v1/forwarding/stats?period=${period}`
        const dailyUrl = `${BACKEND}/api/v1/forwarding/stats/daily?days=${days}`
        const doFetch = (url: string, headers: Record<string, string>) =>
          fetch(url, { headers, signal: AbortSignal.timeout(15000) })
        // Sign once → reuse the same headers for both parallel fetches.
        // If either returns 401 (stale cache / clock skew), drop cache and
        // retry both with a fresh signature. Mirrors useSweepStats.
        const headers = await getAuthHeaders()
        let [sRes, dRes] = await Promise.all([
          doFetch(statsUrl, headers),
          doFetch(dailyUrl, headers),
        ])
        if (sRes.status === 401 || dRes.status === 401) {
          clearCache()
          const fresh = await getAuthHeaders()
          ;[sRes, dRes] = await Promise.all([
            doFetch(statsUrl, fresh),
            doFetch(dailyUrl, fresh),
          ])
        }
        if (sRes.ok) setPeriodStats(await sRes.json())
        if (dRes.ok) { const d = await dRes.json(); setPeriodDaily(d.data ?? []) }
      } catch (err) {
        logger.error('CommandCenter', 'Fetch period stats failed', { period, error: String(err) })
      }
      setPeriodLoading(false)
    }
    fetchPeriod()
  }, [period, address, getAuthHeaders, clearCache])

  // Token breakdown + top routes
  useEffect(() => {
    if (!address) return
    const f = async () => {
      try {
        const res = await fetch(
          `${BACKEND}/api/v1/forwarding/logs?owner_address=${address.toLowerCase()}&per_page=200`,
          { signal: AbortSignal.timeout(15000) }
        )
        if (!res.ok) return
        const data = await res.json()
        const logs = data.logs ?? []
        const tokenMap: Record<string, number> = {}
        const routeMap: Record<string, number> = {}
        for (const l of logs) {
          const sym = l.token_symbol || 'ETH'
          tokenMap[sym] = (tokenMap[sym] || 0) + (l.amount_human || 0)
          const rLabel = l.label || `Route #${l.rule_id}`
          routeMap[rLabel] = (routeMap[rLabel] || 0) + (l.amount_human || 0)
        }
        setTokenBreakdown(
          Object.entries(tokenMap)
            .map(([name, value]) => ({ name, value: parseFloat(value.toFixed(4)) }))
            .sort((a, b) => b.value - a.value)
        )
        setTopRoutes(
          Object.entries(routeMap)
            .map(([label, volume]) => ({ label, volume: parseFloat(volume.toFixed(4)) }))
            .sort((a, b) => b.volume - a.volume)
            .slice(0, 5)
        )
      } catch (err) {
        logger.error('CommandCenter', 'Fetch token breakdown failed', { error: String(err) })
      }
    }
    f()
  }, [address])

  const s = stats ?? {
    total_sweeps: 0, completed: 0, failed: 0,
    total_volume_eth: 0, total_volume_usd: 0, total_gas_spent_eth: 0,
    success_rate: 0, avg_sweep_time_sec: null,
  }

  // Traditional cost estimate: ~$5 per manual transfer
  const traditionalCost = s.total_sweeps * 5
  const actualCost = s.total_gas_spent_eth * ethPrice
  const feesSaved = Math.max(0, traditionalCost - actualCost)

  const statCards = [
    { label: t('totalRouted'), value: `${s.total_volume_eth.toFixed(4)} ETH`, sub: fiat(s.total_volume_eth, ethPrice), color: C.purple },
    { label: t('feesSaved'), value: `$${feesSaved.toFixed(0)}`, sub: `vs ~$5/transfer traditional`, color: C.green },
    { label: t('successRate'), value: `${s.success_rate}%`, sub: `${s.completed} of ${s.total_sweeps}`, color: s.success_rate >= 90 ? C.green : s.success_rate >= 70 ? C.amber : C.red },
    { label: t('avgTime'), value: s.avg_sweep_time_sec != null ? `${s.avg_sweep_time_sec.toFixed(1)}s` : '--', sub: t('perForward'), color: C.blue },
  ]

  const statusBreakdown = [
    { name: t('completed'), value: s.completed, color: C.green },
    { name: t('failed'), value: s.failed, color: C.red },
    { name: t('other'), value: Math.max(0, s.total_sweeps - s.completed - s.failed), color: C.amber },
  ].filter(x => x.value > 0)

  const periods: { key: Period; label: string }[] = [
    { key: '24h', label: '24h' },
    { key: '7d', label: '7d' },
    { key: '30d', label: '30d' },
    { key: 'all', label: t('all') },
  ]

  return (
    <div>
      {/* Period Selector */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        {periods.map(p => (
          <button
            key={p.key}
            onClick={() => setPeriod(p.key)}
            style={{
              padding: '6px 14px', borderRadius: 8, border: 'none',
              background: period === p.key ? `linear-gradient(135deg, ${C.red}, ${C.purple})` : 'rgba(10,10,10,0.04)',
              color: period === p.key ? '#fff' : C.dim,
              fontFamily: C.D, fontSize: 11, fontWeight: 600, cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Stat cards */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
          {[1, 2, 3, 4].map(i => <Sk key={i} w="100%" h={72} r={14} />)}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
          {statCards.map((c, i) => (
            <motion.div
              key={c.label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05, ...smooth }}
              style={{
                background: 'rgba(10,10,10,0.03)',
                border: `1px solid ${C.border}`,
                borderRadius: 14, padding: '12px 14px',
              }}
            >
              <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
                {c.label}
              </div>
              <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 700, color: c.color }}>
                {c.value}
              </div>
              <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 2 }}>
                {c.sub}
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {/* Volume AreaChart */}
      <div style={{
        background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
        borderRadius: 14, padding: '14px 12px 4px', marginBottom: 14,
      }}>
        <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub, marginBottom: 10 }}>
          {t('volume')} ({period === 'all' ? t('allTime') : period})
        </div>
        {!isVisible ? (
          <div style={{ height: 140 }} />
        ) : loading ? (
          <Sk w="100%" h={140} r={8} />
        ) : daily.length > 0 ? (
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={daily} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="ccVolumeGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.purple} stopOpacity={0.2} />
                  <stop offset="100%" stopColor={C.purple} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={['dataMin', 'dataMax']} />
              <Tooltip content={<ChartTip />} />
              <Area
                type="monotone"
                dataKey="volume_eth"
                name="Volume (ETH)"
                stroke={C.purple}
                strokeWidth={2}
                fill="url(#ccVolumeGrad)"
                dot={false}
                animationDuration={600}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: 140, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontFamily: C.M, fontSize: 11, color: C.dim }}>No data yet</span>
          </div>
        )}
      </div>

      {/* Top Routes */}
      <div style={{
        background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
        borderRadius: 14, padding: '14px 12px', marginBottom: 14,
      }}>
        <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub, marginBottom: 10 }}>
          Top Routes
        </div>
        {topRoutes.length > 0 ? topRoutes.map((r, i) => {
          const maxVol = topRoutes[0]?.volume || 1
          const pct = (r.volume / maxVol) * 100
          const col = PIE_COLORS[i % PIE_COLORS.length]
          return (
            <div key={r.label} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontFamily: C.M, fontSize: 10, color: C.text }}>{r.label}</span>
                <span style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>{r.volume} ETH</span>
              </div>
              <div style={{ height: 4, borderRadius: 2, background: 'rgba(10,10,10,0.04)' }}>
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.6, delay: i * 0.08, ease: EASE }}
                  style={{ height: '100%', borderRadius: 2, background: col }}
                />
              </div>
            </div>
          )
        }) : (
          <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>No data</span>
          </div>
        )}
      </div>

      {/* Two columns: PieChart + PieChart */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
        {/* Token Breakdown */}
        <div style={{
          background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
          borderRadius: 14, padding: '14px 8px',
        }}>
          <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub, marginBottom: 8, paddingLeft: 4 }}>
            Token Split
          </div>
          {!isVisible ? (
            <div style={{ height: 80 }} />
          ) : tokenBreakdown.length > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ResponsiveContainer width={80} height={80}>
                <PieChart>
                  <Pie data={tokenBreakdown} dataKey="value" innerRadius={20} outerRadius={35} paddingAngle={2} strokeWidth={0} animationDuration={600}>
                    {tokenBreakdown.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1 }}>
                {tokenBreakdown.map((t, i) => (
                  <div key={t.name} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: PIE_COLORS[i % PIE_COLORS.length] }} />
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.text }}>{t.name}</span>
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 'auto' }}>{t.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>No data</span>
            </div>
          )}
        </div>

        {/* Status Breakdown */}
        <div style={{
          background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
          borderRadius: 14, padding: '14px 8px',
        }}>
          <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub, marginBottom: 8, paddingLeft: 4 }}>
            Status
          </div>
          {!isVisible ? (
            <div style={{ height: 80 }} />
          ) : statusBreakdown.length > 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ResponsiveContainer width={80} height={80}>
                <PieChart>
                  <Pie data={statusBreakdown} dataKey="value" innerRadius={20} outerRadius={35} paddingAngle={2} strokeWidth={0} animationDuration={600}>
                    {statusBreakdown.map((s, i) => <Cell key={i} fill={s.color} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div style={{ flex: 1 }}>
                {statusBreakdown.map(s => (
                  <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: s.color }} />
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.text }}>{s.name}</span>
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 'auto' }}>{s.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>No data</span>
            </div>
          )}
        </div>
      </div>

      {/* Gas BarChart */}
      <div style={{
        background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
        borderRadius: 14, padding: '14px 12px 4px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub }}>
            {t('gasEfficiency')} ({period === 'all' ? t('allTime') : period})
          </span>
          {s.total_gas_spent_eth > 0 && (
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.amber }}>
              {s.total_gas_spent_eth.toFixed(6)} ETH total ({fiat(s.total_gas_spent_eth, ethPrice)})
            </span>
          )}
        </div>
        {!isVisible ? (
          <div style={{ height: 120 }} />
        ) : loading ? (
          <Sk w="100%" h={120} r={8} />
        ) : daily.length > 0 ? (
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={daily} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <XAxis dataKey="date" hide />
              <YAxis hide />
              <Tooltip content={<ChartTip />} />
              <Bar dataKey="gas_total" name="Gas (ETH)" fill={C.amber} radius={[4, 4, 0, 0]} animationDuration={600} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ fontFamily: C.M, fontSize: 11, color: C.dim }}>No data yet</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default AnalyticsTab
