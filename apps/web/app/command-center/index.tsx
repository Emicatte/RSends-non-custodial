'use client'

import { useState, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import dynamic from 'next/dynamic'
import { useAccount, useChainId, useBalance } from 'wagmi'
import { useUniversalWallet } from '../../hooks/useUniversalWallet'
import { useForwardingRules } from '../../lib/useForwardingRules'
import { useSplitContracts } from '../../lib/useSplitContracts'
import { useSweepWebSocket } from '../../lib/useSweepWebSocket'
import { useSweepStats } from '../../lib/useSweepStats'
import { useDistributionList } from '../../lib/useDistributionList'
import { useIsMobile } from '../../hooks/useIsMobile'
import { logger } from '../../lib/logger'

import { C, TABS, CHAIN_NAMES, fiat, TabSkeleton } from './shared'
import type { Tab } from './shared'

const RoutesTab = dynamic(() => import('./RoutesTab'), { loading: () => <TabSkeleton /> })
const SplitsTab = dynamic(() => import('./SplitsTab'), { loading: () => <TabSkeleton /> })
const MonitorTab = dynamic(() => import('./MonitorTab'), { loading: () => <TabSkeleton /> })
const HistoryTab = dynamic(() => import('./HistoryTab'), { loading: () => <TabSkeleton /> })
const AnalyticsTab = dynamic(() => import('./AnalyticsTab'), { loading: () => <TabSkeleton /> })
const GroupsTab = dynamic(() => import('./GroupsTab'), { loading: () => <TabSkeleton /> })
const SettingsTab = dynamic(() => import('./SettingsTab'), { loading: () => <TabSkeleton /> })


function FeatureCardsRow({ t }: { t: ReturnType<typeof useTranslations> }) {
  const cards = [
    { key: 'autoForward',  icon: <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><path d="M2 7h10M10 7l-2-2M10 7l-2 2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg> },
    { key: 'splitRouting', icon: <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><path d="M2 4l4 3-4 3M7 4l4 3-4 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg> },
    { key: 'smartGas',     icon: <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><path d="M7 2l-3 5h2l-1 5 4-6H7l1-4z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg> },
  ] as const
  return (
    <div className="grid grid-cols-3 gap-2">
      {cards.map(c => (
        <div key={c.key} className="bg-white border border-[rgba(200,81,44,0.2)] rounded-[10px] px-[13px] py-[11px]">
          <div className="flex items-center gap-[7px] mb-1.5">
            <span className="text-[#C8512C]">{c.icon}</span>
            <span className="text-[12px] font-medium text-[#2C2C2A]">{t(`routes.${c.key}`)}</span>
          </div>
          <div className="text-[11px] text-[#888780] leading-[1.4]">{t(`routes.${c.key}Desc`)}</div>
        </div>
      ))}
    </div>
  )
}


function StatInline({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={[
        'text-[10px] uppercase tracking-[0.4px] font-medium',
        highlight ? 'text-[#C8512C]' : 'text-[#888780]',
      ].join(' ')}>
        {label}
      </span>
      <span className="text-[12px] text-[#2C2C2A] font-mono font-medium">
        {value}
      </span>
    </div>
  )
}


export default function CommandCenter({
  ownerAddress,
  chainId: chainIdProp,
  isVisible = true,
  deepLink,
  onDeepLinkConsumed,
}: {
  ownerAddress?: string
  chainId?: number
  isVisible?: boolean
  deepLink?: string | null
  onDeepLinkConsumed?: () => void
}) {
  const t = useTranslations('commandCenter')
  const { address: hookAddr, isConnected } = useAccount()
  const hookChainId = useChainId()
  const address = ownerAddress ?? hookAddr
  const chainId = chainIdProp ?? hookChainId
  const { data: balance } = useBalance({ address: address as `0x${string}` | undefined })
  const wallet = useUniversalWallet()
  const isMobile = useIsMobile()

  const [tab, setTab] = useState<Tab>('routes')
  const [tabLoading, setTabLoading] = useState(false)
  const [settingsInitialSection, setSettingsInitialSection] = useState<string | null>(null)

  useEffect(() => {
    if (deepLink === 'apikeys') {
      setTab('settings')
      setSettingsInitialSection('apikeys')
      onDeepLinkConsumed?.()
    }
  }, [deepLink, onDeepLinkConsumed])

  // ── ETH price (derived from stats, fallback $3200) ────
  const [ethPrice, setEthPrice] = useState(3200)

  // ── Hooks ─────────────────────────────────────────────
  const {
    rules, loading: rulesLoading,
    createRule, createRuleBatch, updateRule, deleteRule,
    pauseRule, resumeRule, emergencyStop,
  } = useForwardingRules(address)

  // N-wallet split system (S2/S3) — coexists with legacy forwarding rules.
  const {
    contracts: splitContracts,
    loading: splitLoading,
    createContract: createSplitContract,
    deactivateContract: deactivateSplitContract,
    simulateSplit,
    listExecutions: listSplitExecutions,
    refresh: refreshSplitContracts,
  } = useSplitContracts(address)

  const { events, connected, wsStats } = useSweepWebSocket(address)
  const { stats, daily, loading: statsLoading } = useSweepStats(address)
  const { lists: distLists, loading: distLoading, createList: createDistList, deleteList: deleteDistList } = useDistributionList(address)

  // Derive ETH price from stats
  useEffect(() => {
    if (stats && stats.total_volume_eth > 0 && stats.total_volume_usd > 0) {
      setEthPrice(stats.total_volume_usd / stats.total_volume_eth)
    }
  }, [stats])

  // ── Gas price ─────────────────────────────────────────
  const [gas, setGas] = useState<number | null>(null)
  useEffect(() => {
    const f = async () => {
      try {
        const r = await fetch('https://mainnet.base.org', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_gasPrice', params: [] }),
        })
        setGas(parseInt((await r.json()).result, 16) / 1e9)
      } catch (err) {
        logger.warn('CommandCenter', 'Gas price fetch failed', { error: String(err) })
      }
    }
    f()
    const iv = setInterval(f, 15000)
    return () => clearInterval(iv)
  }, [])

  // ── Tab switch ────────────────────────────────────────
  const switchTab = (next: Tab) => {
    if (next === tab) return
    setTabLoading(true)
    setTab(next)
    setTimeout(() => setTabLoading(false), 300)
  }

  const activeRules = rules.filter(r => r.is_active && !r.is_paused).length

  const familyDot =
    wallet.activeFamily === 'evm'    ? '#378ADD' :
    wallet.activeFamily === 'solana' ? '#7F77DD' :
                                       '#E24B4A'

  const chainLabel =
    wallet.activeFamily === 'evm'    ? (CHAIN_NAMES[chainId] || 'EVM') :
    wallet.activeFamily === 'solana' ? 'Solana' :
                                       'TRON'

  const volumeDisplay = stats ? fiat(stats.total_volume_eth, ethPrice) : '—'
  const sweepsDisplay = stats ? String(stats.total_sweeps) : '—'
  const routesDisplay = String(activeRules)

  // ── Not connected (any chain family) ──────────────────
  if (!isConnected && !wallet.activeAddress) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <div style={{ fontFamily: C.D, fontSize: 15, fontWeight: 600, color: C.text, marginBottom: 4 }}>
          {t('connectWallet')}
        </div>
        <div style={{ fontFamily: C.M, fontSize: 11, color: C.dim }}>
          {t('toAccessFlow')}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full px-4 py-6">

      {/* Unified card: stats | sub-tabs | content */}
      <div className="rounded-2xl border border-[rgba(200,81,44,0.35)] bg-white overflow-hidden rp-stagger-host">

        {/* STATS STRIP — top row */}
        <div className="px-5 py-3 flex items-center justify-between gap-4 border-b border-[rgba(200,81,44,0.15)]">
          <div className="flex items-center gap-[7px]">
            <span className="w-[7px] h-[7px] rounded-full inline-block" style={{ backgroundColor: familyDot }} />
            <span className="text-[12px] font-medium text-[#2C2C2A]">{chainLabel}</span>
          </div>
          <div className="flex items-center gap-4">
            <StatInline label={t('stats.volume')} value={volumeDisplay} />
            <span className="w-px h-[14px] bg-[rgba(136,135,128,0.25)]" />
            <StatInline label={t('stats.sweeps')} value={sweepsDisplay} />
            <span className="w-px h-[14px] bg-[rgba(136,135,128,0.25)]" />
            <StatInline label={t('stats.routes')} value={routesDisplay} highlight />
          </div>
        </div>

        {/* SUB-TAB BAR — middle row */}
        <div className="px-3 py-2.5 flex justify-center border-b border-[rgba(200,81,44,0.15)]">
          <div className="inline-flex gap-[1px] p-[2px] rounded-lg bg-[rgba(200,81,44,0.04)]">
            {TABS.map(({ key }) => {
              const active = tab === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => switchTab(key)}
                  aria-current={active ? 'page' : undefined}
                  className={[
                    'px-3 py-[5px] text-[12px] rounded-md transition-colors font-display whitespace-nowrap',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(200,81,44,0.3)]',
                    active
                      ? 'bg-white text-[#C8512C] font-medium border border-[rgba(200,81,44,0.25)]'
                      : 'bg-transparent text-[#888780] font-normal border border-transparent hover:text-[#2C2C2A]',
                  ].join(' ')}
                >
                  {t(`tabs.${key}`)}
                </button>
              )
            })}
          </div>
        </div>

        {/* CONTENT — bottom row */}
        <div className="px-5 py-6">
          {tabLoading ? <TabSkeleton /> : (
            <>
              {tab === 'routes' && (
                <RoutesTab
                  address={address!}
                  chainId={chainId}
                  balance={balance}
                  ethPrice={ethPrice}
                  rules={rules}
                  loading={rulesLoading}
                  createRule={createRule}
                  createRuleBatch={createRuleBatch}
                  createSplitContract={createSplitContract}
                  simulateSplit={simulateSplit}
                  updateRule={updateRule}
                  deleteRule={deleteRule}
                  pauseRule={pauseRule}
                  resumeRule={resumeRule}
                  distLists={distLists}
                  activeFamily={wallet.activeFamily}
                  isMobile={isMobile}
                />
              )}
              {tab === 'splits' && (
                <SplitsTab
                  contracts={splitContracts}
                  loading={splitLoading}
                  deactivateContract={deactivateSplitContract}
                  listExecutions={listSplitExecutions}
                  refresh={refreshSplitContracts}
                  activeFamily={wallet.activeFamily}
                />
              )}
              {tab === 'monitor' && (
                <MonitorTab
                  gas={gas}
                  stats={stats}
                  activeRules={activeRules}
                  events={events}
                  connected={connected}
                  emergencyStop={emergencyStop}
                  ethPrice={ethPrice}
                  rules={rules}
                  wsStats={wsStats}
                  activeFamily={wallet.activeFamily}
                />
              )}
              {tab === 'history' && (
                <HistoryTab address={address!} ethPrice={ethPrice} stats={stats} rules={rules} activeFamily={wallet.activeFamily} walletAddress={wallet.activeAddress?.raw ?? null} />
              )}
              {tab === 'analytics' && (
                <AnalyticsTab stats={stats} daily={daily} loading={statsLoading} ethPrice={ethPrice} isVisible={isVisible} />
              )}
              {tab === 'groups' && (
                <GroupsTab
                  lists={distLists}
                  loading={distLoading}
                  createList={createDistList}
                  deleteList={deleteDistList}
                  activeFamily={wallet.activeFamily}
                />
              )}
              {tab === 'settings' && (
                <SettingsTab
                  address={address!}
                  chainId={chainId}
                  rules={rules}
                  emergencyStop={emergencyStop}
                  distLists={distLists}
                  distLoading={distLoading}
                  createDistList={createDistList}
                  deleteDistList={deleteDistList}
                  initialSection={settingsInitialSection as any}
                  onInitialSectionConsumed={() => setSettingsInitialSection(null)}
                />
              )}
            </>
          )}
        </div>

      </div>

      {/* FEATURE CARDS — separate slim row below */}
      <div className="mt-3">
        <FeatureCardsRow t={t} />
      </div>

    </div>
  )
}
