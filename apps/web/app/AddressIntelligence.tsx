'use client'

import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { isAddress, getAddress } from 'viem'
import { useTranslations } from 'next-intl'
import { useUserContacts, serverToLocal } from '@/hooks/useUserContacts'

// ── Theme (matches TransferForm T) ──────────────────────────────────────────
import { C } from '@/app/designTokens'
const T = { ...C, emerald: '#00ffa3', muted: C.sub, pink: C.purple, red: '#ff2d55', amber: '#ffb800' }

const LS_KEY = 'rp_address_book'

// ── Types ───────────────────────────────────────────────────────────────────
interface AddressContact {
  address: string
  label: string
  lastUsed: string
  txCount: number
}

export interface AddressIntelligenceProps {
  value: string
  onChange: (addr: string) => void
  onValidation?: (valid: boolean, error: string) => void
  chainId?: number
  disabled?: boolean
  inputStyle?: React.CSSProperties
}

// ── Identicon: 4x4 grid from address hash ──────────────────────────────────
function generateIdenticon(address: string): string[] {
  const hash = address.toLowerCase().slice(2)
  const colors: string[] = []
  for (let i = 0; i < 16; i++) {
    const byte = parseInt(hash.slice(i * 2, i * 2 + 2), 16)
    const hue = (byte * 360) / 255
    colors.push(`hsl(${hue}, 70%, 50%)`)
  }
  return colors
}

function Identicon({ address, size = 28 }: { address: string; size?: number }) {
  const colors = generateIdenticon(address)
  const cell = size / 4
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ borderRadius: size / 5, flexShrink: 0 }}>
      <rect width={size} height={size} fill="#FFFFFF" rx={size / 5} />
      {colors.map((c, i) => (
        <rect
          key={i}
          x={(i % 4) * cell}
          y={Math.floor(i / 4) * cell}
          width={cell}
          height={cell}
          fill={c}
          opacity={0.85}
        />
      ))}
    </svg>
  )
}

// ── localStorage helpers ────────────────────────────────────────────────────
function loadContacts(): AddressContact[] {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveContacts(contacts: AddressContact[]) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(contacts))
  } catch { /* SSR / quota */ }
}

/** Record a successful TX for this address */
export function recordSuccessfulTx(address: string, label?: string) {
  const contacts = loadContacts()
  const normalized = address.toLowerCase()
  const existing = contacts.find(c => c.address.toLowerCase() === normalized)
  const now = new Date().toISOString()
  if (existing) {
    existing.txCount += 1
    existing.lastUsed = now
    if (label) existing.label = label
  } else {
    contacts.push({
      address: getAddress(address),
      label: label || '',
      lastUsed: now,
      txCount: 1,
    })
  }
  // Keep max 50 contacts
  if (contacts.length > 50) contacts.splice(0, contacts.length - 50)
  saveContacts(contacts)
  // Mirror to server when authed (listener is components/ContactsPersistence.tsx)
  try {
    const saved = contacts.find(c => c.address.toLowerCase() === normalized)
    if (saved && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('rsends:contact-recorded', {
        detail: {
          address: saved.address,
          label: saved.label,
          lastUsed: saved.lastUsed,
          txCount: saved.txCount,
        },
      }))
    }
  } catch {
    // SSR / dispatch unavailable — localStorage is source of truth
  }
}

