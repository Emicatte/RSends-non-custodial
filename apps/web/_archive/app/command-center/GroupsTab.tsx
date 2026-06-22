'use client'

import { useState, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { C, EASE, inp, labelStyle, isValidAddr, Sk, TabSkeleton, tr } from './shared'
import type { ChainFamily } from '../../lib/chain-adapters/types'
import type { DistributionEntry } from '../../lib/useDistributionList'
import { logger } from '../../lib/logger'

function GroupsTab({
  lists, loading, createList, deleteList, activeFamily,
}: {
  lists: any[]
  loading: boolean
  createList: (name: string, entries: DistributionEntry[]) => Promise<any>
  deleteList: (id: number) => Promise<void>
  activeFamily: ChainFamily
}) {
  const t = useTranslations('commandCenter.groups')

  // ── Non-EVM guard: distribution groups are EVM-only ──
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

  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [entries, setEntries] = useState<DistributionEntry[]>([{ address: '', label: '', percent: 100 }])
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)
  const deletingRef = useRef(false)

  const total = entries.reduce((s, e) => s + e.percent, 0)
  const canSave = name.trim() && entries.length > 0 &&
    entries.every(e => isValidAddr(e.address)) &&
    (entries.length === 1 || Math.abs(total - 100) < 1)

  const addEntry = () => {
    if (entries.length >= 5) return
    setEntries([...entries, { address: '', label: '', percent: 0 }])
  }

  const removeEntry = (i: number) => {
    const next = entries.filter((_, idx) => idx !== i)
    if (next.length === 1) next[0].percent = 100
    setEntries(next)
  }

  const handleSave = async () => {
    if (savingRef.current) return
    savingRef.current = true
    setSaving(true)
    try {
      await createList(name, entries)
      setName('')
      setEntries([{ address: '', label: '', percent: 100 }])
      setShowForm(false)
    } catch (err) {
      logger.error('CommandCenter', 'Create list failed', { error: String(err) })
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (deletingRef.current) return
    deletingRef.current = true
    setDeleting(true)
    try { await deleteList(id) } catch (err) {
      logger.error('CommandCenter', 'Delete list failed', { listId: String(id), error: String(err) })
    } finally {
      deletingRef.current = false
      setDeleting(false)
    }
    setConfirmDelete(null)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.sub }}>
          {lists.length} Group{lists.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={() => setShowForm(s => !s)}
          style={{
            padding: '6px 14px', borderRadius: 10,
            background: showForm ? 'rgba(10,10,10,0.08)' : `${C.blue}10`,
            border: `1px solid ${showForm ? C.border : `${C.blue}25`}`,
            color: showForm ? C.dim : C.blue,
            fontFamily: C.D, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {showForm ? '\u2715 Cancel' : '+ New Group'}
        </button>
      </div>

      {/* Create form */}
      <AnimatePresence>
        {showForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.4 }}
            style={{ overflow: 'hidden', marginBottom: 12 }}
          >
            <div className="bf-blur-24s" style={{
              background: 'rgba(10,10,10,0.03)',
              border: '1px solid rgba(10,10,10,0.08)',
              borderRadius: 16, padding: 16,
            }}>
              <div style={{ marginBottom: 8 }}>
                <label style={labelStyle}>Group Name</label>
                <input value={name} onChange={e => setName(e.target.value)} placeholder="Payroll" style={inp} />
              </div>

              {entries.map((e, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                  <input
                    value={e.address}
                    onChange={ev => {
                      const next = [...entries]; next[i] = { ...next[i], address: ev.target.value }; setEntries(next)
                    }}
                    placeholder="0x..."
                    style={{ ...inp, flex: 1 }}
                  />
                  <input
                    value={e.label}
                    onChange={ev => {
                      const next = [...entries]; next[i] = { ...next[i], label: ev.target.value }; setEntries(next)
                    }}
                    placeholder="Label"
                    style={{ ...inp, width: 80 }}
                  />
                  <input
                    type="number"
                    value={e.percent}
                    onChange={ev => {
                      const next = [...entries]; next[i] = { ...next[i], percent: parseInt(ev.target.value) || 0 }; setEntries(next)
                    }}
                    style={{ ...inp, width: 50, textAlign: 'center' }}
                  />
                  {entries.length > 1 && (
                    <button
                      onClick={() => removeEntry(i)}
                      style={{
                        width: 28, borderRadius: 8,
                        background: `${C.red}08`, border: `1px solid ${C.red}20`,
                        color: C.red, cursor: 'pointer', fontFamily: C.M, fontSize: 12,
                      }}
                    >{'\u2715'}</button>
                  )}
                </div>
              ))}

              {entries.length < 5 && (
                <button onClick={addEntry} style={{
                  width: '100%', padding: '6px 0', borderRadius: 8,
                  background: 'transparent', border: `1px dashed ${C.dim}`,
                  color: C.dim, fontFamily: C.M, fontSize: 10, cursor: 'pointer',
                  marginBottom: 8,
                }}>+ Add Entry</button>
              )}

              {entries.length > 1 && (
                <div style={{
                  fontFamily: C.M, fontSize: 9, color: total === 100 ? C.green : C.amber,
                  marginBottom: 8,
                }}>
                  Total: {total}% {total !== 100 ? '(must be 100%)' : '\u2713'}
                </div>
              )}

              <button
                onClick={handleSave}
                disabled={!canSave || saving}
                style={{
                  width: '100%', padding: '10px', borderRadius: 12, border: 'none',
                  background: canSave ? `linear-gradient(135deg, ${C.red}, ${C.purple})` : 'rgba(10,10,10,0.04)',
                  color: canSave ? '#fff' : 'rgba(10,10,10,0.35)',
                  fontFamily: C.D, fontSize: 12, fontWeight: 700,
                  cursor: canSave ? 'pointer' : 'not-allowed',
                  transition: 'all 0.2s',
                }}
              >
                {saving ? t('saving') : t('saveGroup')}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* List of groups */}
      {loading && lists.length === 0 ? (
        <TabSkeleton />
      ) : lists.length === 0 && !showForm ? (
        <div style={{
          padding: 28, textAlign: 'center',
          background: 'rgba(10,10,10,0.03)',
          borderRadius: 14, border: `1px solid ${C.border}`,
        }}>
          <div style={{ fontFamily: C.D, fontSize: 13, color: C.dim, marginBottom: 4 }}>No groups yet</div>
          <div style={{ fontFamily: C.M, fontSize: 10, color: `${C.dim}80` }}>
            Save destination groups for quick route setup
          </div>
        </div>
      ) : (
        <AnimatePresence initial={false}>
          {lists.map((l: any) => (
            <motion.div
              key={l.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{
                background: 'rgba(10,10,10,0.03)',
                border: `1px solid ${C.border}`,
                borderRadius: 14, padding: 14, marginBottom: 8,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text }}>
                  {l.name}
                </span>
                {confirmDelete === l.id ? (
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button
                      onClick={() => handleDelete(l.id)}
                      disabled={deleting}
                      style={{
                        padding: '3px 8px', borderRadius: 6, border: `1px solid ${C.red}25`,
                        background: `${C.red}08`, color: C.red,
                        cursor: deleting ? 'wait' : 'pointer',
                        opacity: deleting ? 0.5 : 1,
                        fontFamily: C.M, fontSize: 9, fontWeight: 600,
                      }}
                    >{deleting ? t('deleting') : t('confirm')}</button>
                    {!deleting && <button
                      onClick={() => setConfirmDelete(null)}
                      style={{
                        padding: '3px 8px', borderRadius: 6, border: `1px solid ${C.border}`,
                        background: 'transparent', color: C.dim, cursor: 'pointer',
                        fontFamily: C.M, fontSize: 9, fontWeight: 600,
                      }}
                    >Cancel</button>}
                  </div>
                ) : (
                  <button
                    onClick={() => setConfirmDelete(l.id)}
                    style={{
                      padding: '3px 8px', borderRadius: 6, border: `1px solid ${C.red}25`,
                      background: `${C.red}08`, color: C.red, cursor: 'pointer',
                      fontFamily: C.M, fontSize: 9, fontWeight: 600,
                    }}
                  >Delete</button>
                )}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {(l.entries || []).map((e: DistributionEntry, i: number) => (
                  <span key={i} style={{
                    fontFamily: C.M, fontSize: 9, color: C.sub,
                    background: `${C.sub}10`, padding: '2px 7px', borderRadius: 6,
                  }}>
                    {e.label || tr(e.address)} {e.percent}%
                  </span>
                ))}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      )}
    </div>
  )
}

export default GroupsTab
