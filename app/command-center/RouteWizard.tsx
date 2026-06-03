'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { useWriteContract } from 'wagmi'
import { parseEther, parseUnits, formatUnits, getAddress } from 'viem'
import { getRegistry } from '../../lib/contractRegistry'
import { FEE_ROUTER_ABI, FEE_ROUTER_V6_ABI } from '../../lib/feeRouterAbi'
import type { CreateRulePayload } from '../../lib/useForwardingRules'
import type {
  CreateSplitContractPayload,
  SimulateSplitPayload,
  SimulationResult,
  SplitContract,
} from '../../lib/useSplitContracts'
import { mutationHeaders, parseRSendError } from '../../lib/rsendFetch'
import { logger } from '../../lib/logger'
import type { DistributionEntry } from '../../lib/useDistributionList'
import {
  C, EASE, RSEND_FEE_PCT, CHAIN_NAMES, TOKEN_OPTIONS,
  inp, selectStyle, labelStyle,
  Tip, ToggleSwitch, Sk, slideVariants,
} from './shared'
import type { WizardStep, DestMode, Destination, AdvancedSettings } from './shared'
import { DEFAULT_ADVANCED } from './shared'


// ── Local helpers (duplicated from CommandCenter.tsx) ──────

function tr(a: string, s = 6, e = 4): string {
  return !a || a.length < s + e + 2 ? a : `${a.slice(0, s)}...${a.slice(-e)}`
}

function isValidAddr(a: string): boolean {
  return /^0x[0-9a-fA-F]{40}$/.test(a)
}