// ── Component ───────────────────────────────────────────────────────────────
export default function AddressIntelligence({
  value, onChange, onValidation, chainId, disabled, inputStyle,
}: AddressIntelligenceProps) {
  const [addrError, setAddrError]       = useState('')
  const [isValid, setIsValid]           = useState(false)
  const [isNew, setIsNew]               = useState(false)
  const [pasteBanner, setPasteBanner]   = useState(false)
  const [suggestions, setSuggestions]   = useState<AddressContact[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [focused, setFocused]           = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const t = useTranslations('send')

  // Dual-mode contacts source: server when authed, localStorage otherwise.
  const { contacts: serverContacts, isAuthed } = useUserContacts()
  const allContacts = useMemo<AddressContact[]>(
    () => (isAuthed ? serverContacts.map(serverToLocal) : loadContacts()),
    [isAuthed, serverContacts],
  )

  // ── Validate + check contact book ────────────────────────────────────────
  const validate = useCallback((addr: string) => {
    if (!addr) {
      setAddrError(''); setIsValid(false); setIsNew(false)
      onValidation?.(false, '')
      return
    }
    if (!isAddress(addr)) {
      setAddrError(t('invalidAddress')); setIsValid(false); setIsNew(false)
      onValidation?.(false, t('invalidAddress'))
      return
    }
    // Valid — check if known
    setAddrError(''); setIsValid(true)
    const contacts = allContacts
    const known = contacts.some(c => c.address.toLowerCase() === addr.toLowerCase())
    setIsNew(!known)
    onValidation?.(true, '')
  }, [onValidation, t, allContacts])

  useEffect(() => { validate(value) }, [value, validate])

  // ── Suggestions from contact book ────────────────────────────────────────
  const updateSuggestions = useCallback((query: string) => {
    if (!query || query.length < 2) { setSuggestions([]); return }
    const contacts = allContacts
    const q = query.toLowerCase()
    const matches = contacts
      .filter(c =>
        c.address.toLowerCase().includes(q) ||
        c.label.toLowerCase().includes(q)
      )
      .sort((a, b) => new Date(b.lastUsed).getTime() - new Date(a.lastUsed).getTime())
      .slice(0, 5)
    setSuggestions(matches)
  }, [allContacts])

  // ── Paste detection ──────────────────────────────────────────────────────
  const handlePaste = useCallback(() => {
    setPasteBanner(true)
    const t = setTimeout(() => setPasteBanner(false), 5000)
    return () => clearTimeout(t)
  }, [])

  // ── Close suggestions on outside click ───────────────────────────────────
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // ── Border color logic ───────────────────────────────────────────────────
  const borderColor = addrError
    ? `${T.red}40`
    : isValid && isNew
      ? `${T.amber}40`
      : isValid
        ? `${T.emerald}25`
        : T.border

  // ── Status indicator color ───────────────────────────────────────────────
  const dotColor = addrError ? T.red : isValid && isNew ? T.amber : isValid ? T.emerald : null

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      {/* ── Input row with identicon ─────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {/* Identicon — shown only when valid */}
        {isValid && value && (
          <Identicon address={value} size={28} />
        )}

        <input
          type="text"
          placeholder="0x... o ENS"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          value={value}
          onChange={e => {
            onChange(e.target.value)
            updateSuggestions(e.target.value)
            setShowSuggestions(true)
          }}
          onPaste={handlePaste}
          onFocus={() => { setFocused(true); if (suggestions.length) setShowSuggestions(true) }}
          onBlur={() => { setFocused(false); setTimeout(() => setShowSuggestions(false), 150) }}
          disabled={disabled}
          style={{
            ...inputStyle,
            flex: 1,
            fontSize: 16,
            borderColor,
          }}
        />

        {/* Status dot */}
        {dotColor && (
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: dotColor,
            boxShadow: `0 0 6px ${dotColor}`,
            flexShrink: 0,
          }} />
        )}
      </div>

      {/* ── Validation / New address badges ──────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, minHeight: 18 }}>
        {addrError && (
          <span style={{
            fontFamily: T.D, fontSize: 10, fontWeight: 600, color: T.red,
          }}>
            {addrError}
          </span>
        )}
        {isValid && !addrError && isNew && (
          <span style={{
            fontFamily: T.D, fontSize: 10, fontWeight: 700,
            color: T.amber,
            background: `${T.amber}15`,
            padding: '2px 8px',
            borderRadius: 6,
            border: `1px solid ${T.amber}30`,
          }}>
            Nuovo destinatario
          </span>
        )}
        {isValid && !addrError && !isNew && (
          <span style={{
            fontFamily: T.D, fontSize: 10, fontWeight: 600, color: T.emerald,
          }}>
            Contatto conosciuto
          </span>
        )}
      </div>

      {/* ── Paste banner ─────────────────────────────────────────────────── */}
      {pasteBanner && (
        <div style={{
          marginTop: 6, padding: '8px 12px', borderRadius: 10,
          background: `${T.purple}0d`,
          border: `1px solid ${T.purple}30`,
          display: 'flex', alignItems: 'center', gap: 8,
          animation: 'rpFadeUp 0.2s var(--ease-spring) both',
        }}>
          <span style={{ fontSize: 13 }}>📋</span>
          <span style={{ fontFamily: T.D, fontSize: 11, fontWeight: 500, color: T.purple }}>
            Indirizzo incollato — verifica che sia corretto
          </span>
        </div>
      )}

      {/* ── Suggestions dropdown ─────────────────────────────────────────── */}
      {showSuggestions && suggestions.length > 0 && (
        <div style={{
          position: 'absolute', left: 0, right: 0, top: '100%',
          marginTop: 4, zIndex: 100,
          background: '#FFFFFF',
          border: `1px solid rgba(10,10,10,0.10)`,
          borderRadius: 12,
          boxShadow: '0 12px 40px rgba(0,0,0,0.7)',
          overflow: 'hidden',
        }}>
          <div style={{
            padding: '6px 12px',
            fontFamily: T.D, fontSize: 10, fontWeight: 700,
            textTransform: 'uppercase' as const, letterSpacing: '0.08em',
            color: T.muted, borderBottom: `1px solid ${T.border}`,
          }}>
            Contatti recenti
          </div>
          {suggestions.map((contact, i) => (
            <button
              key={contact.address}
              type="button"
              onMouseDown={e => {
                e.preventDefault()
                onChange(contact.address)
                setShowSuggestions(false)
              }}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px',
                background: 'transparent',
                border: 'none',
                borderBottom: i < suggestions.length - 1 ? `1px solid ${T.border}` : 'none',
                cursor: 'pointer',
                transition: 'background 0.1s',
                textAlign: 'left',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(10,10,10,0.04)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <Identicon address={contact.address} size={24} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {contact.label && (
                  <div style={{ fontFamily: T.D, fontSize: 12, fontWeight: 600, color: T.text, marginBottom: 1 }}>
                    {contact.label}
                  </div>
                )}
                <div style={{ fontFamily: T.M, fontSize: 11, color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>
                  {contact.address.slice(0, 6)}...{contact.address.slice(-4)}
                </div>
              </div>
              <div style={{ fontFamily: T.M, fontSize: 10, color: T.muted, flexShrink: 0 }}>
                {contact.txCount} tx
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
