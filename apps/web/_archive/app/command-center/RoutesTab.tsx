'use client'

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import dynamic from 'next/dynamic'
import RuleCard from '../RuleCard'
import { logger } from '../../lib/logger'
import type { ChainFamily } from '../../lib/chain-adapters/types'
import type { CreateRulePayload } from '../../lib/useForwardingRules'
import type {
  CreateSplitContractPayload,
  SimulateSplitPayload,
  SimulationResult,
  SplitContract,
} from '../../lib/useSplitContracts'
import { C, TabSkeleton } from './shared'

const RouteWizard = dynamic(() => import('./RouteWizard'), { ssr: false })

function RoutesTab({
  address, chainId, balance, ethPrice, rules, loading,
  createRule, createRuleBatch, createSplitContract, simulateSplit,
  updateRule, deleteRule, pauseRule, resumeRule,
  distLists, activeFamily, isMobile,
}: {
  address: string
  chainId: number
  balance: any
  ethPrice: number
  rules: any[]
  loading: boolean
  createRule: (p: CreateRulePayload) => Promise<any>
  createRuleBatch: (p: CreateRulePayload[]) => Promise<void>
  createSplitContract?: (p: CreateSplitContractPayload) => Promise<SplitContract>
  simulateSplit?: (p: SimulateSplitPayload) => Promise<SimulationResult>
  updateRule: (id: number, u: Record<string, any>) => Promise<void>
  deleteRule: (id: number) => Promise<void>
  pauseRule: (id: number) => Promise<void>
  resumeRule: (id: number) => Promise<void>
  distLists: any[]
  activeFamily: ChainFamily
  isMobile?: boolean
}) {
  const t = useTranslations('commandCenter.routes')

  // ── Non-EVM guard: auto-forwarding is EVM-only for now ──
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

  const [showWizard, setShowWizard] = useState(false)

  const handleToggle = async (id: number, active: boolean) => {
    try {
      await updateRule(id, { is_active: !active })
    } catch (err) {
      logger.error('CommandCenter', 'Toggle rule failed', { ruleId: String(id), error: String(err) })
    }
  }

  // Single portal instance — AnimatePresence inside so exit animation works after portal
  const wizardPortal = createPortal(
    <AnimatePresence>
      {showWizard && (
        <RouteWizard
          key="route-wizard"
          onClose={() => setShowWizard(false)}
          onCreate={createRule}
          onCreateBatch={createRuleBatch}
          onCreateSplitContract={createSplitContract}
          onSimulateSplit={simulateSplit}
          address={address}
          chainId={chainId}
          balance={balance}
          ethPrice={ethPrice}
          distLists={distLists}
          isMobile={isMobile}
        />
      )}
    </AnimatePresence>
  , document.body)

  // ── Empty state ────────────────────────────────────────
  if (!loading && rules.length === 0) {
    return (
      <>
        <EmptyState onStart={() => setShowWizard(true)} />
        {wizardPortal}
      </>
    )
  }

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.sub }}>
          {rules.length} Route{rules.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={() => setShowWizard(true)}
          style={{
            padding: '6px 14px', borderRadius: 10,
            background: `${C.purple}10`,
            border: `1px solid ${C.purple}25`,
            color: C.purple,
            fontFamily: C.D, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {t('newRoute')}
        </button>
      </div>

      {/* Rules grid */}
      {loading && rules.length === 0 ? (
        <TabSkeleton />
      ) : (
        <AnimatePresence initial={false}>
          {rules.map(r => (
            <RuleCard
              key={r.id}
              rule={r}
              onToggle={handleToggle}
              onPause={pauseRule}
              onResume={resumeRule}
              onDelete={deleteRule}
            />
          ))}
        </AnimatePresence>
      )}

      {/* Wizard portal */}
      {wizardPortal}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  EMPTY STATE
// ═══════════════════════════════════════════════════════════

function EmptyState({ onStart }: { onStart: () => void }) {
  const t = useTranslations('commandCenter.routes')
  return (
    <div className="text-center py-6">
      <svg width="120" height="78" viewBox="0 0 140 90" fill="none" className="mx-auto mb-4 block">
        <line x1="28" y1="45" x2="65" y2="22" stroke="rgba(200,81,44,0.3)" strokeWidth="1" strokeDasharray="3 3"/>
        <line x1="28" y1="45" x2="65" y2="68" stroke="rgba(200,81,44,0.3)" strokeWidth="1" strokeDasharray="3 3"/>
        <line x1="65" y1="22" x2="112" y2="45" stroke="rgba(200,81,44,0.3)" strokeWidth="1" strokeDasharray="3 3"/>
        <line x1="65" y1="68" x2="112" y2="45" stroke="rgba(200,81,44,0.3)" strokeWidth="1" strokeDasharray="3 3"/>
        <circle cx="28" cy="45" r="11" fill="#FCEBEB" stroke="#E24B4A" strokeWidth="1"/>
        <text x="28" y="49" textAnchor="middle" fontSize="10" fill="#A32D2D" fontWeight="500">W</text>
        <circle cx="65" cy="22" r="11" fill="#EAF3DE" stroke="#639922" strokeWidth="1"/>
        <text x="65" y="26" textAnchor="middle" fontSize="10" fill="#3B6D11" fontWeight="500">A</text>
        <circle cx="65" cy="68" r="11" fill="#E6F1FB" stroke="#378ADD" strokeWidth="1"/>
        <text x="65" y="72" textAnchor="middle" fontSize="10" fill="#185FA5" fontWeight="500">B</text>
        <circle cx="112" cy="45" r="11" fill="#FAECE7" stroke="#D85A30" strokeWidth="1"/>
        <text x="112" y="49" textAnchor="middle" fontSize="10" fill="#993C1D" fontWeight="500">C</text>
      </svg>
      <h3 className="text-[15px] font-medium text-[#2C2C2A] mb-1">{t('noRoutesYet')}</h3>
      {/* TODO(i18n): add `noRoutesYetDesc` key to messages/*.json */}
      <p className="text-[12px] text-[#888780] mx-auto mb-4 leading-[1.5] max-w-[340px]">
        Create a route to auto-forward incoming funds, split payments, or optimize gas.
      </p>
      <button
        type="button"
        onClick={onStart}
        className="px-[18px] py-[9px] bg-[#C8512C] text-white border-none rounded-[9px] text-[12px] font-medium hover:bg-[#B04424] transition-colors cursor-pointer"
      >
        {t('createFirstRoute')}
      </button>
    </div>
  )
}

export default RoutesTab