function fiat(eth: number, price: number): string {
  const usd = eth * price
  if (usd >= 1000) return `$${(usd / 1000).toFixed(1)}k`
  if (usd >= 1) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(4)}`
}


// ═══════════════════════════════════════════════════════════
//  ROUTE WIZARD
// ═══════════════════════════════════════════════════════════

function RouteWizard({
  onClose, onCreate, onCreateBatch, onCreateSplitContract, onSimulateSplit,
  address, chainId, balance, ethPrice, distLists, isMobile,
}: {
  onClose: () => void
  onCreate: (p: CreateRulePayload) => Promise<any>
  onCreateBatch: (p: CreateRulePayload[]) => Promise<void>
  /**
   * N-wallet split path (S3): when destinations > 2, the wizard creates a
   * SplitContract via POST /api/v1/splits/contracts instead of N separate
   * ForwardingRules. Optional for backward compatibility: if not provided,
   * the wizard falls back to the legacy batch-of-rules path.
   */
  onCreateSplitContract?: (p: CreateSplitContractPayload) => Promise<SplitContract>
  /**
   * Pure simulation hook (POST /api/v1/splits/simulate). Used by Step 3 to
   * render a backend-computed preview of the distribution plan (BPS-exact
   * math + RSends fee). Optional: if absent, the static client-side preview
   * is used.
   */
  onSimulateSplit?: (p: SimulateSplitPayload) => Promise<SimulationResult>
  address: string
  chainId: number
  balance: any
  ethPrice: number
  distLists: any[]
  isMobile?: boolean
}) {
  const t = useTranslations('commandCenter.wizard')
  const [step, setStep] = useState<WizardStep>(1)
  const [direction, setDirection] = useState(1)

  // Step 2 state
  const [destMode, setDestMode] = useState<DestMode>('quick')
  const [destinations, setDestinations] = useState<Destination[]>([{ address: '', label: '', percent: 100, shareBps: 10000 }])
  const [csvText, setCsvText] = useState('')
  const [csvParsed, setCsvParsed] = useState<{ address: string; label: string; valid: boolean }[]>([])
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [advanced, setAdvanced] = useState<AdvancedSettings>({ ...DEFAULT_ADVANCED })

  // Step 3 state
  const [confirmed, setConfirmed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const savingRef = useRef(false)

  // On-chain signing via writeContractAsync (always opens MetaMask)
  const { writeContractAsync } = useWriteContract()

  // Active destinations (resolved from quick or bulk)
  const activeDests: Destination[] = useMemo(() => {
    if (destMode === 'quick') return destinations
    const valid = csvParsed.filter(r => r.valid)
    const n = valid.length
    if (n === 0) return []
    // BPS-aware even distribution: first gets the remainder so sum === 10000 exact
    const evenBps = Math.floor(10000 / n)
    const remainderBps = 10000 - evenBps * n
    return valid.map((r, i) => {
      const bps = i === 0 ? evenBps + remainderBps : evenBps
      return {
        address: r.address,
        label: r.label,
        percent: bps / 100,
        shareBps: bps,
      }
    })
  }, [destMode, destinations, csvParsed])

  const totalPercent = activeDests.reduce((s, d) => s + d.percent, 0)
  const activeTotalBps = activeDests.reduce((s, d) => s + (d.shareBps || Math.round(d.percent * 100)), 0)
  const activeBpsExact = activeTotalBps === 10000

  // Validation — BPS exact (no "close enough" for money)
  // Also reject duplicate recipient addresses: backend SplitContract rejects them,
  // and 2-way legacy splits would silently mean "send 100% to the same wallet twice".
  const activeAddrsLower = activeDests.map(d => d.address.toLowerCase())
  const noDuplicateAddrs = new Set(activeAddrsLower).size === activeAddrsLower.length
  const canNext2 = activeDests.length > 0 &&
    activeDests.every(d => isValidAddr(d.address)) &&
    noDuplicateAddrs &&
    (activeDests.length === 1 || activeBpsExact)

  // Navigation
  const goNext = () => { setDirection(1); setStep(s => Math.min(3, s + 1) as WizardStep) }
  const goBack = () => { setDirection(-1); setStep(s => Math.max(1, s - 1) as WizardStep) }

  // CSV parser
  const parseCsv = () => {
    const lines = csvText.trim().split('\n').filter(l => l.trim())
    const result = lines.map(line => {
      const parts = line.split(',').map(p => p.trim())
      const addr = parts[0] || ''
      const label = parts[1] || ''
      return { address: addr, label, valid: isValidAddr(addr) }
    })
    if (result.length > 1 && !result[0].valid && result[0].address.toLowerCase().includes('address')) {
      result.shift()
    }
    setCsvParsed(result)
  }

  // Build common payload fields from advanced settings
  const buildPayloadBase = (): Partial<CreateRulePayload> => ({
    owner_address: address,
    source_wallet: address,
    min_threshold: parseFloat(advanced.threshold) || 0.001,
    gas_strategy: advanced.speed === 'economy' ? 'slow' : advanced.speed,
    gas_limit_gwei: parseInt(advanced.maxGas) || 50,
    cooldown_sec: parseInt(advanced.cooldown) || 60,
    max_daily_vol: advanced.dailyLimit ? parseFloat(advanced.dailyLimit) : undefined,
    token_filter: advanced.tokenFilter.length > 0 ? advanced.tokenFilter : undefined,
    auto_swap: advanced.autoSwap,
    swap_to_token: advanced.autoSwap && advanced.swapTo.startsWith('0x') ? advanced.swapTo : undefined,
    notify_enabled: advanced.notifyEnabled,
    notify_channel: advanced.notifyChannel,
    telegram_chat_id: advanced.notifyChannel === 'telegram' && advanced.chatId ? advanced.chatId : undefined,
    email_address: advanced.notifyChannel === 'email' && advanced.email ? advanced.email : undefined,
    schedule_json: advanced.scheduleEnabled
      ? { days: advanced.schedDays, from: advanced.schedFrom, to: advanced.schedTo, tz: Intl.DateTimeFormat().resolvedOptions().timeZone }
      : undefined,
    chain_id: chainId,
  })

  // Create handler (ref guard prevents double-click)
  //
  // Two branches:
  //   • N-wallet split (N > 2 and onCreateSplitContract provided):
  //     SplitContract is backend-only config — no on-chain tx, no oracle sign.
  //     The actual split happens when a payment arrives at master_wallet
  //     (webhook → split_webhook_bridge → SplitExecutor).
  //   • Legacy 1/2-dest path:
  //     oracle sign → writeContractAsync (MetaMask opens) → backend rule creation.
  const handleCreate = async () => {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true)
    setError(null)
    try {
      const base = buildPayloadBase()
      const dests = activeDests

      // ═══════ N-wallet split path (N > 2) ═══════
      // SplitContract is backend-only config → skip oracle+on-chain entirely.
      if (dests.length > 2 && onCreateSplitContract) {
        // Invariante BPS: la somma di shareBps deve essere ESATTAMENTE 10000.
        // Già garantita da canNext2 (activeBpsExact) ma ri-verifichiamo qui per
        // difesa in profondità — meglio un errore client che un 400 dal backend.
        const totalBps = dests.reduce(
          (s, d) => s + (d.shareBps || Math.round(d.percent * 100)),
          0,
        )
        if (totalBps !== 10000) {
          throw new Error(
            `Split shares must sum to exactly 10000 BPS (100.00%), got ${totalBps}`,
          )
        }

        // Backend SplitContract rejects duplicate recipient addresses.
        // Re-check here so the user gets a clear client error instead of a 422.
        const lowered = dests.map(d => d.address.toLowerCase())
        if (new Set(lowered).size !== lowered.length) {
          throw new Error(t('duplicateAddressError'))
        }

        const splitPayload: CreateSplitContractPayload = {
          client_id: address.toLowerCase(),
          client_name: undefined,
          contract_ref: undefined,
          master_wallet: address.toLowerCase(),
          chain_id: chainId,
          rsend_fee_bps: 50, // TODO: wire to advanced settings once exposed in UI
          allowed_tokens: advanced.tokenFilter.length > 0 ? advanced.tokenFilter : [],
          recipients: dests.map((d, i) => ({
            wallet_address: d.address.toLowerCase(),
            label: d.label || '',
            role: d.role ?? (i === 0 ? 'primary' : 'recipient'),
            share_bps: d.shareBps || Math.round(d.percent * 100),
            position: i,
          })),
        }
        await onCreateSplitContract(splitPayload)
        onClose()
        return
      }

      // ═══════ Legacy 1- or 2-dest path ═══════
      const primaryDest = dests[0]

      // ── Step 1: Oracle signature ──────────────────────────
      const registry = getRegistry(chainId)
      if (!registry) throw new Error(`Chain ${chainId} not supported`)

      const tokenAddr = base.token_address || '0x0000000000000000000000000000000000000000'
      const isNative = tokenAddr === '0x0000000000000000000000000000000000000000'
      const threshold = base.min_threshold ?? 0.001
      const amountWei = isNative
        ? parseEther(String(threshold))
        : parseUnits(String(threshold), 18) // ERC-20 decimals resolved below

      const oracleRes = await fetch('/api/oracle/sign', {
        method: 'POST',
        headers: mutationHeaders(),
        body: JSON.stringify({
          sender: address,
          recipient: primaryDest.address,
          tokenIn: tokenAddr,
          tokenOut: tokenAddr,
          amountIn: String(threshold),
          amountInWei: amountWei.toString(),
          symbol: base.token_symbol || 'ETH',
          chainId,
        }),
        signal: AbortSignal.timeout(5000),
      })
      if (!oracleRes.ok) throw new Error(t('oracleRequestFailed'))
      const oracle = await oracleRes.json()
      if (!oracle.approved) throw new Error(oracle.rejectionReason || t('oracleDenied'))

      // M1 slice B: V5/V6 take a threshold bytes[]; V4 a single bytes.
      const isV6 = registry.version === 'v6'
      const routerAbi = isV6 ? FEE_ROUTER_V6_ABI : FEE_ROUTER_ABI
      const oracleSigArg = isV6
        ? (oracle.oracleSignatures as `0x${string}`[])
        : (oracle.oracleSignature as `0x${string}`)

      // ── Step 2: On-chain tx via MetaMask ──────────────────
      const recipientAddr = getAddress(primaryDest.address) as `0x${string}`
      let txHash: `0x${string}`

      if (isNative) {
        txHash = await writeContractAsync({
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
        txHash = await writeContractAsync({
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
      console.log('[RSend] Route confirmed on-chain:', txHash)

      // ── Step 3: Create rule in backend ────────────────────
      if (dests.length === 1) {
        await onCreate({
          ...base,
          destination_wallet: dests[0].address,
          label: dests[0].label || undefined,
          split_enabled: false,
          split_percent: 100,
        } as CreateRulePayload)
      } else if (dests.length === 2 && destMode === 'quick') {
        // Derive split_percent from canonical shareBps (BPS → percent)
        // Backend legacy 2-way split still uses split_percent, but we compute
        // it from the authoritative BPS value to preserve 0.01% precision.
        const primaryBps = dests[0].shareBps || Math.round(dests[0].percent * 100)
        await onCreate({
          ...base,
          destination_wallet: dests[0].address,
          label: dests[0].label || undefined,
          split_enabled: true,
          split_percent: primaryBps / 100,
          split_destination: dests[1].address,
        } as CreateRulePayload)
      } else {
        // ── Legacy fallback (N > 2 with no SplitContract wiring) ──
        // Reached only when onCreateSplitContract is not provided — the N>2
        // short-circuit above handles the normal split case.
        const payloads: CreateRulePayload[] = dests.map(d => ({
          ...base,
          destination_wallet: d.address,
          label: d.label || undefined,
          split_enabled: false,
          split_percent: 100,
        } as CreateRulePayload))
        await onCreateBatch(payloads)
      }
      onClose()
    } catch (e: any) {
      // User rejection in MetaMask is NOT an error — silently cancel
      const isUserRejection =
        e?.code === 4001 ||
        e?.code === 'ACTION_REJECTED' ||
        /user (rejected|denied|cancelled)/i.test(e?.message ?? '')
      if (!isUserRejection) {
        setError(e instanceof Error ? e.message : t('failedToCreateRoute'))
      }
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  // Load distribution group
  const loadGroup = (entries: DistributionEntry[]) => {
    setDestinations(entries.map(e => ({
      address: e.address,
      label: e.label,
      percent: e.percent,
      shareBps: Math.round(e.percent * 100),
    })))
    setDestMode('quick')
  }

  // Fix D — lock body scroll while modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      onClick={onClose} /* Fix E — close on backdrop click */
      style={{
        position: 'fixed', inset: 0,
        zIndex: 9999,
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(2px)',
        WebkitBackdropFilter: 'blur(2px)',
        display: 'flex', justifyContent: 'center', alignItems: isMobile ? 'stretch' : 'center',
      }}
    >
      {/* Modal panel */}
      <div
        onClick={e => e.stopPropagation()} /* Fix E — prevent panel clicks from closing */
        style={{
        ...(isMobile ? {
          width: '100%', maxWidth: '100%', height: '100dvh', maxHeight: '100dvh', borderRadius: 0,
        } : {
          width: '90%', maxWidth: 480, maxHeight: '90vh', borderRadius: 16,
        }),
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        position: 'relative',
        zIndex: 10000,
        boxSizing: 'border-box',
        background: C.card,
      }}>

        {/* ── Non-scrolling header: close + title + step bar ── */}
        <div style={{ padding: isMobile ? '16px 16px 0' : '20px 24px 0', flexShrink: 0 }}>
          {/* Close */}
          <button onClick={onClose} style={{
            position: 'absolute', top: 12, right: 12,
            background: 'none', border: 'none', color: C.dim, cursor: 'pointer',
            fontFamily: C.D, fontSize: 20, padding: 8,
          }}>{'\u2715'}</button>

          {/* Title */}
          <div style={{ fontFamily: C.D, fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 4 }}>
            Create Route
          </div>


          {/* Step bar */}
          <WizardStepBar step={step} />
        </div>

        {/* ── Scrollable body: step content + error ── */}
        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: isMobile ? '0 16px' : '0 24px' }}>
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={step}
              custom={direction}
              variants={slideVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.35, ease: EASE }}
              style={{ minHeight: 200 }}
            >
              {step === 1 && (
                <Step1Source address={address} chainId={chainId} balance={balance} ethPrice={ethPrice} />
              )}
              {step === 2 && (
                <Step2Destinations
                  destMode={destMode} setDestMode={setDestMode}
                  destinations={destinations} setDestinations={setDestinations}
                  csvText={csvText} setCsvText={setCsvText}
                  csvParsed={csvParsed} parseCsv={parseCsv}
                  showAdvanced={showAdvanced} setShowAdvanced={setShowAdvanced}
                  advanced={advanced} setAdvanced={setAdvanced}
                  ethPrice={ethPrice}
                  distLists={distLists} loadGroup={loadGroup}
                />
              )}
              {step === 3 && (
                <Step3Review
                  address={address}
                  destinations={activeDests}
                  ethPrice={ethPrice}
                  balance={balance}
                  advanced={advanced}
                  confirmed={confirmed}
                  setConfirmed={setConfirmed}
                  onSimulateSplit={onSimulateSplit}
                />
              )}
            </motion.div>
          </AnimatePresence>

          {/* Error */}
          {error && (
            <div style={{
              fontFamily: C.M, fontSize: 10, color: C.red, marginTop: 10,
              padding: '6px 10px', background: `${C.red}08`, borderRadius: 8,
            }}>
              {error}
            </div>
          )}
        </div>

        {/* ── Non-scrolling footer: navigation buttons ── */}
        <div style={{ padding: isMobile ? '0 16px 24px' : '0 24px 32px', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
            {step > 1 && (
              <motion.button
                whileTap={{ scale: 0.97 }}
                onClick={goBack}
                style={{
                  padding: '12px 20px', borderRadius: 12,
                  background: 'rgba(10,10,10,0.08)', border: `1px solid ${C.border}`,
                  color: C.sub, fontFamily: C.D, fontSize: 13, fontWeight: 600,
                  cursor: 'pointer', transition: 'all 0.15s',
                }}
              >
                Back
              </motion.button>
            )}
            <div style={{ flex: 1 }} />
            {step < 3 ? (
              <motion.button
                whileTap={{ scale: 0.97 }}
                onClick={goNext}
                disabled={step === 2 && !canNext2}
                style={{
                  padding: '12px 28px', borderRadius: 12, border: 'none',
                  background: (step === 2 && !canNext2)
                    ? 'rgba(10,10,10,0.04)'
                    : `linear-gradient(135deg, ${C.red}, ${C.purple})`,
                  color: (step === 2 && !canNext2) ? 'rgba(10,10,10,0.35)' : '#fff',
                  fontFamily: C.D, fontSize: 13, fontWeight: 700,
                  cursor: (step === 2 && !canNext2) ? 'not-allowed' : 'pointer',
                  boxShadow: (step === 2 && !canNext2) ? 'none' : `0 4px 20px ${C.purple}25`,
                  transition: 'all 0.2s',
                }}
              >
                Continue
              </motion.button>
            ) : (
              <motion.button
                whileTap={{ scale: 0.97 }}
                onClick={handleCreate}
                disabled={!confirmed || saving}
                style={{
                  padding: '12px 28px', borderRadius: 12, border: 'none',
                  background: (!confirmed || saving)
                    ? 'rgba(10,10,10,0.04)'
                    : `linear-gradient(135deg, ${C.red}, ${C.purple})`,
                  color: (!confirmed || saving) ? 'rgba(10,10,10,0.35)' : '#fff',
                  fontFamily: C.D, fontSize: 13, fontWeight: 700,
                  cursor: (!confirmed || saving) ? 'not-allowed' : 'pointer',
                  boxShadow: (!confirmed || saving) ? 'none' : `0 4px 20px ${C.purple}25`,
                  transition: 'all 0.2s',
                }}
              >
                {saving ? t('checkWalletToSign') : t('signAndCreateRoute')}
              </motion.button>
            )}
          </div>
        </div>

      </div>
    </motion.div>
  )
}


// ═══════════════════════════════════════════════════════════
//  WIZARD STEP BAR
// ═══════════════════════════════════════════════════════════

function WizardStepBar({ step }: { step: WizardStep }) {
  const t = useTranslations('commandCenter.wizard')
  const steps = [
    { n: 1, label: t('source') },
    { n: 2, label: t('destinations') },
    { n: 3, label: t('review') },
  ]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 28 }}>
      {steps.map((s, i) => (
        <div key={s.n} style={{ display: 'flex', alignItems: 'center', flex: i < steps.length - 1 ? 1 : 'none' }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: step >= s.n ? `linear-gradient(135deg, ${C.red}, ${C.purple})` : 'rgba(10,10,10,0.08)',
            color: step >= s.n ? '#fff' : C.dim,
            fontFamily: C.D, fontSize: 11, fontWeight: 700,
            transition: 'all 0.3s',
            boxShadow: step === s.n ? `0 0 12px ${C.purple}40` : 'none',
          }}>
            {step > s.n ? '\u2713' : s.n}
          </div>
          <span style={{
            fontFamily: C.M, fontSize: 9, color: step >= s.n ? C.text : C.dim,
            marginLeft: 6, whiteSpace: 'nowrap',
          }}>
            {s.label}
          </span>
          {i < steps.length - 1 && (
            <div style={{
              flex: 1, height: 2, marginLeft: 8, marginRight: 8, borderRadius: 1,
              background: step > s.n
                ? `linear-gradient(90deg, ${C.red}, ${C.purple})`
                : 'rgba(10,10,10,0.08)',
              transition: 'background 0.3s',
            }} />
          )}
        </div>
      ))}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  STEP 1 — SOURCE WALLET
// ═══════════════════════════════════════════════════════════

function Step1Source({
  address, chainId, balance, ethPrice,
}: {
  address: string; chainId: number; balance: any; ethPrice: number
}) {
  const bal = balance ? parseFloat(balance.formatted) : 0
  const chainName = CHAIN_NAMES[chainId] || `Chain ${chainId}`

  return (
    <div>
      <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Source Wallet
      </div>
      <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginBottom: 16 }}>
        Incoming funds to this wallet will be automatically forwarded
      </div>

      <div style={{
        background: 'rgba(10,10,10,0.03)',
        border: `1px solid ${C.purple}20`,
        borderRadius: 16, padding: '20px 18px',
      }}>
        {/* Address */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%',
            background: `linear-gradient(135deg, ${C.purple}30, ${C.blue}30)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="5" width="18" height="14" rx="3" stroke={C.purple} strokeWidth="1.5" />
              <path d="M3 10h18" stroke={C.purple} strokeWidth="1.5" />
            </svg>
          </div>
          <div>
            <div style={{ fontFamily: C.M, fontSize: 13, color: C.text, fontWeight: 600 }}>
              {tr(address, 8, 6)}
            </div>
            <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>
              Connected wallet
            </div>
          </div>
        </div>

        {/* Balance + Chain */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div style={{
            background: 'rgba(10,10,10,0.03)', borderRadius: 10, padding: '10px 12px',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
              Balance
            </div>
            <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 700, color: C.text }}>
              {bal.toFixed(4)} {balance?.symbol || 'ETH'}
            </div>
            <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>
              {fiat(bal, ethPrice)}
            </div>
          </div>
          <div style={{
            background: 'rgba(10,10,10,0.03)', borderRadius: 10, padding: '10px 12px',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
              Network
            </div>
            <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 700, color: C.text }}>
              {chainName}
            </div>
            <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>
              Chain ID {chainId}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  STEP 2 — DESTINATIONS
// ═══════════════════════════════════════════════════════════

function Step2Destinations({
  destMode, setDestMode, destinations, setDestinations,
  csvText, setCsvText, csvParsed, parseCsv,
  showAdvanced, setShowAdvanced, advanced, setAdvanced,
  ethPrice, distLists, loadGroup,
}: {
  destMode: DestMode; setDestMode: (m: DestMode) => void
  destinations: Destination[]; setDestinations: (d: Destination[]) => void
  csvText: string; setCsvText: (t: string) => void
  csvParsed: { address: string; label: string; valid: boolean }[]; parseCsv: () => void
  showAdvanced: boolean; setShowAdvanced: (fn: any) => void
  advanced: AdvancedSettings; setAdvanced: (fn: any) => void
  ethPrice: number
  distLists: any[]; loadGroup: (entries: DistributionEntry[]) => void
}) {
  const t = useTranslations('commandCenter.wizard')
  // BPS-aware totals (canonical) — exact to 0.01%
  const totalBps = destinations.reduce((s, d) => s + (d.shareBps || Math.round(d.percent * 100)), 0)
  const bpsExact = totalBps === 10000

  const addDest = () => {
    if (destinations.length >= 5) return
    // BPS-aware even split: first dest absorbs remainder so sum === 10000 exact
    const n = destinations.length + 1
    const evenBps = Math.floor(10000 / n)
    const remainderBps = 10000 - evenBps * n
    const updated = destinations.map((d, i) => {
      const bps = i === 0 ? evenBps + remainderBps : evenBps
      return { ...d, percent: bps / 100, shareBps: bps }
    })
    updated.push({ address: '', label: '', percent: evenBps / 100, shareBps: evenBps })
    setDestinations(updated)
  }

  const removeDest = (i: number) => {
    const next = destinations.filter((_, idx) => idx !== i)
    if (next.length === 1) {
      next[0] = { ...next[0], percent: 100, shareBps: 10000 }
    }
    setDestinations(next)
  }

  const updateDest = (i: number, field: keyof Destination, value: any) => {
    const next = [...destinations]
    if (field === 'percent') {
      // Sync canonical shareBps whenever percent changes (UI → BPS)
      const p = Math.max(0, Math.min(100, parseFloat(String(value)) || 0))
      next[i] = { ...next[i], percent: p, shareBps: Math.round(p * 100) }
    } else if (field === 'shareBps') {
      // Sync display percent whenever shareBps changes (BPS → UI)
      const bps = Math.max(0, Math.min(10000, parseInt(String(value)) || 0))
      next[i] = { ...next[i], shareBps: bps, percent: bps / 100 }
    } else {
      next[i] = { ...next[i], [field]: value }
    }
    setDestinations(next)
  }

  return (
    <div>
      <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Destinations
      </div>
      <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginBottom: 14 }}>
        Where should incoming funds be forwarded?
      </div>

      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        {(['quick', 'bulk'] as DestMode[]).map(m => (
          <button
            key={m}
            onClick={() => setDestMode(m)}
            style={{
              flex: 1, padding: '8px 0', borderRadius: 10,
              background: destMode === m ? `${C.purple}12` : 'rgba(10,10,10,0.03)',
              border: `1px solid ${destMode === m ? `${C.purple}30` : C.border}`,
              color: destMode === m ? C.purple : C.dim,
              fontFamily: C.D, fontSize: 11, fontWeight: 600, cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {m === 'quick' ? t('quickSetup') : t('csvImport')}
          </button>
        ))}
      </div>

      {/* Load from group */}
      {distLists.length > 0 && destMode === 'quick' && (
        <div style={{ marginBottom: 12 }}>
          <label style={labelStyle}>Load from saved group</label>
          <select
            onChange={e => {
              const list = distLists.find((l: any) => l.id === Number(e.target.value))
              if (list) loadGroup(list.entries)
            }}
            defaultValue=""
            style={selectStyle}
          >
            <option value="" disabled>Select a group...</option>
            {distLists.map((l: any) => (
              <option key={l.id} value={l.id}>{l.name} ({l.entries?.length} destinations)</option>
            ))}
          </select>
        </div>
      )}

      {/* Quick mode */}
      {destMode === 'quick' && (
        <div>
          {destinations.map((d, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05, duration: 0.3, ease: EASE }}
              style={{
                background: 'rgba(10,10,10,0.03)',
                border: `1px solid ${d.address && !isValidAddr(d.address) ? `${C.red}30` : C.border}`,
                borderRadius: 14, padding: '12px 14px', marginBottom: 8,
              }}
            >
              <div style={{ display: 'flex', gap: 8, marginBottom: destinations.length > 1 ? 10 : 0 }}>
                <div style={{ flex: 1 }}>
                  <label style={labelStyle}>Wallet Address</label>
                  <input
                    value={d.address}
                    onChange={e => updateDest(i, 'address', e.target.value)}
                    placeholder="0x..."
                    style={{
                      ...inp,
                      borderColor: d.address && !isValidAddr(d.address) ? `${C.red}60` : undefined,
                    }}
                  />
                  {d.address && !isValidAddr(d.address) && (
                    <div style={{ fontFamily: C.M, fontSize: 9, color: C.red, marginTop: 2 }}>
                      Invalid address
                    </div>
                  )}
                  {d.address && isValidAddr(d.address) && destinations.filter(
                    x => x.address && x.address.toLowerCase() === d.address.toLowerCase()
                  ).length > 1 && (
                    <div style={{ fontFamily: C.M, fontSize: 9, color: C.amber, marginTop: 2 }}>
                      Duplicate address
                    </div>
                  )}
                </div>
                <div style={{ width: 120 }}>
                  <label style={labelStyle}>Label</label>
                  <input
                    value={d.label}
                    onChange={e => updateDest(i, 'label', e.target.value)}
                    placeholder="Treasury"
                    style={inp}
                  />
                </div>
                {destinations.length > 1 && (
                  <button
                    onClick={() => removeDest(i)}
                    style={{
                      alignSelf: 'flex-end', marginBottom: 1,
                      width: 28, height: 28, borderRadius: 8,
                      background: `${C.red}08`, border: `1px solid ${C.red}20`,
                      color: C.red, cursor: 'pointer', fontFamily: C.M, fontSize: 14,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}
                  >
                    {'\u2715'}
                  </button>
                )}
              </div>

              {/* Percentage slider + precise numeric input (only when multiple dests) */}
              {destinations.length > 1 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {/* Precise numeric input — 0.01% (1 bps) precision */}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 2,
                    width: 72,
                    padding: '4px 6px', borderRadius: 8,
                    background: 'rgba(10,10,10,0.04)',
                    border: `1px solid ${C.border}`,
                  }}>
                    <input
                      type="number"
                      min={0} max={100} step="0.01"
                      value={d.percent}
                      onChange={e => updateDest(i, 'percent', e.target.value)}
                      style={{
                        width: '100%',
                        background: 'transparent', border: 'none', outline: 'none',
                        color: C.purple, fontFamily: C.D, fontSize: 12, fontWeight: 700,
                        textAlign: 'right', padding: 0,
                      }}
                    />
                    <span style={{
                      fontFamily: C.D, fontSize: 11, fontWeight: 700, color: C.purple,
                    }}>%</span>
                  </div>
                  <input
                    type="range"
                    min={0} max={100} step="0.01"
                    value={d.percent}
                    onChange={e => updateDest(i, 'percent', e.target.value)}
                    style={{ flex: 1, accentColor: C.purple, height: 4 }}
                  />
                </div>
              )}
            </motion.div>
          ))}

          {/* Add destination */}
          {destinations.length < 5 && (
            <button
              onClick={addDest}
              style={{
                width: '100%', padding: '10px 0', borderRadius: 10,
                background: 'transparent',
                border: `1px dashed ${C.dim}`,
                color: C.dim, fontFamily: C.D, fontSize: 11, fontWeight: 600,
                cursor: 'pointer', transition: 'all 0.15s',
                marginBottom: 8,
              }}
            >
              + Add Destination
            </button>
          )}

          {/* Total check — BPS exact (0.01% precision) */}
          {destinations.length > 1 && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 12px', borderRadius: 10,
              background: bpsExact ? `${C.green}08` : `${C.red}08`,
              border: `1px solid ${bpsExact ? `${C.green}20` : `${C.red}20`}`,
              marginBottom: 8,
            }}>
              <span style={{ fontFamily: C.M, fontSize: 11, color: bpsExact ? C.green : C.red }}>
                Total: {(totalBps / 100).toFixed(2)}%
              </span>
              {!bpsExact && (
                <span style={{ fontFamily: C.M, fontSize: 10, color: C.red }}>
                  {totalBps > 10000
                    ? `${((totalBps - 10000) / 100).toFixed(2)}% over`
                    : `${((10000 - totalBps) / 100).toFixed(2)}% under`}
                </span>
              )}
            </div>
          )}

          {/* Precise BPS error — shown inline under the total bar */}
          {destinations.length > 1 && !bpsExact && (
            <div style={{
              fontFamily: C.M, fontSize: 10, color: C.red, marginTop: 4, marginBottom: 8,
            }}>
              Total must be exactly 100.00% — currently {(totalBps / 100).toFixed(2)}%
            </div>
          )}
        </div>
      )}

      {/* Bulk CSV mode */}
      {destMode === 'bulk' && (
        <div>
          <label style={labelStyle}>Paste CSV (address, label per line)</label>
          <textarea
            value={csvText}
            onChange={e => setCsvText(e.target.value)}
            placeholder={'0x1234...abcd, Treasury\n0x5678...efgh, Savings'}
            rows={5}
            style={{
              ...inp, resize: 'vertical', minHeight: 80,
              fontFamily: C.M, fontSize: 11, lineHeight: 1.6,
            }}
          />
          <button
            onClick={parseCsv}
            disabled={!csvText.trim()}
            style={{
              marginTop: 8, padding: '8px 16px', borderRadius: 10,
              background: csvText.trim() ? `${C.blue}12` : 'rgba(10,10,10,0.03)',
              border: `1px solid ${csvText.trim() ? `${C.blue}25` : C.border}`,
              color: csvText.trim() ? C.blue : C.dim,
              fontFamily: C.D, fontSize: 11, fontWeight: 600, cursor: csvText.trim() ? 'pointer' : 'not-allowed',
              transition: 'all 0.15s',
            }}
          >
            Parse CSV
          </button>

          {/* Preview table */}
          {csvParsed.length > 0 && (
            <div style={{
              marginTop: 10, background: 'rgba(10,10,10,0.03)',
              border: `1px solid ${C.border}`, borderRadius: 12, overflow: 'hidden',
            }}>
              <div style={{
                display: 'grid', gridTemplateColumns: '24px 1fr 1fr',
                gap: 6, padding: '6px 10px',
                borderBottom: `1px solid ${C.border}`,
                background: 'rgba(10,10,10,0.04)',
              }}>
                <span style={{ fontFamily: C.M, fontSize: 8, color: C.dim }}></span>
                <span style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase' }}>Address</span>
                <span style={{ fontFamily: C.M, fontSize: 8, color: C.dim, textTransform: 'uppercase' }}>Label</span>
              </div>
              {csvParsed.map((row, i) => (
                <div key={i} style={{
                  display: 'grid', gridTemplateColumns: '24px 1fr 1fr',
                  gap: 6, padding: '6px 10px',
                  borderBottom: i < csvParsed.length - 1 ? `1px solid ${C.border}` : 'none',
                }}>
                  <span style={{ fontFamily: C.M, fontSize: 11, color: row.valid ? C.green : C.red }}>
                    {row.valid ? '\u2713' : '\u2717'}
                  </span>
                  <span style={{ fontFamily: C.M, fontSize: 10, color: row.valid ? C.text : C.red, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {tr(row.address, 10, 6)}
                  </span>
                  <span style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
                    {row.label || '--'}
                  </span>
                </div>
              ))}
              <div style={{ padding: '6px 10px', background: 'rgba(10,10,10,0.04)' }}>
                <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
                  {csvParsed.filter(r => r.valid).length} valid / {csvParsed.length} total
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Advanced Settings Accordion ──────────────── */}
      <div style={{ marginTop: 14 }}>
        <button
          onClick={() => setShowAdvanced((v: boolean) => !v)}
          style={{
            width: '100%', padding: '10px 14px', borderRadius: 12,
            background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
            color: C.sub, fontFamily: C.D, fontSize: 11, fontWeight: 600,
            cursor: 'pointer', textAlign: 'left',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}
        >
          <span>Advanced Settings</span>
          <span style={{ fontSize: 10, transition: 'transform 0.2s', transform: showAdvanced ? 'rotate(180deg)' : 'none' }}>
            {'\u25BE'}
          </span>
        </button>
        <AnimatePresence>
          {showAdvanced && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
              style={{ overflow: 'hidden' }}
            >
              <AdvancedAccordion settings={advanced} onChange={setAdvanced} ethPrice={ethPrice} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  ADVANCED ACCORDION
// ═══════════════════════════════════════════════════════════

function AdvancedAccordion({
  settings, onChange, ethPrice,
}: {
  settings: AdvancedSettings
  onChange: (fn: (s: AdvancedSettings) => AdvancedSettings) => void
  ethPrice: number
}) {
  const t = useTranslations('commandCenter.wizard')
  const upd = (field: keyof AdvancedSettings, value: any) =>
    onChange(s => ({ ...s, [field]: value }))

  return (
    <div style={{
      padding: '14px', marginTop: 6,
      background: 'rgba(10,10,10,0.04)',
      border: `1px solid ${C.border}`,
      borderRadius: 12,
    }}>
      {/* Threshold */}
      <div style={{ marginBottom: 10 }}>
        <Tip text={t('tipMinAmount')}>
          <label style={labelStyle}>Minimum Amount (ETH)</label>
        </Tip>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="number"
            value={settings.threshold}
            onChange={e => upd('threshold', e.target.value)}
            step="0.001" style={{ ...inp, flex: 1 }}
          />
          <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, whiteSpace: 'nowrap' }}>
            {fiat(parseFloat(settings.threshold) || 0, ethPrice)}
          </span>
        </div>
      </div>

      {/* Token filter */}
      <div style={{ marginBottom: 10 }}>
        <Tip text={t('tipTokenFilter')}>
          <label style={labelStyle}>Token Filter</label>
        </Tip>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {TOKEN_OPTIONS.map(t => {
            const on = settings.tokenFilter.includes(t)
            return (
              <button
                key={t}
                onClick={() => onChange(s => ({
                  ...s,
                  tokenFilter: on ? s.tokenFilter.filter(x => x !== t) : [...s.tokenFilter, t],
                }))}
                style={{
                  padding: '4px 10px', borderRadius: 8,
                  background: on ? `${C.purple}15` : 'rgba(10,10,10,0.03)',
                  border: `1px solid ${on ? `${C.purple}30` : C.border}`,
                  color: on ? C.purple : C.dim,
                  fontFamily: C.M, fontSize: 10, fontWeight: 600, cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {t}
              </button>
            )
          })}
        </div>
      </div>

      {/* Speed */}
      <div style={{ marginBottom: 10 }}>
        <Tip text={t('tipGasStrategy')}>
          <label style={labelStyle}>Speed</label>
        </Tip>
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            { key: 'economy' as const, label: t('economy'), desc: t('lowerFees') },
            { key: 'normal' as const, label: t('normal'), desc: t('balanced') },
            { key: 'fast' as const, label: t('fast'), desc: t('priority') },
          ].map(opt => (
            <button
              key={opt.key}
              onClick={() => upd('speed', opt.key)}
              style={{
                flex: 1, padding: '8px 6px', borderRadius: 10,
                background: settings.speed === opt.key ? `${C.purple}12` : 'rgba(10,10,10,0.03)',
                border: `1px solid ${settings.speed === opt.key ? `${C.purple}30` : C.border}`,
                color: settings.speed === opt.key ? C.purple : C.sub,
                fontFamily: C.D, fontSize: 10, fontWeight: 600, cursor: 'pointer',
                textAlign: 'center', transition: 'all 0.15s',
              }}
            >
              <div>{opt.label}</div>
              <div style={{ fontFamily: C.M, fontSize: 8, color: C.dim, marginTop: 2 }}>{opt.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Max Gas + Cooldown */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 10 }}>
        <div>
          <Tip text={t('tipMaxGas')}>
            <label style={labelStyle}>Max Gas (gwei)</label>
          </Tip>
          <input type="number" value={settings.maxGas} onChange={e => upd('maxGas', e.target.value)} style={inp} />
        </div>
        <div>
          <Tip text={t('tipCooldown')}>
            <label style={labelStyle}>Wait Time (sec)</label>
          </Tip>
          <input type="number" value={settings.cooldown} onChange={e => upd('cooldown', e.target.value)} style={inp} />
        </div>
      </div>

      {/* Daily limit */}
      <div style={{ marginBottom: 10 }}>
        <Tip text={t('tipDailyLimit')}>
          <label style={labelStyle}>Daily Limit (ETH)</label>
        </Tip>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="number"
            value={settings.dailyLimit}
            onChange={e => upd('dailyLimit', e.target.value)}
            placeholder="No limit"
            style={{ ...inp, flex: 1 }}
          />
          {settings.dailyLimit && (
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, whiteSpace: 'nowrap' }}>
              {fiat(parseFloat(settings.dailyLimit) || 0, ethPrice)}
            </span>
          )}
        </div>
      </div>

      {/* Auto-swap */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: settings.autoSwap ? 8 : 10 }}>
        <Tip text={t('tipAutoSwap')}>
          <span style={{ fontFamily: C.D, fontSize: 11, color: C.sub }}>Auto-Swap</span>
        </Tip>
        <ToggleSwitch value={settings.autoSwap} onChange={v => upd('autoSwap', v)} />
      </div>
      {settings.autoSwap && (
        <div style={{ marginBottom: 10 }}>
          <label style={labelStyle}>Swap to Token Address</label>
          <input value={settings.swapTo} onChange={e => upd('swapTo', e.target.value)} placeholder="0x..." style={inp} />
        </div>
      )}

      {/* Schedule */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: settings.scheduleEnabled ? 8 : 10 }}>
        <Tip text={t('tipSchedule')}>
          <span style={{ fontFamily: C.D, fontSize: 11, color: C.sub }}>Schedule</span>
        </Tip>
        <ToggleSwitch value={settings.scheduleEnabled} onChange={v => upd('scheduleEnabled', v)} />
      </div>
      {settings.scheduleEnabled && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => {
              const on = settings.schedDays.includes(d.toLowerCase())
              return (
                <button
                  key={d}
                  onClick={() => onChange(s => ({
                    ...s,
                    schedDays: on ? s.schedDays.filter(x => x !== d.toLowerCase()) : [...s.schedDays, d.toLowerCase()],
                  }))}
                  style={{
                    padding: '4px 8px', borderRadius: 6,
                    background: on ? `${C.blue}15` : 'rgba(10,10,10,0.03)',
                    border: `1px solid ${on ? `${C.blue}30` : C.border}`,
                    color: on ? C.blue : C.dim,
                    fontFamily: C.M, fontSize: 9, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {d}
                </button>
              )
            })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            <div>
              <label style={labelStyle}>From</label>
              <input type="time" value={settings.schedFrom} onChange={e => upd('schedFrom', e.target.value)} style={inp} />
            </div>
            <div>
              <label style={labelStyle}>To</label>
              <input type="time" value={settings.schedTo} onChange={e => upd('schedTo', e.target.value)} style={inp} />
            </div>
          </div>
        </div>
      )}

      {/* Notifications */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: settings.notifyEnabled ? 8 : 0 }}>
        <Tip text={t('tipNotifications')}>
          <span style={{ fontFamily: C.D, fontSize: 11, color: C.sub }}>Notifications</span>
        </Tip>
        <ToggleSwitch value={settings.notifyEnabled} onChange={v => upd('notifyEnabled', v)} />
      </div>
      {settings.notifyEnabled && (
        <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr', gap: 6 }}>
          <div>
            <label style={labelStyle}>Channel</label>
            <select value={settings.notifyChannel} onChange={e => upd('notifyChannel', e.target.value)} style={selectStyle}>
              <option value="telegram">Telegram</option>
              <option value="email">Email</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>{settings.notifyChannel === 'telegram' ? 'Chat ID' : 'Email'}</label>
            {settings.notifyChannel === 'telegram' ? (
              <input value={settings.chatId} onChange={e => upd('chatId', e.target.value)} placeholder="123456789" style={inp} />
            ) : (
              <input value={settings.email} onChange={e => upd('email', e.target.value)} placeholder="you@example.com" type="email" style={inp} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  STEP 3 — REVIEW
// ═══════════════════════════════════════════════════════════

function Step3Review({
  address, destinations, ethPrice, balance, advanced, confirmed, setConfirmed,
  onSimulateSplit,
}: {
  address: string
  destinations: Destination[]
  ethPrice: number
  balance: any
  advanced: AdvancedSettings
  confirmed: boolean
  setConfirmed: (v: boolean) => void
  onSimulateSplit?: (p: SimulateSplitPayload) => Promise<SimulationResult>
}) {
  const t = useTranslations('commandCenter.wizard')
  const userBal = balance ? parseFloat(balance.formatted) : 0
  const exampleEth = userBal > 0 ? userBal : 1
  const fee = exampleEth * RSEND_FEE_PCT / 100
  const afterFee = exampleEth - fee
  const total = destinations.reduce((s, d) => s + d.percent, 0)

  // ── Live simulation via POST /api/v1/splits/simulate ──
  // Backend-computed BPS-exact preview, only when N>2 and the simulation
  // hook is wired. Falls back gracefully to the static client preview.
  const [simulation, setSimulation] = useState<SimulationResult | null>(null)
  const [simLoading, setSimLoading] = useState(false)
  const [simError, setSimError] = useState<string | null>(null)

  // Derive token + decimals heuristically from advanced.tokenFilter
  // (USDC=6, USDT=6, DAI=18, ETH/WETH=18, fallback to USDC).
  // We compute the preview "per 100 units" to match the existing static UX.
  const previewToken = advanced.tokenFilter[0] || 'USDC'
  const previewDecimals = (() => {
    const t = previewToken.toUpperCase()
    if (t === 'USDC' || t === 'USDT') return 6
    return 18
  })()

  // Stable signature of recipients for the effect dep — avoids re-fetching
  // on every render when destinations[] is the same content.
  const recipientsKey = useMemo(
    () => destinations.map(d =>
      `${d.address}:${d.shareBps || Math.round(d.percent * 100)}:${d.label || ''}:${d.role || ''}`
    ).join('|'),
    [destinations],
  )

  useEffect(() => {
    // Only simulate when:
    //   • the simulation hook is provided (i.e., split-system path),
    //   • we have N>2 destinations (the path that maps to a SplitContract),
    //   • every recipient has a valid EVM address,
    //   • all recipient addresses are unique (backend rejects duplicates),
    //   • the BPS sum is exactly 10000 (otherwise the backend will 400).
    if (!onSimulateSplit) return
    if (destinations.length <= 2) {
      setSimulation(null)
      setSimError(null)
      return
    }
    if (!destinations.every(d => isValidAddr(d.address))) {
      setSimulation(null)
      setSimError(null)
      return
    }
    const lowered = destinations.map(d => d.address.toLowerCase())
    if (new Set(lowered).size !== lowered.length) {
      setSimulation(null)
      setSimError(null)
      return
    }
    const totalBps = destinations.reduce(
      (s, d) => s + (d.shareBps || Math.round(d.percent * 100)),
      0,
    )
    if (totalBps !== 10000) {
      setSimulation(null)
      setSimError(null)
      return
    }

    let cancelled = false
    setSimLoading(true)
    setSimError(null)

    onSimulateSplit({
      amount: '100',
      token: previewToken,
      decimals: previewDecimals,
      rsend_fee_bps: 50,
      recipients: destinations.map((d, i) => ({
        wallet_address: d.address,
        label: d.label || '',
        role: d.role ?? (i === 0 ? 'primary' : 'recipient'),
        share_bps: d.shareBps || Math.round(d.percent * 100),
        position: i,
      })),
    })
      .then(res => { if (!cancelled) setSimulation(res) })
      .catch(err => {
        if (!cancelled) {
          setSimError(err instanceof Error ? err.message : String(err))
          setSimulation(null)
        }
      })
      .finally(() => { if (!cancelled) setSimLoading(false) })

    return () => { cancelled = true }
    // recipientsKey is the stable identity proxy for `destinations`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipientsKey, previewToken, previewDecimals, onSimulateSplit])

  return (
    <div>
      <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Review Route
      </div>
      <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginBottom: 16 }}>
        Verify your configuration before signing
      </div>

      {/* ── Animated Flow Diagram ──────────────────── */}
      <FlowDiagram address={address} destinations={destinations} />

      {/* ── Split Preview — visual distribution per 100 token units ── */}
      {/*                                                                 */}
      {/* Two modes:                                                      */}
      {/*   1. LIVE — when destinations > 2 and onSimulateSplit is wired, */}
      {/*      we render the BPS-exact plan returned by                   */}
      {/*      POST /api/v1/splits/simulate (authoritative backend math). */}
      {/*   2. STATIC — for 2-dest splits (legacy 2-way path) we keep the */}
      {/*      client-side preview based on shareBps.                     */}
      {destinations.length > 1 && (
        <div style={{
          padding: 12, borderRadius: 12,
          background: 'rgba(10,10,10,0.04)',
          border: `1px solid ${C.border}`,
          marginBottom: 10,
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 8,
          }}>
            <div style={{
              fontFamily: C.M, fontSize: 8, color: C.dim,
              textTransform: 'uppercase', letterSpacing: '0.08em',
            }}>
              {simulation
                ? `Split Preview · live (per 100 ${simulation.input.token})`
                : `Split Preview (per 100 ${previewToken})`
              }
            </div>
            {simulation && (
              <span style={{
                fontFamily: C.M, fontSize: 7, color: C.green,
                padding: '1px 6px', borderRadius: 4,
                background: `${C.green}10`,
                border: `1px solid ${C.green}25`,
              }}>
                BACKEND
              </span>
            )}
            {simLoading && !simulation && (
              <span style={{ fontFamily: C.M, fontSize: 8, color: C.dim }}>simulating…</span>
            )}
          </div>

          {/* ── Visual bar ── */}
          <div style={{
            display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden',
            marginBottom: 8,
          }}>
            {(simulation
              ? simulation.recipients.map(r => ({ flex: r.share_bps }))
              : destinations.map(d => ({ flex: d.shareBps || Math.round(d.percent * 100) }))
            ).map((row, i) => (
              <div key={i} style={{
                flex: row.flex,
                background: [C.green, C.blue, C.purple, C.amber, C.red][i % 5],
                transition: 'flex 0.3s',
              }} />
            ))}
          </div>

          {/* ── Table ── */}
          {simulation
            ? simulation.recipients.map((r, i) => (
                <div key={i} style={{
                  display: 'flex', justifyContent: 'space-between',
                  padding: '4px 0',
                  borderBottom: i < simulation.recipients.length - 1 ? `1px solid ${C.border}` : 'none',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: [C.green, C.blue, C.purple, C.amber, C.red][i % 5],
                    }} />
                    <span style={{ fontFamily: C.M, fontSize: 10, color: C.text }}>
                      {r.label || tr(r.wallet)}
                    </span>
                    {r.role && r.role !== 'primary' && r.role !== 'recipient' && (
                      <span style={{
                        fontFamily: C.M, fontSize: 7, color: C.dim,
                        padding: '1px 4px', borderRadius: 4,
                        background: 'rgba(10,10,10,0.04)',
                      }}>
                        {r.role}
                      </span>
                    )}
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text }}>
                      {r.share_percent}
                    </span>
                    <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 6 }}>
                      ({r.amount_human})
                    </span>
                  </div>
                </div>
              ))
            : destinations.map((d, i) => {
                const bps = d.shareBps || Math.round(d.percent * 100)
                const sampleAmount = (bps / 100).toFixed(2) // Per 100 units
                return (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between',
                    padding: '4px 0',
                    borderBottom: i < destinations.length - 1 ? `1px solid ${C.border}` : 'none',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: [C.green, C.blue, C.purple, C.amber, C.red][i % 5],
                      }} />
                      <span style={{ fontFamily: C.M, fontSize: 10, color: C.text }}>
                        {d.label || tr(d.address)}
                      </span>
                      {d.role && d.role !== 'primary' && (
                        <span style={{
                          fontFamily: C.M, fontSize: 7, color: C.dim,
                          padding: '1px 4px', borderRadius: 4,
                          background: 'rgba(10,10,10,0.04)',
                        }}>
                          {d.role}
                        </span>
                      )}
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text }}>
                        {(bps / 100).toFixed(2)}%
                      </span>
                      <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 6 }}>
                        ({sampleAmount})
                      </span>
                    </div>
                  </div>
                )
              })
          }

          {/* ── RSends fee ── */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            padding: '6px 0 0', marginTop: 4,
            borderTop: `1px solid ${C.border}`,
          }}>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>RSends fee</span>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
              {simulation
                ? `${(simulation.rsend_fee.bps / 100).toFixed(2)}% (${simulation.rsend_fee.amount_human})`
                : `${RSEND_FEE_PCT.toFixed(2)}% (${RSEND_FEE_PCT.toFixed(2)})`
              }
            </span>
          </div>

          {simError && (
            <div style={{
              fontFamily: C.M, fontSize: 9, color: C.red, marginTop: 6,
              padding: '4px 8px', background: `${C.red}08`, borderRadius: 6,
            }}>
              Live preview unavailable: {simError}
            </div>
          )}
        </div>
      )}

      {/* ── Calculation Table ──────────────────────── */}
      <div style={{
        background: 'rgba(10,10,10,0.03)', border: `1px solid ${C.border}`,
        borderRadius: 14, padding: '14px 16px', marginBottom: 16,
      }}>
        <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub, marginBottom: 10 }}>
          {userBal > 0
            ? `Your balance: ${exampleEth.toFixed(4)} ETH (${fiat(exampleEth, ethPrice)})`
            : `Hypothetical example — if you receive ${exampleEth} ETH (${fiat(exampleEth, ethPrice)})`
          }
        </div>

        {/* Fee row */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '6px 0', borderBottom: `1px solid ${C.border}`,
        }}>
          <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>
            RSends processing fee ({RSEND_FEE_PCT}%)
          </span>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontFamily: C.M, fontSize: 11, color: C.text }}>{fee.toFixed(4)} ETH</span>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 6 }}>{fiat(fee, ethPrice)}</span>
          </div>
        </div>

        {/* Destination rows */}
        {destinations.map((d, i) => {
          const amt = afterFee * (d.percent / Math.max(total, 1))
          return (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '6px 0',
              borderBottom: i < destinations.length - 1 ? `1px solid ${C.border}` : 'none',
            }}>
              <span style={{ fontFamily: C.M, fontSize: 10, color: C.text }}>
                {d.label || tr(d.address)} ({d.percent}%)
              </span>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontFamily: C.M, fontSize: 11, color: C.green }}>{amt.toFixed(4)} ETH</span>
                <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 6 }}>{fiat(amt, ethPrice)}</span>
              </div>
            </div>
          )
        })}

        {/* Total */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '8px 0 0', marginTop: 6, borderTop: `1px solid ${C.border}`,
        }}>
          <span style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.sub }}>Total distributed</span>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontFamily: C.D, fontSize: 13, fontWeight: 700, color: C.text }}>{afterFee.toFixed(4)} ETH</span>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginLeft: 6 }}>{fiat(afterFee, ethPrice)}</span>
          </div>
        </div>
      </div>

      {/* Settings summary */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 16,
      }}>
        {[
          `${advanced.threshold} ETH min`,
          advanced.speed === 'economy' ? t('economySpeed') : advanced.speed === 'fast' ? t('fastSpeed') : t('normalSpeed'),
          `${advanced.maxGas} gwei max`,
          `${advanced.cooldown}s cooldown`,
          ...(advanced.dailyLimit ? [`${advanced.dailyLimit} ETH/day`] : []),
          ...(advanced.tokenFilter.length > 0 ? [`Tokens: ${advanced.tokenFilter.join(', ')}`] : []),
          ...(advanced.autoSwap ? [t('autoSwap')] : []),
          ...(advanced.scheduleEnabled ? [t('scheduled')] : []),
          ...(advanced.notifyEnabled ? [advanced.notifyChannel] : []),
        ].map(tag => (
          <span key={tag} style={{
            fontFamily: C.M, fontSize: 9, color: C.sub,
            background: `${C.sub}10`, padding: '2px 7px', borderRadius: 6,
          }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Confirmation */}
      <label style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        padding: '12px 14px', borderRadius: 12, cursor: 'pointer',
        background: confirmed ? `${C.green}06` : 'rgba(10,10,10,0.04)',
        border: `1px solid ${confirmed ? `${C.green}20` : C.border}`,
        transition: 'all 0.2s',
      }}>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={e => setConfirmed(e.target.checked)}
          style={{ marginTop: 2, accentColor: C.green }}
        />
        <div>
          <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: C.text, marginBottom: 2 }}>
            I understand this rule will automatically forward incoming funds
          </div>
          <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
            You will sign with your wallet to verify ownership. No funds will be moved until a transaction is detected.
          </div>
        </div>
      </label>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════
