'use client'

import { useState, useRef } from 'react'
import { useWriteContract, useChainId } from 'wagmi'
import { parseEther, getAddress } from 'viem'
import { motion } from 'framer-motion'
import type { ForwardingRule } from '../lib/useForwardingRules'
import { getRegistry } from '../lib/contractRegistry'
import { FEE_ROUTER_ABI, FEE_ROUTER_V6_ABI } from '../lib/feeRouterAbi'
import { mutationHeaders } from '../lib/rsendFetch'
import { C } from '@/app/designTokens'

function tr(a: string, s = 6, e = 4): string {
  return !a || a.length < s + e + 2 ? a : `${a.slice(0, s)}...${a.slice(-e)}`
}

function ago(ts: string | null): string {
  if (!ts) return '--'
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000)
  if (m < 1) return 'now'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`
}

interface Props {
  rule: ForwardingRule
  onToggle: (id: number, active: boolean) => void
  onPause: (id: number) => void
  onResume: (id: number) => void
  onDelete: (id: number) => Promise<void>
}

export default function RuleCard({ rule, onToggle, onPause, onResume, onDelete }: Props) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const busyRef = useRef(false)
  const isPaused = rule.is_paused
  const isActive = rule.is_active && !isPaused

  // ── On-chain execution (writeContractAsync → always opens MetaMask) ──
  const { writeContractAsync } = useWriteContract()
  const chainId = useChainId()
  const [signingState, setSigningState] = useState<'idle' | 'signing'>('idle')
  const isSigningRef = useRef(false)

  const handleConfirm = async () => {
    if (isSigningRef.current) return
    isSigningRef.current = true
    setSigningState('signing')
    setActionError(null)
    try {
      // Step 1: Oracle signature
      const registry = getRegistry(rule.chain_id || chainId)
      if (!registry) throw new Error(`Chain ${rule.chain_id || chainId} not supported`)

      const tokenAddr = rule.token_address || '0x0000000000000000000000000000000000000000'
      const isNative = tokenAddr === '0x0000000000000000000000000000000000000000'
      const amountWei = parseEther(String(rule.min_threshold || '0.001'))

      const oracleRes = await fetch('/api/oracle/sign', {
        method: 'POST',
        headers: mutationHeaders(),
        body: JSON.stringify({
          sender: rule.source_wallet,
          recipient: rule.destination_wallet,
          tokenIn: tokenAddr,
          tokenOut: tokenAddr,
          amountIn: String(rule.min_threshold || '0.001'),
          amountInWei: amountWei.toString(),
          symbol: rule.token_symbol || 'ETH',
          chainId: rule.chain_id || chainId,
        }),
        signal: AbortSignal.timeout(8000),
      })
      if (!oracleRes.ok) throw new Error('Oracle signature request failed')
      const oracle = await oracleRes.json()
      if (!oracle.approved) throw new Error(oracle.rejectionReason || 'Oracle denied')

      // M1 slice B: V5/V6 routers take a threshold bytes[] (oracleSignatures);
      // V4 takes a single bytes (oracleSignature).
      const isV6 = registry.version === 'v6'
      const routerAbi = isV6 ? FEE_ROUTER_V6_ABI : FEE_ROUTER_ABI
      const oracleSigArg = isV6
        ? (oracle.oracleSignatures as `0x${string}`[])
        : (oracle.oracleSignature as `0x${string}`)

      // Step 2: On-chain tx via MetaMask
      const recipientAddr = getAddress(rule.destination_wallet) as `0x${string}`

      if (isNative) {
        await writeContractAsync({
          address: registry.feeRouter,
          abi: routerAbi,
          functionName: 'transferETHWithOracle',
          args: [
            recipientAddr,
            oracle.oracleNonce as `0x${string}`,
            BigInt(oracle.oracleDeadline),
            oracleSigArg,
          ],
          value: amountWei,
        })
      } else {
        await writeContractAsync({
          address: registry.feeRouter,
          abi: routerAbi,
          functionName: 'transferWithOracle',
          args: [
            tokenAddr as `0x${string}`,
            amountWei,
            recipientAddr,
            oracle.oracleNonce as `0x${string}`,
            BigInt(oracle.oracleDeadline),
            oracleSigArg,
          ],
        })
      }
    } catch (err: any) {
      const isRejected =
        err?.code === 4001 ||
        err?.code === 'ACTION_REJECTED' ||
        /user (rejected|denied|cancelled)/i.test(err?.message ?? '')
      if (!isRejected) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error('[RuleCard] confirm failed:', msg)
        setActionError(msg)
      }
    } finally {
      isSigningRef.current = false
      setSigningState('idle')
    }
  }

  const guard = async (fn: () => Promise<void>) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setActionError(null)
    try {
      await fn()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      console.error('[RuleCard] action failed:', msg)
      setActionError(msg)
    } finally {
      setBusy(false)
      busyRef.current = false
    }
  }

  const safeDelete = () => guard(async () => {
    await onDelete(rule.id)
    setConfirmDelete(false)
  })

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      style={{
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${isPaused ? `${C.amber}20` : isActive ? `${C.green}15` : C.border}`,
        borderRadius: 14,
        padding: 14,
        marginBottom: 8,
        opacity: rule.is_active ? 1 : 0.5,
        transition: 'border-color 0.2s, opacity 0.2s',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <div style={{
            width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
            background: isPaused ? C.amber : isActive ? C.green : C.dim,
            boxShadow: isPaused ? `0 0 6px ${C.amber}50` : isActive ? `0 0 6px ${C.green}50` : 'none',
          }} />
          <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {rule.label || `Rule #${rule.id}`}
          </span>
          {isPaused && (
            <span style={{ fontFamily: C.M, fontSize: 8, color: C.amber, background: `${C.amber}12`, padding: '1px 5px', borderRadius: 4, flexShrink: 0 }}>
              PAUSED
            </span>
          )}
        </div>

        {/* Toggle switch */}
        <button
          onClick={() => guard(() => Promise.resolve(onToggle(rule.id, rule.is_active)))}
          style={{
            width: 34, height: 18, borderRadius: 9, border: 'none', cursor: 'pointer',
            background: isActive ? C.green : 'rgba(10,10,10,0.08)',
            position: 'relative', transition: 'background 0.2s', flexShrink: 0,
          }}
        >
          <div style={{
            width: 12, height: 12, borderRadius: '50%', background: '#fff',
            position: 'absolute', top: 3,
            left: isActive ? 19 : 3, transition: 'left 0.2s',
          }} />
        </button>
      </div>

      {/* Route info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ fontFamily: C.M, fontSize: 11, color: C.sub }}>{tr(rule.source_wallet)}</span>
        <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>-&gt;</span>
        <span style={{ fontFamily: C.M, fontSize: 11, color: C.text }}>{tr(rule.destination_wallet)}</span>
      </div>

      {/* Split info */}
      {rule.split_enabled && rule.split_destination && (
        <div style={{
          background: `${C.purple}08`, border: `1px solid ${C.purple}15`,
          borderRadius: 8, padding: '6px 10px', marginBottom: 8,
        }}>
          <div style={{ fontFamily: C.M, fontSize: 9, color: C.purple, marginBottom: 2 }}>SPLIT ROUTING</div>
          <div style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
            {rule.split_percent}% -&gt; Primary &middot; {100 - rule.split_percent}% -&gt; {tr(rule.split_destination)}
          </div>
        </div>
      )}

      {/* Params row */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
        <Tag label={`${rule.min_threshold} ${rule.token_symbol}`} />
        <Tag label={rule.gas_strategy} />
        <Tag label={`${rule.gas_limit_gwei} gwei`} />
        <Tag label={`${rule.cooldown_sec}s cd`} />
        {rule.max_daily_vol && <Tag label={`${rule.max_daily_vol} max/d`} />}
        {rule.auto_swap && <Tag label="Auto-swap" color={C.amber} />}
        {rule.notify_enabled && <Tag label={rule.notify_channel} color={C.blue} />}
      </div>

      {/* Error message */}
      {actionError && (
        <div style={{
          fontFamily: C.M, fontSize: 9, color: C.red,
          background: `${C.red}08`, border: `1px solid ${C.red}15`,
          borderRadius: 6, padding: '4px 8px', marginBottom: 8,
          wordBreak: 'break-word',
        }}>
          {actionError}
        </div>
      )}

      {/* Stats + actions */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 12 }}>
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
            {rule.sweep_count ?? 0} sweeps
          </span>
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
            Last: {ago(rule.last_sweep ?? null)}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {rule.is_active && (
            <ActionBtn
              label={signingState === 'signing' ? 'Signing...' : 'Confirm'}
              color={C.purple}
              disabled={signingState === 'signing' || busy}
              onClick={handleConfirm}
            />
          )}
          {rule.is_active && (
            <ActionBtn
              label={isPaused ? 'Resume' : 'Pause'}
              color={isPaused ? C.green : C.amber}
              disabled={busy}
              onClick={() => guard(async () => { isPaused ? await onResume(rule.id) : await onPause(rule.id) })}
            />
          )}
          {confirmDelete ? (
            <>
              <ActionBtn label={busy ? 'Check wallet...' : 'Confirm'} color={C.red} disabled={busy} onClick={safeDelete} />
              {!busy && <ActionBtn label="Cancel" color={C.dim} onClick={() => setConfirmDelete(false)} />}
            </>
          ) : (
            <ActionBtn label="Delete" color={C.red} disabled={busy} onClick={() => setConfirmDelete(true)} />
          )}
        </div>
      </div>
    </motion.div>
  )
}

function Tag({ label, color }: { label: string; color?: string }) {
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 9, color: color ?? 'rgba(10,10,10,0.55)',
      background: `${color ?? 'rgba(10,10,10,0.55)'}10`, padding: '2px 7px',
      borderRadius: 6, whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

function ActionBtn({ label, color, onClick, disabled }: { label: string; color: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      style={{
        padding: '3px 8px', borderRadius: 6, border: `1px solid ${color}25`,
        background: `${color}08`, color, cursor: disabled ? 'wait' : 'pointer',
        fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600,
        transition: 'all 0.15s',
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {label}
    </button>
  )
}
