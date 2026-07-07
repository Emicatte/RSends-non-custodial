'use client'

/**
 * SplitsTab — N-wallet SplitContract management.
 *
 * Renders the list of SplitContracts for the connected wallet, with:
 *   • Locked badge (immutable after first execution)
 *   • Recipient breakdown with BPS share + role tags
 *   • Status indicators (active / locked / deactivated)
 *   • Audit trail: per-contract executions list (lazy-loaded)
 *   • Deactivate action (disabled if already deactivated)
 *
 * Coexists with the legacy Routes tab — does NOT touch ForwardingRules.
 * The 2-way legacy split path remains in Routes; the N-wallet path lives here.
 */

import { useState, useCallback, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import type {
  SplitContract,
  SplitExecution,
} from '../../lib/useSplitContracts'
import type { ChainFamily } from '../../lib/chain-adapters/types'
import { C, EASE, TabSkeleton, tr, fmtDate } from './shared'

const STATUS_COLORS: Record<string, string> = {
  pending:         C.amber,
  executing:       C.blue,
  completed:       C.green,
  partial_failure: C.amber,
  failed:          C.red,
}

function SplitsTab({
  contracts,
  loading,
  deactivateContract,
  listExecutions,
  refresh,
  activeFamily,
}: {
  contracts: SplitContract[]
  loading: boolean
  deactivateContract: (id: number) => Promise<any>
  listExecutions: (id: number, limit?: number) => Promise<SplitExecution[]>
  refresh: () => void
  activeFamily: ChainFamily
}) {
  const t = useTranslations('commandCenter.splits')

  // ── Non-EVM guard (split system is EVM-only for now) ──
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

  // Sort by created_at desc; locked → top isn't useful since most fresh ones aren't locked yet.
  const sorted = useMemo(() => {
    return [...contracts].sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0
      return tb - ta
    })
  }, [contracts])

  if (loading && contracts.length === 0) {
    return <TabSkeleton />
  }

  if (!loading && contracts.length === 0) {
    return <SplitsEmptyState />
  }

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.sub }}>
          {sorted.length} Split Contract{sorted.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={refresh}
          style={{
            padding: '6px 12px', borderRadius: 8,
            background: 'rgba(10,10,10,0.04)',
            border: `1px solid ${C.border}`,
            color: C.sub,
            fontFamily: C.M, fontSize: 10, cursor: 'pointer',
          }}
        >
          Refresh
        </button>
      </div>

      <AnimatePresence initial={false}>
        {sorted.map(c => (
          <SplitContractCard
            key={c.id}
            contract={c}
            deactivateContract={deactivateContract}
            listExecutions={listExecutions}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  Single contract card
// ═══════════════════════════════════════════════════════════

function SplitContractCard({
  contract,
  deactivateContract,
  listExecutions,
}: {
  contract: SplitContract
  deactivateContract: (id: number) => Promise<any>
  listExecutions: (id: number, limit?: number) => Promise<SplitExecution[]>
}) {
  const t = useTranslations('commandCenter.splits')
  const [expanded, setExpanded] = useState(false)
  const [executions, setExecutions] = useState<SplitExecution[] | null>(null)
  const [execLoading, setExecLoading] = useState(false)
  const [execError, setExecError] = useState<string | null>(null)
  const [deactivating, setDeactivating] = useState(false)

  const recipients = contract.recipients ?? []
  const totalBps = contract.total_bps ?? recipients.reduce((s, r) => s + r.share_bps, 0)

  const loadExecutions = useCallback(async () => {
    setExecLoading(true)
    setExecError(null)
    try {
      const data = await listExecutions(contract.id, 20)
      setExecutions(data)
    } catch (e) {
      setExecError(e instanceof Error ? e.message : String(e))
    } finally {
      setExecLoading(false)
    }
  }, [contract.id, listExecutions])

  const toggleExpand = useCallback(() => {
    const next = !expanded
    setExpanded(next)
    // Lazy-load executions on first expand
    if (next && executions === null && !execLoading) {
      loadExecutions()
    }
  }, [expanded, executions, execLoading, loadExecutions])

  const handleDeactivate = useCallback(async () => {
    if (deactivating) return
    if (!contract.is_active) return
    if (!confirm(`Deactivate split contract #${contract.id}? Incoming payments will no longer be split.`)) return
    setDeactivating(true)
    try {
      await deactivateContract(contract.id)
    } catch (e) {
      alert(`Failed to deactivate: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setDeactivating(false)
    }
  }, [contract.id, contract.is_active, deactivateContract, deactivating])

  // Status pill — three mutually exclusive states
  const statusInfo = !contract.is_active
    ? { label: 'DEACTIVATED', color: C.dim, bg: 'rgba(10,10,10,0.04)' }
    : contract.is_locked
      ? { label: 'LOCKED', color: C.amber, bg: `${C.amber}10` }
      : { label: 'ACTIVE', color: C.green, bg: `${C.green}10` }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.25, ease: EASE }}
      style={{
        background: 'rgba(10,10,10,0.04)',
        border: `1px solid ${C.border}`,
        borderRadius: 14,
        padding: '12px 14px',
        marginBottom: 10,
      }}
    >
      {/* ── Header row ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{
            fontFamily: C.D, fontSize: 12, fontWeight: 700, color: C.text,
            whiteSpace: 'nowrap',
          }}>
            #{contract.id}
          </span>
          <span style={{
            fontFamily: C.M, fontSize: 10, color: C.sub,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {contract.client_name || tr(contract.master_wallet)}
          </span>
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
            v{contract.version}
          </span>
        </div>

        {/* Status pill */}
        <span style={{
          fontFamily: C.M, fontSize: 8, fontWeight: 700,
          color: statusInfo.color, background: statusInfo.bg,
          padding: '3px 8px', borderRadius: 6,
          border: `1px solid ${statusInfo.color}25`,
          letterSpacing: '0.06em',
        }}>
          {statusInfo.label}
        </span>
      </div>

      {/* ── Master wallet + meta ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, marginTop: 6,
        fontFamily: C.M, fontSize: 9, color: C.dim,
      }}>
        <span>Master:</span>
        <code style={{ color: C.sub, fontSize: 9 }}>{tr(contract.master_wallet)}</code>
        <span>·</span>
        <span>Chain {contract.chain_id}</span>
        <span>·</span>
        <span>Fee {(contract.rsend_fee_bps / 100).toFixed(2)}%</span>
        {contract.locked_at && (
          <>
            <span>·</span>
            <span>Locked {fmtDate(contract.locked_at)}</span>
          </>
        )}
      </div>

      {/* ── Visual share bar ── */}
      {recipients.length > 0 && (
        <div style={{
          display: 'flex', height: 5, borderRadius: 3, overflow: 'hidden',
          marginTop: 10, marginBottom: 8,
        }}>
          {recipients.map((r, i) => (
            <div key={r.id} style={{
              flex: r.share_bps,
              background: [C.green, C.blue, C.purple, C.amber, C.red][i % 5],
            }} />
          ))}
        </div>
      )}

      {/* ── Recipients table ── */}
      {recipients.length > 0 && (
        <div>
          {recipients.map((r, i) => (
            <div key={r.id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '4px 0',
              borderBottom: i < recipients.length - 1 ? `1px solid ${C.border}` : 'none',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: [C.green, C.blue, C.purple, C.amber, C.red][i % 5],
                  flexShrink: 0,
                }} />
                <span style={{
                  fontFamily: C.M, fontSize: 10, color: C.text,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {r.label || tr(r.wallet_address)}
                </span>
                {r.role && r.role !== 'recipient' && (
                  <span style={{
                    fontFamily: C.M, fontSize: 7, color: C.dim,
                    padding: '1px 4px', borderRadius: 4,
                    background: 'rgba(10,10,10,0.04)',
                    flexShrink: 0,
                  }}>
                    {r.role}
                  </span>
                )}
              </div>
              <span style={{
                fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text,
                flexShrink: 0,
              }}>
                {r.share_percent}
              </span>
            </div>
          ))}

          {/* Total check — visible if backend reports a non-10000 sum */}
          {totalBps !== 10000 && (
            <div style={{
              fontFamily: C.M, fontSize: 9, color: C.red, marginTop: 6,
              padding: '4px 8px', background: `${C.red}08`, borderRadius: 6,
            }}>
              ⚠ Total BPS {totalBps} ≠ 10000 (server data inconsistency)
            </div>
          )}
        </div>
      )}

      {/* ── Action row ── */}
      <div style={{
        display: 'flex', gap: 8, marginTop: 10,
      }}>
        <button
          onClick={toggleExpand}
          style={{
            padding: '5px 10px', borderRadius: 8,
            background: 'rgba(10,10,10,0.04)',
            border: `1px solid ${C.border}`,
            color: C.sub,
            fontFamily: C.M, fontSize: 10, cursor: 'pointer',
          }}
        >
          {expanded ? t('hideAuditTrail') : t('viewAuditTrail')}
        </button>
        {contract.is_active && (
          <button
            onClick={handleDeactivate}
            disabled={deactivating}
            style={{
              padding: '5px 10px', borderRadius: 8,
              background: `${C.red}08`,
              border: `1px solid ${C.red}25`,
              color: C.red,
              fontFamily: C.M, fontSize: 10,
              cursor: deactivating ? 'not-allowed' : 'pointer',
              opacity: deactivating ? 0.5 : 1,
            }}
          >
            {deactivating ? t('deactivating') : t('deactivate')}
          </button>
        )}
      </div>

      {/* ── Audit trail (lazy) ── */}
      {expanded && (
        <div style={{
          marginTop: 10, paddingTop: 10,
          borderTop: `1px solid ${C.border}`,
        }}>
          <div style={{
            fontFamily: C.M, fontSize: 8, color: C.dim,
            textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8,
          }}>
            Execution audit trail
          </div>

          {execLoading && <TabSkeleton />}

          {execError && (
            <div style={{
              fontFamily: C.M, fontSize: 9, color: C.red,
              padding: '4px 8px', background: `${C.red}08`, borderRadius: 6,
            }}>
              {execError}
            </div>
          )}

          {!execLoading && !execError && executions !== null && executions.length === 0 && (
            <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, padding: '6px 0' }}>
              No executions yet. The first incoming payment to the master wallet will trigger this split.
            </div>
          )}

          {!execLoading && executions !== null && executions.length > 0 && executions.map(e => (
            <ExecutionRow key={e.id} execution={e} />
          ))}
        </div>
      )}
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════
//  Execution row (audit trail item)
// ═══════════════════════════════════════════════════════════

function ExecutionRow({ execution }: { execution: SplitExecution }) {
  const [expanded, setExpanded] = useState(false)
  const statusColor = STATUS_COLORS[execution.status] || C.dim
  const detail = execution.distribution_detail

  return (
    <div style={{
      padding: '6px 8px', marginBottom: 4,
      background: 'rgba(10,10,10,0.04)',
      borderRadius: 8, border: `1px solid ${C.border}`,
    }}>
      <div
        onClick={() => setExpanded(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%', background: statusColor, flexShrink: 0,
          }} />
          <span style={{
            fontFamily: C.M, fontSize: 9, color: C.sub,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {tr(execution.source_tx_hash, 8, 6)}
          </span>
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, flexShrink: 0 }}>
            {execution.input_amount} {execution.input_token}
          </span>
        </div>
        <span style={{
          fontFamily: C.M, fontSize: 8, fontWeight: 700,
          color: statusColor, padding: '2px 6px', borderRadius: 4,
          background: `${statusColor}10`, flexShrink: 0,
          letterSpacing: '0.04em',
        }}>
          {execution.status.toUpperCase()}
        </span>
      </div>

      {expanded && detail && Array.isArray(detail) && (
        <div style={{
          marginTop: 6, paddingTop: 6,
          borderTop: `1px solid ${C.border}`,
        }}>
          {detail.map((d, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '2px 0', fontFamily: C.M, fontSize: 9,
            }}>
              <span style={{
                color: C.sub,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                marginRight: 6,
              }}>
                {d.label || tr(d.wallet)} · {(d.share_bps / 100).toFixed(2)}%
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                <span style={{ color: STATUS_COLORS[d.status] || C.dim }}>
                  {d.status}
                </span>
                {d.tx_hash && (
                  <code style={{ color: C.dim, fontSize: 8 }}>{tr(d.tx_hash, 6, 4)}</code>
                )}
              </div>
            </div>
          ))}
          {execution.completed_at && (
            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, marginTop: 4 }}>
              Completed {fmtDate(execution.completed_at)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  Empty state
// ═══════════════════════════════════════════════════════════

function SplitsEmptyState() {
  return (
    <div style={{ textAlign: 'center', padding: '30px 20px' }}>
      <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 700, color: C.text, marginBottom: 8 }}>
        No split contracts yet
      </div>
      <div style={{ fontFamily: C.M, fontSize: 11, color: C.dim, lineHeight: 1.5, marginBottom: 16 }}>
        Create a route with 3+ destinations from the Routes tab to spawn an N-wallet split contract.<br/>
        Incoming payments to the master wallet will be split automatically.
      </div>
    </div>
  )
}


export default SplitsTab