//  ANIMATED FLOW DIAGRAM (SVG)
// ═══════════════════════════════════════════════════════════

function FlowDiagram({ address, destinations }: { address: string; destinations: Destination[] }) {
  const n = destinations.length
  const h = Math.max(80, 20 + n * 44)
  const midY = h / 2

  return (
    <div style={{
      background: 'rgba(10,10,10,0.04)', border: `1px solid ${C.border}`,
      borderRadius: 14, padding: '14px 8px', marginBottom: 16,
    }}>
      <svg width="100%" viewBox={`0 0 480 ${h}`} style={{ display: 'block' }}>
        {/* Source node */}
        <rect x="4" y={midY - 18} width="86" height="36" rx="10"
          fill={`${C.purple}12`} stroke={C.purple} strokeWidth="0.8" />
        <text x="47" y={midY - 3} textAnchor="middle" fill={C.text} fontSize="8" fontFamily="var(--font-mono)">
          {address.slice(0, 6)}...{address.slice(-4)}
        </text>
        <text x="47" y={midY + 9} textAnchor="middle" fill={C.dim} fontSize="7" fontFamily="var(--font-mono)">
          Source
        </text>

        {/* Line source → RSends */}
        <line x1="90" y1={midY} x2="155" y2={midY}
          stroke={C.purple} strokeWidth="1" strokeDasharray="6 3" opacity="0.7">
          <animate attributeName="stroke-dashoffset" from="9" to="0" dur="1.2s" repeatCount="indefinite" />
        </line>

        {/* RSends fee node */}
        <rect x="155" y={midY - 18} width="76" height="36" rx="10"
          fill={`${C.blue}10`} stroke={C.blue} strokeWidth="0.8" />
        <text x="193" y={midY - 3} textAnchor="middle" fill={C.text} fontSize="9" fontFamily="var(--font-mono)">
          RSends
        </text>
        <text x="193" y={midY + 9} textAnchor="middle" fill={C.dim} fontSize="7" fontFamily="var(--font-mono)">
          {RSEND_FEE_PCT}% fee
        </text>

        {/* Destination nodes */}
        {destinations.map((d, i) => {
          const dy = n === 1 ? midY : 22 + i * ((h - 44) / Math.max(1, n - 1))
          return (
            <g key={i}>
              <line x1="231" y1={midY} x2="325" y2={dy}
                stroke={C.green} strokeWidth="1" strokeDasharray="6 3" opacity="0.6">
                <animate attributeName="stroke-dashoffset" from="9" to="0" dur="1.2s" repeatCount="indefinite" />
              </line>
              <rect x="325" y={dy - 18} width="148" height="36" rx="10"
                fill={`${C.green}08`} stroke={C.green} strokeWidth="0.8" />
              <text x="399" y={dy - 3} textAnchor="middle" fill={C.text} fontSize="8" fontFamily="var(--font-mono)">
                {d.label || `${d.address.slice(0, 6)}...${d.address.slice(-4)}`}
              </text>
              <text x="399" y={dy + 9} textAnchor="middle" fill={C.green} fontSize="8" fontFamily="var(--font-mono)" fontWeight="600">
                {d.percent}%
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}


export default RouteWizard
