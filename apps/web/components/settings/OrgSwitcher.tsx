'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { useOrganizations } from '@/hooks/useOrganizations'

const ORANGE = '#C8512C'
const INK = '#2C2C2A'
const MUTED = '#888780'

export function OrgSwitcher() {
  const t = useTranslations('settings.organization.switcher')
  const tErr = useTranslations('settings.organization.errors')
  const {
    organizations,
    activeOrgId,
    loading,
    saving,
    error,
    isAuthed,
    switchActive,
    createOrganization,
    clearError,
  } = useOrganizations()

  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
        setCreating(false)
        setNewName('')
        setLocalError(null)
        clearError()
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open, clearError])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setCreating(false)
        setNewName('')
        setLocalError(null)
        clearError()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, clearError])

  const active = organizations.find((o) => o.id === activeOrgId) ?? null

  const handleSwitch = useCallback(
    async (orgId: string) => {
      if (orgId === activeOrgId) {
        setOpen(false)
        return
      }
      setLocalError(null)
      try {
        await switchActive(orgId)
        setOpen(false)
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setLocalError(code)
      }
    },
    [activeOrgId, switchActive],
  )

  const handleCreate = useCallback(async () => {
    const name = newName.trim()
    if (!name) return
    setLocalError(null)
    try {
      const created = await createOrganization({ name })
      await switchActive(created.id)
      setCreating(false)
      setNewName('')
      setOpen(false)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setLocalError(code)
    }
  }, [newName, createOrganization, switchActive])

  if (!isAuthed) return null

  const displayLabel = active
    ? active.name
    : loading
      ? t('placeholder')
      : t('placeholder')

  const shownError = localError ?? error
  const errorMsg = shownError
    ? (() => {
        try {
          return tErr(shownError)
        } catch {
          return tErr('unknown')
        }
      })()
    : null

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={loading}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 14px',
          border: `1px solid rgba(200,81,44,0.25)`,
          borderRadius: 10,
          background: '#FFFFFF',
          color: INK,
          fontSize: 14,
          fontWeight: 500,
          cursor: loading ? 'wait' : 'pointer',
          minWidth: 200,
          justifyContent: 'space-between',
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span
          style={{
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {displayLabel}
          {active?.is_personal ? (
            <span
              style={{
                marginLeft: 8,
                fontSize: 10,
                textTransform: 'uppercase',
                color: MUTED,
                letterSpacing: 0.5,
              }}
            >
              {t('personalLabel')}
            </span>
          ) : null}
        </span>
        <span style={{ color: ORANGE, fontSize: 12 }}>▾</span>
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            zIndex: 50,
            minWidth: 260,
            maxHeight: 360,
            overflowY: 'auto',
            background: '#FFFFFF',
            border: `1px solid rgba(200,81,44,0.2)`,
            borderRadius: 12,
            boxShadow: '0 12px 32px rgba(44,44,42,0.12)',
            padding: 6,
          }}
        >
          {organizations.map((o) => {
            const selected = o.id === activeOrgId
            return (
              <button
                key={o.id}
                type="button"
                onClick={() => handleSwitch(o.id)}
                disabled={saving}
                role="option"
                aria-selected={selected}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  width: '100%',
                  padding: '10px 12px',
                  border: 'none',
                  background: selected ? 'rgba(200,81,44,0.08)' : 'transparent',
                  color: selected ? ORANGE : INK,
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: selected ? 600 : 400,
                  cursor: saving ? 'wait' : 'pointer',
                  textAlign: 'left',
                }}
              >
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    flex: 1,
                  }}
                >
                  {o.name}
                  {o.is_personal ? (
                    <span
                      style={{
                        marginLeft: 8,
                        fontSize: 10,
                        textTransform: 'uppercase',
                        color: MUTED,
                        letterSpacing: 0.5,
                      }}
                    >
                      {t('personalLabel')}
                    </span>
                  ) : null}
                </span>
                {selected ? (
                  <span style={{ fontSize: 12, color: ORANGE }}>✓</span>
                ) : null}
              </button>
            )
          })}

          <div
            style={{
              borderTop: '1px solid rgba(200,81,44,0.15)',
              marginTop: 6,
              paddingTop: 6,
            }}
          >
            {creating ? (
              <div style={{ padding: '6px 8px' }}>
                <input
                  autoFocus
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={t('createCta')}
                  maxLength={100}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      void handleCreate()
                    }
                  }}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    fontSize: 14,
                    border: `1px solid rgba(200,81,44,0.25)`,
                    borderRadius: 8,
                    outline: 'none',
                    color: INK,
                  }}
                />
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={saving || !newName.trim()}
                    style={{
                      flex: 1,
                      padding: '6px 10px',
                      background: ORANGE,
                      color: '#FFFFFF',
                      border: 'none',
                      borderRadius: 8,
                      fontSize: 13,
                      fontWeight: 500,
                      cursor:
                        saving || !newName.trim() ? 'not-allowed' : 'pointer',
                      opacity: saving || !newName.trim() ? 0.6 : 1,
                    }}
                  >
                    {saving ? '…' : t('createCta')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setCreating(false)
                      setNewName('')
                      setLocalError(null)
                    }}
                    style={{
                      padding: '6px 10px',
                      background: 'transparent',
                      color: MUTED,
                      border: `1px solid rgba(136,135,128,0.3)`,
                      borderRadius: 8,
                      fontSize: 13,
                      cursor: 'pointer',
                    }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setCreating(true)}
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '10px 12px',
                  border: 'none',
                  background: 'transparent',
                  color: ORANGE,
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: 'pointer',
                  textAlign: 'left',
                  borderRadius: 8,
                }}
              >
                + {t('createCta')}
              </button>
            )}
            {errorMsg ? (
              <div
                style={{
                  padding: '4px 10px 8px',
                  fontSize: 12,
                  color: '#C0392B',
                }}
              >
                {errorMsg}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}
