'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

import { C, SPRING as EASE } from '@/app/designTokens'
const T = { ...C, emerald: '#00ffa3', muted: C.sub, dim: 'rgba(10,10,10,0.30)' }

const SUGGESTIONS = ['Alpha-99', 'Luna-42', 'Crypto-77', 'Orion-13', 'Nova-56']

interface AntiPhishingSetupProps {
  isOpen: boolean
  onClose: () => void
  onSave: (code: string) => void
}

export default function AntiPhishingSetup({ isOpen, onClose, onSave }: AntiPhishingSetupProps) {
  const [code, setCode] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (isOpen) {
      try {
        const existing = localStorage.getItem('rsend_antiphishing_code')
        if (existing) setCode(existing)
      } catch {}
      setSaved(false)
    }
  }, [isOpen])

  // ESC to close
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  const handleSave = () => {
    const trimmed = code.trim()
    if (!trimmed) return
    onSave(trimmed)
    setSaved(true)
    setTimeout(() => onClose(), 600)
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            key="ap-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            style={{
              position: 'fixed', inset: 0, zIndex: 3000,
              background: 'rgba(0,0,0,0.60)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
            }}
          />

          {/* Modal */}
          <motion.div
            key="ap-modal"
            initial={{ opacity: 0, scale: 0.96, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 20 }}
            transition={{ duration: 0.3, ease: EASE }}
            style={{
              position: 'fixed',
              top: '50%', left: '50%',
              transform: 'translate(-50%, -50%)',
              zIndex: 3001,
              width: '90%',
              maxWidth: 400,
              background: '#FFFFFF',
              borderRadius: 20,
              border: '1px solid rgba(10,10,10,0.10)',
              boxShadow: '0 40px 100px rgba(0,0,0,0.7)',
              padding: 24,
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <span style={{ fontFamily: T.D, fontSize: 16, fontWeight: 700, color: T.text, letterSpacing: '-0.02em' }}>
                Codice Anti-Phishing
              </span>
              <button
                onClick={onClose}
                style={{
                  width: 32, height: 32, borderRadius: 10,
                  background: 'rgba(10,10,10,0.08)',
                  border: `1px solid ${T.border}`,
                  color: T.muted, cursor: 'pointer', fontSize: 14,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >✕</button>
            </div>

            {/* Description */}
            <p style={{
              fontFamily: T.M, fontSize: 12, color: T.muted,
              lineHeight: 1.6, margin: '0 0 20px',
            }}>
              Questo codice apparir&agrave; nella schermata di conferma di ogni transazione.
              Se non lo vedi, il sito potrebbe essere un clone malevolo.
            </p>

            {/* Input */}
            <input
              type="text"
              value={code}
              onChange={e => setCode(e.target.value.slice(0, 20))}
              placeholder="Es. Alpha-99"
              style={{
                width: '100%',
                padding: '14px 16px',
                borderRadius: 12,
                border: `1px solid rgba(10,10,10,0.10)`,
                background: 'rgba(10,10,10,0.04)',
                color: T.text,
                fontFamily: T.M,
                fontSize: 14,
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ fontFamily: T.M, fontSize: 10, color: T.dim, marginTop: 6, marginBottom: 16 }}>
              Max 20 caratteri — {20 - code.length} rimanenti
            </div>

            {/* Suggestions */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
              {SUGGESTIONS.map(s => (
                <button
                  key={s}
                  onClick={() => setCode(s)}
                  style={{
                    padding: '6px 12px', borderRadius: 8,
                    background: code === s ? 'rgba(200,81,44,0.15)' : 'rgba(10,10,10,0.04)',
                    border: `1px solid ${code === s ? 'rgba(200,81,44,0.3)' : T.border}`,
                    color: code === s ? '#C8512C' : T.muted,
                    fontFamily: T.M, fontSize: 11,
                    cursor: 'pointer', transition: 'all 0.15s',
                  }}
                >
                  {s}
                </button>
              ))}
            </div>

            {/* Save button */}
            <button
              onClick={handleSave}
              disabled={!code.trim()}
              style={{
                width: '100%', padding: 16, borderRadius: 14, border: 'none',
                fontFamily: T.D, fontSize: 15, fontWeight: 700,
                background: saved
                  ? 'linear-gradient(135deg, #00ffa3, #00cc80)'
                  : code.trim()
                    ? 'linear-gradient(135deg, #C8512C, #C8512C)'
                    : 'rgba(10,10,10,0.08)',
                color: saved ? '#000' : code.trim() ? '#fff' : T.dim,
                cursor: code.trim() ? 'pointer' : 'not-allowed',
                transition: 'all 0.2s ease',
              }}
            >
              {saved ? '✓ Salvato' : 'Salva Codice'}
            </button>

            {/* Remove option if existing */}
            {code.trim() && (
              <button
                onClick={() => {
                  localStorage.removeItem('rsend_antiphishing_code')
                  setCode('')
                  onSave('')
                  onClose()
                }}
                style={{
                  width: '100%', padding: 12, marginTop: 8, borderRadius: 14, border: 'none',
                  fontFamily: T.M, fontSize: 12, color: T.dim,
                  background: 'transparent', cursor: 'pointer',
                }}
              >
                Rimuovi codice
              </button>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
