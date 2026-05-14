'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { useWriteContract } from 'wagmi'
import { C, EASE, BACKEND, CHAIN_NAMES, inp, selectStyle, labelStyle, isValidAddr, tr, ToggleSwitch, Sk } from './shared'
import type { DistributionEntry } from '../../lib/useDistributionList'
import { getRegistry } from '../../lib/contractRegistry'
import { FEE_ROUTER_ABI } from '../../lib/feeRouterAbi'
import { mutationHeaders, parseRSendError } from '../../lib/rsendFetch'
import { logger } from '../../lib/logger'

type SettingsSection = 'security' | 'notifications' | 'distribution' | 'apikeys' | 'export' | 'danger'

function SettingsTab({
  address, chainId, rules, emergencyStop,
  distLists, distLoading, createDistList, deleteDistList,
  initialSection, onInitialSectionConsumed,
}: {
  address: string
  chainId: number
  rules: any[]
  emergencyStop: () => Promise<any>
  distLists: any[]
  distLoading: boolean
  createDistList: (name: string, entries: DistributionEntry[]) => Promise<any>
  deleteDistList: (id: number) => Promise<void>
  initialSection?: SettingsSection | null
  onInitialSectionConsumed?: () => void
}) {
  const t = useTranslations('commandCenter.settings')
  const [expanded, setExpanded] = useState<SettingsSection | null>(initialSection ?? 'security')

  useEffect(() => {
    if (initialSection) {
      setExpanded(initialSection)
      onInitialSectionConsumed?.()
    }
  }, [initialSection, onInitialSectionConsumed])

  // ── Security: spending limits ──
  const [limits, setLimits] = useState<any>(null)
  const [limitsLoading, setLimitsLoading] = useState(false)

  // ── Notifications: global defaults (applied on new rules) ──
  const [notifyEnabled, setNotifyEnabled] = useState(true)
  const [notifyChannel, setNotifyChannel] = useState<'telegram' | 'email'>('telegram')
  const [chatId, setChatId] = useState('')
  const [email, setEmail] = useState('')
  const [notifySaved, setNotifySaved] = useState(false)

  // ── Distribution lists ──
  const [newListName, setNewListName] = useState('')
  const [newEntries, setNewEntries] = useState<DistributionEntry[]>([{ address: '', label: '', percent: 100 }])
  const [distSaving, setDistSaving] = useState(false)
  const distSavingRef = useRef(false)
  const [distConfirmDel, setDistConfirmDel] = useState<number | null>(null)
  const [distDeleting, setDistDeleting] = useState(false)
  const distDeletingRef = useRef(false)

  // ── API Keys ──
  const [apiKeys, setApiKeys] = useState<any[]>([])
  const [apiKeysLoading, setApiKeysLoading] = useState(false)
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [newKeyScope, setNewKeyScope] = useState<'read' | 'write' | 'admin'>('write')
  const [newKeyEnv, setNewKeyEnv] = useState<'test' | 'live'>('live')
  const [generatingKey, setGeneratingKey] = useState(false)
  const generatingRef = useRef(false)
  const [newKeyPlaintext, setNewKeyPlaintext] = useState<string | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<number | null>(null)
  const [revokingId, setRevokingId] = useState<number | null>(null)

  // ── Export ──
  const [exportFormat, setExportFormat] = useState<'csv' | 'json'>('csv')
  const [exportDateFrom, setExportDateFrom] = useState('')
  const [exportDateTo, setExportDateTo] = useState('')
  // ── Danger ──
  const [confirmEmergency, setConfirmEmergency] = useState(false)
  const [emergencyLoading, setEmergencyLoading] = useState(false)
  const emergencyRef = useRef(false)
  const [emergencyResult, setEmergencyResult] = useState<string | null>(null)

  // Fetch spending limits
  useEffect(() => {
    if (expanded !== 'security') return
    setLimitsLoading(true)
    fetch(`${BACKEND}/api/v1/forwarding/spending-limits?source_address=${address.toLowerCase()}&chain_id=${chainId}`, {
      signal: AbortSignal.timeout(10000),
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => setLimits(d))
      .catch(() => {})
      .finally(() => setLimitsLoading(false))
  }, [expanded, address, chainId])

  // ── API Keys: fetch / generate / revoke ──
  const fetchApiKeys = useCallback(async () => {
    setApiKeysLoading(true)
    try {
      const res = await fetch(`${BACKEND}/api/v1/keys?owner_address=${address}`, { signal: AbortSignal.timeout(10000) })
      if (res.ok) setApiKeys(await res.json())
    } catch {}
    finally { setApiKeysLoading(false) }
  }, [address])

  useEffect(() => {
    if (expanded === 'apikeys') fetchApiKeys()
  }, [expanded, fetchApiKeys])

  const generateApiKey = async () => {
    if (generatingRef.current || !newKeyLabel.trim()) return
    generatingRef.current = true
    setGeneratingKey(true)
    try {
      const res = await fetch(`${BACKEND}/api/v1/keys/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner_address: address, label: newKeyLabel.trim(), scope: newKeyScope, environment: newKeyEnv }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        alert(err.detail || t('failedToGenerateKey'))
        return
      }
      const data = await res.json()
      setNewKeyPlaintext(data.key)
      setNewKeyLabel('')
      fetchApiKeys()
    } catch { alert(t('failedToGenerateKey')) }
    finally { generatingRef.current = false; setGeneratingKey(false) }
  }

  const revokeApiKey = async (keyId: number) => {
    setRevokingId(keyId)
    try {
      await fetch(`${BACKEND}/api/v1/keys/${keyId}/revoke`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner_address: address }),
      })
      fetchApiKeys()
    } catch {}
    finally { setRevokingId(null) }
  }

  // Load notification prefs from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`rsend_notif_${address}`)
      if (saved) {
        const p = JSON.parse(saved)
        setNotifyEnabled(p.enabled ?? true)
        setNotifyChannel(p.channel ?? 'telegram')
        setChatId(p.chatId ?? '')
        setEmail(p.email ?? '')
      }
    } catch (err) {
      logger.warn('CommandCenter', 'Load notification prefs failed', { error: String(err) })
    }
  }, [address])

  const saveNotifPrefs = () => {
    try {
      localStorage.setItem(`rsend_notif_${address}`, JSON.stringify({
        enabled: notifyEnabled, channel: notifyChannel, chatId, email,
      }))
      setNotifySaved(true)
      setTimeout(() => setNotifySaved(false), 2000)
    } catch (err) {
      logger.error('CommandCenter', 'Save notification prefs failed', { error: String(err) })
    }
  }

  // Distribution list helpers
  const distTotal = newEntries.reduce((s, e) => s + e.percent, 0)
  const canSaveDist = newListName.trim() && newEntries.length > 0 &&
    newEntries.every(e => isValidAddr(e.address)) &&
    (newEntries.length === 1 || Math.abs(distTotal - 100) < 1)

  const handleCreateDist = async () => {
    if (distSavingRef.current) return
    distSavingRef.current = true
    setDistSaving(true)
    try {
      await createDistList(newListName, newEntries)
      setNewListName('')
      setNewEntries([{ address: '', label: '', percent: 100 }])
    } catch (err) {
      logger.error('CommandCenter', 'Create distribution list failed', { error: String(err) })
    } finally {
      distSavingRef.current = false
      setDistSaving(false)
    }
  }

  // Export handler
  const handleExport = () => {
    const params = new URLSearchParams({
      owner_address: address.toLowerCase(),
      format: exportFormat,
    })
    if (exportDateFrom) params.set('date_from', exportDateFrom)
    if (exportDateTo) params.set('date_to', exportDateTo)
    window.open(`${BACKEND}/api/v1/forwarding/logs/export?${params}`, '_blank')
  }

  // Emergency stop handler (ref guard prevents double-click)
  const handleEmergencyStop = async () => {
    if (emergencyRef.current) return
    emergencyRef.current = true
    setEmergencyLoading(true)
    try {
      const data = await emergencyStop()
      setEmergencyResult(`Paused ${data.paused_count ?? 0} rule(s)`)
      setConfirmEmergency(false)
    } catch (e) {
      setEmergencyResult(e instanceof Error ? e.message : 'Failed')
    } finally {
      emergencyRef.current = false
      setEmergencyLoading(false)
    }
    setTimeout(() => setEmergencyResult(null), 4000)
  }

  // Section header helper
  const SectionHeader = ({ id, label, icon, color }: { id: SettingsSection; label: string; icon: string; color: string }) => (
    <button
      onClick={() => setExpanded(expanded === id ? null : id)}
      style={{
        width: '100%', display: 'flex', alignItems: 'center', gap: 10,
        padding: '12px 14px', borderRadius: 12,
        background: expanded === id ? `${color}08` : 'rgba(10,10,10,0.04)',
        border: `1px solid ${expanded === id ? `${color}30` : C.border}`,
        color: expanded === id ? C.text : C.sub,
        fontFamily: C.D, fontSize: 12, fontWeight: 600,
        cursor: 'pointer', transition: 'all 0.2s',
        marginBottom: expanded === id ? 0 : 0,
        textAlign: 'left',
      }}
    >
      <span style={{ fontSize: 14, opacity: 0.7 }}>{icon}</span>
      <span style={{ flex: 1 }}>{label}</span>
      <span style={{ fontFamily: C.M, fontSize: 10, color: C.dim, transform: expanded === id ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}>▸</span>
    </button>
  )

  const cardStyle: React.CSSProperties = {
    padding: '14px', borderRadius: 12,
    background: 'rgba(10,10,10,0.04)',
    border: `1px solid ${C.border}`,
  }

  const activeRules = rules.filter(r => r.is_active && !r.is_paused).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

      {/* ════════════ SECURITY ════════════ */}
      <SectionHeader id="security" label={t('security')} icon="🛡" color={C.blue} />
      <AnimatePresence>
        {expanded === 'security' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Spending Limits */}
              <div>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Spending Limits</div>
                {limitsLoading ? (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Sk w="33%" h={60} r={10} /><Sk w="33%" h={60} r={10} /><Sk w="33%" h={60} r={10} />
                  </div>
                ) : limits ? (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                    {[
                      { label: t('perHour'), spent: limits.per_hour?.spent ?? 0, limit: limits.per_hour?.limit ?? 0, color: C.blue },
                      { label: t('perDay'), spent: limits.per_day?.spent ?? 0, limit: limits.per_day?.limit ?? 0, color: C.purple },
                      { label: t('globalDaily'), spent: limits.global_daily?.spent ?? 0, limit: limits.global_daily?.limit ?? 0, color: C.green },
                    ].map(l => {
                      const pct = l.limit > 0 ? Math.min(100, (l.spent / l.limit) * 100) : 0
                      const warn = pct >= 80
                      return (
                        <div key={l.label} style={cardStyle}>
                          <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginBottom: 6 }}>{l.label}</div>
                          <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 700, color: warn ? C.amber : C.text }}>
                            {l.spent.toFixed(4)}
                          </div>
                          <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginBottom: 6 }}>
                            / {l.limit.toFixed(4)} ETH
                          </div>
                          <div style={{ height: 3, borderRadius: 2, background: 'rgba(10,10,10,0.08)' }}>
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${pct}%` }}
                              transition={{ duration: 0.6, ease: EASE }}
                              style={{ height: '100%', borderRadius: 2, background: warn ? C.amber : l.color }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div style={{ ...cardStyle, fontFamily: C.M, fontSize: 11, color: C.dim, textAlign: 'center' }}>
                    No limits configured
                  </div>
                )}
              </div>

              {/* Whitelist */}
              <div>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Approved Destinations</div>
                <div style={cardStyle}>
                  {rules.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      {[...new Set(rules.map(r => r.destination_wallet))].map(dest => (
                        <div key={dest} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 5, height: 5, borderRadius: '50%', background: C.green }} />
                          <span style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>{tr(dest, 8, 6)}</span>
                          <span style={{ fontFamily: C.M, fontSize: 8, color: C.dim, background: `${C.green}10`, padding: '1px 5px', borderRadius: 4 }}>
                            whitelisted
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ fontFamily: C.M, fontSize: 11, color: C.dim, textAlign: 'center' }}>
                      No destinations configured
                    </div>
                  )}
                </div>
              </div>

              {/* Circuit Breaker */}
              <div>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Circuit Breaker</div>
                <div style={{ ...cardStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: activeRules > 0 ? C.green : C.dim,
                      boxShadow: activeRules > 0 ? `0 0 6px ${C.green}60` : 'none',
                    }} />
                    <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text }}>
                      {activeRules > 0 ? t('closedActive') : t('openIdle')}
                    </span>
                  </div>
                  <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
                    {activeRules} active rule{activeRules !== 1 ? 's' : ''}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ════════════ NOTIFICATIONS ════════════ */}
      <SectionHeader id="notifications" label={t('notifications')} icon="🔔" color={C.purple} />
      <AnimatePresence>
        {expanded === 'notifications' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Enable toggle */}
              <div style={{ ...cardStyle, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text }}>Enable Notifications</div>
                  <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 2 }}>Applied as default for new rules</div>
                </div>
                <ToggleSwitch value={notifyEnabled} onChange={setNotifyEnabled} />
              </div>

              {notifyEnabled && (
                <>
                  {/* Channel selector */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                    {(['telegram', 'email'] as const).map(ch => (
                      <button
                        key={ch}
                        onClick={() => setNotifyChannel(ch)}
                        style={{
                          ...cardStyle, textAlign: 'center', cursor: 'pointer',
                          borderColor: notifyChannel === ch ? `${C.purple}50` : C.border,
                          background: notifyChannel === ch ? `${C.purple}08` : 'rgba(10,10,10,0.04)',
                        }}
                      >
                        <div style={{ fontSize: 18, marginBottom: 4 }}>{ch === 'telegram' ? '✈' : '✉'}</div>
                        <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 600, color: notifyChannel === ch ? C.text : C.sub, textTransform: 'capitalize' }}>
                          {ch}
                        </div>
                      </button>
                    ))}
                  </div>

                  {/* Input field */}
                  {notifyChannel === 'telegram' ? (
                    <div>
                      <label style={labelStyle}>Telegram Chat ID</label>
                      <input
                        style={inp}
                        placeholder="e.g. -1001234567890"
                        value={chatId}
                        onChange={e => setChatId(e.target.value)}
                      />
                      <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 4 }}>
                        Add @RSendssBot to your group, then send /start to get the chat ID
                      </div>
                    </div>
                  ) : (
                    <div>
                      <label style={labelStyle}>Email Address</label>
                      <input
                        style={inp}
                        placeholder="you@example.com"
                        type="email"
                        value={email}
                        onChange={e => setEmail(e.target.value)}
                      />
                    </div>
                  )}

                  {/* Save button */}
                  <button
                    onClick={saveNotifPrefs}
                    style={{
                      padding: '8px 16px', borderRadius: 10, border: 'none',
                      background: notifySaved ? `${C.green}20` : `${C.purple}15`,
                      color: notifySaved ? C.green : C.purple,
                      fontFamily: C.D, fontSize: 11, fontWeight: 600,
                      cursor: 'pointer', transition: 'all 0.2s',
                    }}
                  >
                    {notifySaved ? t('saved') : t('savePreferences')}
                  </button>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ════════════ DISTRIBUTION LISTS ════════════ */}
      <SectionHeader id="distribution" label={t('distributionLists')} icon="📋" color={C.green} />
      <AnimatePresence>
        {expanded === 'distribution' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Existing lists */}
              {distLoading ? (
                <Sk w="100%" h={60} r={10} />
              ) : distLists.length > 0 ? (
                distLists.map(l => (
                  <div key={l.id} style={{ ...cardStyle, display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text }}>{l.name}</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>
                          {(l.entries || []).length} recipient{(l.entries || []).length !== 1 ? 's' : ''}
                        </span>
                        {distConfirmDel === l.id ? (
                          <div style={{ display: 'flex', gap: 4 }}>
                            <button
                              disabled={distDeleting}
                              onClick={async () => {
                                if (distDeletingRef.current) return
                                distDeletingRef.current = true
                                setDistDeleting(true)
                                try { await deleteDistList(l.id); setDistConfirmDel(null) } catch (err) {
                                  logger.error('CommandCenter', 'Delete dist list failed', { listId: String(l.id), error: String(err) })
                                } finally {
                                  distDeletingRef.current = false
                                  setDistDeleting(false)
                                }
                              }}
                              style={{ padding: '2px 8px', borderRadius: 5, border: 'none', background: C.red, color: '#fff', fontFamily: C.M, fontSize: 9, cursor: distDeleting ? 'wait' : 'pointer', opacity: distDeleting ? 0.5 : 1 }}>
                              {distDeleting ? '...' : t('yes')}
                            </button>
                            {!distDeleting && <button onClick={() => setDistConfirmDel(null)}
                              style={{ padding: '2px 8px', borderRadius: 5, border: `1px solid ${C.border}`, background: 'transparent', color: C.dim, fontFamily: C.M, fontSize: 9, cursor: 'pointer' }}>
                              No
                            </button>}
                          </div>
                        ) : (
                          <button onClick={() => setDistConfirmDel(l.id)}
                            style={{ padding: '2px 8px', borderRadius: 5, border: `1px solid ${C.red}25`, background: `${C.red}08`, color: C.red, fontFamily: C.M, fontSize: 9, cursor: 'pointer' }}>
                            Delete
                          </button>
                        )}
                      </div>
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {(l.entries || []).map((e: DistributionEntry, i: number) => (
                        <span key={i} style={{ fontFamily: C.M, fontSize: 9, color: C.sub, background: `${C.sub}10`, padding: '2px 7px', borderRadius: 6 }}>
                          {e.label || tr(e.address)} {e.percent}%
                        </span>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div style={{ ...cardStyle, textAlign: 'center', fontFamily: C.M, fontSize: 11, color: C.dim }}>
                  No distribution lists yet
                </div>
              )}

              {/* Create new list */}
              <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em' }}>New List</div>
                <input
                  style={inp}
                  placeholder="List name"
                  value={newListName}
                  onChange={e => setNewListName(e.target.value)}
                />
                {newEntries.map((entry, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 28px', gap: 4, alignItems: 'center' }}>
                    <input
                      style={inp}
                      placeholder="0x..."
                      value={entry.address}
                      onChange={e => {
                        const next = [...newEntries]
                        next[i] = { ...next[i], address: e.target.value }
                        setNewEntries(next)
                      }}
                    />
                    <input
                      style={{ ...inp, textAlign: 'center' }}
                      placeholder="%"
                      type="number"
                      value={entry.percent || ''}
                      onChange={e => {
                        const next = [...newEntries]
                        next[i] = { ...next[i], percent: Number(e.target.value) || 0 }
                        setNewEntries(next)
                      }}
                    />
                    {newEntries.length > 1 && (
                      <button
                        onClick={() => {
                          const next = newEntries.filter((_, idx) => idx !== i)
                          if (next.length === 1) next[0].percent = 100
                          setNewEntries(next)
                        }}
                        style={{ width: 28, height: 28, borderRadius: 7, border: `1px solid ${C.border}`, background: 'transparent', color: C.dim, cursor: 'pointer', fontSize: 12 }}
                      >×</button>
                    )}
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 6 }}>
                  {newEntries.length < 5 && (
                    <button
                      onClick={() => setNewEntries([...newEntries, { address: '', label: '', percent: 0 }])}
                      style={{ padding: '5px 10px', borderRadius: 8, border: `1px solid ${C.border}`, background: 'transparent', color: C.sub, fontFamily: C.M, fontSize: 9, cursor: 'pointer' }}
                    >+ Add Recipient</button>
                  )}
                  <button
                    onClick={handleCreateDist}
                    disabled={!canSaveDist || distSaving}
                    style={{
                      padding: '5px 12px', borderRadius: 8, border: 'none',
                      background: canSaveDist ? `${C.green}20` : 'rgba(10,10,10,0.04)',
                      color: canSaveDist ? C.green : C.dim,
                      fontFamily: C.D, fontSize: 10, fontWeight: 600,
                      cursor: canSaveDist ? 'pointer' : 'not-allowed',
                    }}
                  >
                    {distSaving ? t('saving') : t('createList')}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ════════════ API KEYS ════════════ */}
      <SectionHeader id="apikeys" label="API Keys" icon="🔑" color={C.purple} />
      <AnimatePresence>
        {expanded === 'apikeys' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Generate new key */}
              <div style={cardStyle}>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Generate new key</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input
                    value={newKeyLabel}
                    onChange={e => setNewKeyLabel(e.target.value)}
                    placeholder="Key label (e.g. Production, Staging)"
                    style={{ ...inp, flex: '1 1 140px', minWidth: 140 }}
                    onKeyDown={e => e.key === 'Enter' && generateApiKey()}
                  />
                  <select
                    value={newKeyScope}
                    onChange={e => setNewKeyScope(e.target.value as any)}
                    style={{ ...selectStyle, flex: '0 0 auto', minWidth: 100 }}
                  >
                    <option value="read">Read Only</option>
                    <option value="write">Read + Write</option>
                    <option value="admin">Admin</option>
                  </select>
                  <select
                    value={newKeyEnv}
                    onChange={e => setNewKeyEnv(e.target.value as any)}
                    style={{ ...selectStyle, flex: '0 0 auto', minWidth: 80 }}
                  >
                    <option value="live">Live</option>
                    <option value="test">Test</option>
                  </select>
                  <button
                    onClick={generateApiKey}
                    disabled={generatingKey || !newKeyLabel.trim()}
                    style={{
                      padding: '8px 16px', borderRadius: 8,
                      background: C.purple, color: '#fff', border: 'none',
                      cursor: 'pointer', fontFamily: C.D, fontSize: 12,
                      opacity: generatingKey || !newKeyLabel.trim() ? 0.5 : 1,
                      whiteSpace: 'nowrap', transition: 'opacity 0.2s',
                    }}
                  >
                    {generatingKey ? t('generating') : t('generateKey')}
                  </button>
                </div>
              </div>

              {/* Newly generated key — show ONCE */}
              {newKeyPlaintext && (
                <div style={{
                  background: 'rgba(0,214,143,0.08)',
                  border: '1px solid rgba(0,214,143,0.3)',
                  borderRadius: 10, padding: 14,
                }}>
                  <div style={{ fontFamily: C.D, fontSize: 11, color: C.green, marginBottom: 8, fontWeight: 600 }}>
                    Copy this key now — it won't be shown again
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <code style={{
                      fontFamily: C.M, fontSize: 11, color: C.text,
                      background: 'rgba(0,0,0,0.3)', padding: '6px 10px',
                      borderRadius: 6, flex: 1, wordBreak: 'break-all',
                    }}>
                      {newKeyPlaintext}
                    </code>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(newKeyPlaintext)
                        setCopiedKeyId(-1)
                        setTimeout(() => setCopiedKeyId(null), 2000)
                      }}
                      style={{
                        padding: '6px 12px', borderRadius: 6,
                        background: copiedKeyId === -1 ? C.green : 'rgba(10,10,10,0.08)',
                        border: 'none', cursor: 'pointer', color: '#fff',
                        fontFamily: C.D, fontSize: 11, whiteSpace: 'nowrap',
                        transition: 'background 0.2s',
                      }}
                    >
                      {copiedKeyId === -1 ? t('copied') : t('copy')}
                    </button>
                  </div>
                  <button
                    onClick={() => setNewKeyPlaintext(null)}
                    style={{
                      marginTop: 8, background: 'none', border: 'none',
                      color: C.dim, fontSize: 11, cursor: 'pointer', fontFamily: C.D,
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              )}

              {/* List existing keys */}
              {apiKeysLoading ? <Sk w="100%" h={60} /> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {apiKeys.length === 0 && !newKeyPlaintext && (
                    <div style={{ color: C.dim, fontFamily: C.D, fontSize: 12, padding: '12px 0' }}>
                      No API keys yet. Generate one above.
                    </div>
                  )}
                  {apiKeys.map(k => {
                    const scopeColors: Record<string, string> = { read: C.dim, write: C.blue, admin: C.purple }
                    const envColor = k.environment === 'test' ? C.amber : C.green
                    return (
                      <div key={k.id} style={{
                        padding: '10px 12px', borderRadius: 10,
                        background: 'rgba(10,10,10,0.04)',
                        border: `1px solid ${k.is_active ? C.border : 'rgba(255,76,106,0.2)'}`,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                            <span style={{ fontFamily: C.D, fontSize: 12, color: k.is_active ? C.text : C.dim }}>{k.label}</span>
                            <span style={{ fontSize: 8, fontFamily: C.M, padding: '1px 5px', borderRadius: 4, background: `${scopeColors[k.scope] || C.dim}20`, color: scopeColors[k.scope] || C.dim, textTransform: 'uppercase' }}>{k.scope}</span>
                            <span style={{ fontSize: 8, fontFamily: C.M, padding: '1px 5px', borderRadius: 4, background: `${envColor}20`, color: envColor, textTransform: 'uppercase' }}>{k.environment}</span>
                            {!k.is_active && (
                              <span style={{ fontSize: 8, color: C.red, fontFamily: C.M, background: 'rgba(255,76,106,0.1)', padding: '1px 5px', borderRadius: 4 }}>REVOKED</span>
                            )}
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                            <span style={{ fontSize: 9, color: C.dim, fontFamily: C.M }}>{k.rate_limit_rpm || 100} req/min</span>
                            {k.is_active && (
                              <button
                                onClick={() => revokeApiKey(k.id)}
                                disabled={revokingId === k.id}
                                style={{
                                  padding: '4px 10px', borderRadius: 6,
                                  background: 'rgba(255,76,106,0.1)',
                                  border: '1px solid rgba(255,76,106,0.3)',
                                  color: C.red, cursor: 'pointer',
                                  fontFamily: C.D, fontSize: 10,
                                  opacity: revokingId === k.id ? 0.5 : 1,
                                  transition: 'opacity 0.2s',
                                }}
                              >
                                {revokingId === k.id ? '...' : t('revoke')}
                              </button>
                            )}
                          </div>
                        </div>
                        <code style={{ fontFamily: C.M, fontSize: 10, color: C.dim }}>{k.prefix}</code>
                        <div style={{ marginTop: 4, fontFamily: C.M, fontSize: 9, color: C.sub }}>
                          {k.total_requests || 0} requests · {k.total_intents_created || 0} intents · ${k.total_volume_usd || '0'} volume
                          {k.last_used_at && <span> · Used {new Date(k.last_used_at).toLocaleDateString()}</span>}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Usage hint */}
              <div style={{
                marginTop: 4, padding: 10, borderRadius: 8,
                background: 'rgba(139,92,246,0.05)',
                border: '1px solid rgba(139,92,246,0.15)',
              }}>
                <div style={{ fontFamily: C.D, fontSize: 10, color: C.purple, marginBottom: 4 }}>Usage</div>
                <code style={{ fontFamily: C.M, fontSize: 10, color: C.sub }}>
                  Authorization: Bearer rsend_live_your_key_here
                </code>
              </div>

            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ════════════ EXPORT & COMPLIANCE ════════════ */}
      <SectionHeader id="export" label={t('exportCompliance')} icon="📊" color={C.amber} />
      <AnimatePresence>
        {expanded === 'export' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Export Sweep Logs */}
              <div style={cardStyle}>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Export Sweep Logs</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  <div>
                    <label style={labelStyle}>From</label>
                    <input style={inp} type="date" value={exportDateFrom} onChange={e => setExportDateFrom(e.target.value)} />
                  </div>
                  <div>
                    <label style={labelStyle}>To</label>
                    <input style={inp} type="date" value={exportDateTo} onChange={e => setExportDateTo(e.target.value)} />
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <label style={{ ...labelStyle, marginBottom: 0 }}>Format</label>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {(['csv', 'json'] as const).map(f => (
                      <button
                        key={f}
                        onClick={() => setExportFormat(f)}
                        style={{
                          padding: '4px 12px', borderRadius: 6, border: `1px solid ${exportFormat === f ? `${C.amber}40` : C.border}`,
                          background: exportFormat === f ? `${C.amber}10` : 'transparent',
                          color: exportFormat === f ? C.amber : C.dim,
                          fontFamily: C.M, fontSize: 10, fontWeight: 600,
                          cursor: 'pointer', textTransform: 'uppercase',
                        }}
                      >{f}</button>
                    ))}
                  </div>
                  <button
                    onClick={handleExport}
                    style={{
                      marginLeft: 'auto',
                      padding: '6px 14px', borderRadius: 8, border: 'none',
                      background: `${C.amber}15`, color: C.amber,
                      fontFamily: C.D, fontSize: 10, fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    Download
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ════════════ DANGER ZONE ════════════ */}
      <SectionHeader id="danger" label={t('dangerZone')} icon="⚠" color={C.red} />
      <AnimatePresence>
        {expanded === 'danger' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>

              {/* Emergency Stop */}
              <div style={{ ...cardStyle, borderColor: `${C.red}20` }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div>
                    <div style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.red }}>Emergency Stop</div>
                    <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 2 }}>
                      Immediately pause all {activeRules} active forwarding rule{activeRules !== 1 ? 's' : ''}
                    </div>
                  </div>
                </div>
                {emergencyResult && (
                  <div style={{
                    fontFamily: C.M, fontSize: 10, padding: '6px 10px', borderRadius: 8, marginBottom: 6,
                    background: emergencyResult.startsWith('Paused') ? `${C.green}10` : `${C.red}10`,
                    color: emergencyResult.startsWith('Paused') ? C.green : C.red,
                  }}>
                    {emergencyResult}
                  </div>
                )}
                {!confirmEmergency ? (
                  <button
                    onClick={() => setConfirmEmergency(true)}
                    disabled={activeRules === 0}
                    style={{
                      width: '100%', padding: '10px', borderRadius: 10,
                      border: `1px solid ${activeRules > 0 ? C.red : C.dim}`,
                      background: activeRules > 0 ? `${C.red}10` : 'transparent',
                      color: activeRules > 0 ? C.red : C.dim,
                      fontFamily: C.D, fontSize: 12, fontWeight: 700,
                      cursor: activeRules > 0 ? 'pointer' : 'not-allowed',
                      transition: 'all 0.2s',
                    }}
                  >
                    Stop All Routes
                  </button>
                ) : (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={handleEmergencyStop}
                      disabled={emergencyLoading}
                      style={{
                        flex: 1, padding: '10px', borderRadius: 10, border: 'none',
                        background: C.red, color: '#fff',
                        fontFamily: C.D, fontSize: 12, fontWeight: 700,
                        cursor: emergencyLoading ? 'wait' : 'pointer',
                      }}
                    >
                      {emergencyLoading ? t('stopping') : t('confirmStopAll')}
                    </button>
                    <button
                      onClick={() => setConfirmEmergency(false)}
                      style={{
                        padding: '10px 16px', borderRadius: 10,
                        border: `1px solid ${C.border}`, background: 'transparent',
                        color: C.sub, fontFamily: C.D, fontSize: 12, cursor: 'pointer',
                      }}
                    >Cancel</button>
                  </div>
                )}
              </div>

              {/* Info notice */}
              <div style={{
                padding: '10px 14px', borderRadius: 10,
                background: 'rgba(10,10,10,0.04)',
                border: `1px solid ${C.border}`,
              }}>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, lineHeight: 1.6 }}>
                  Paused rules can be individually resumed from the Routes tab.
                  Rule deletion requires wallet signature and is permanent.
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default SettingsTab
