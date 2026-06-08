'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence, type PanInfo } from 'framer-motion'
import { useTranslations } from 'next-intl'
import type { TokenInfo } from './tokens/tokenRegistry'

// ── Theme (matches TransferForm T) ──────────────────────────────────────────
import { C, SPRING as EASE } from '@/app/designTokens'
const T = { ...C, success: '#16A34A', terracotta: '#C8512C', muted: C.sub, pink: C.purple, red: '#ff2d55', amber: '#ffb800' }
const GAS_EXPIRY_SEC = 60
const HOLD_DURATION = 3000

// ── Deterministic identicon from address (4x4 grid) ─────────────────────────
function generateIdenticon(address: string): string[] {
  const hash = address.toLowerCase().slice(2)
  const colors: string[] = []
  for (let i = 0; i < 16; i++) {
    const byte = parseInt(hash.slice(i * 2, i * 2 + 2) || '00', 16)
    const hue = (byte * 360) / 255
    colors.push(`hsl(${hue}, 65%, 55%)`)
  }
  return colors
}

function Identicon({ address, size = 32 }: { address: string; size?: number }) {
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

// ── Gas level visual indicator ──────────────────────────────────────────────
function GasLevelBar({ level }: { level: 'low' | 'medium' | 'normal' | 'high' | 'extreme' }) {
  const t = useTranslations('txConfirmation')
  const lvl = level === 'medium' ? 'normal' : level
  const segments = lvl === 'low' ? 1 : lvl === 'normal' ? 2 : lvl === 'high' ? 3 : 4
  const color = lvl === 'extreme' ? T.red : lvl === 'high' ? T.amber : T.green
  return (
    <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          style={{
            width: 8, height: 10, borderRadius: 2,
            background: i < segments ? color : 'rgba(10,10,10,0.08)',
            transition: 'background 0.2s',
          }}
        />
      ))}
      <span style={{ fontFamily: T.M, fontSize: 10, color, marginLeft: 4, textTransform: 'capitalize' }}>
        {lvl === 'low' ? t('gasLow') : lvl === 'normal' ? t('gasNormal') : lvl === 'high' ? t('gasHigh') : t('gasExtreme')}
      </span>
    </div>
  )
}

// ── Token icon with fallback ────────────────────────────────────────────────
const TOKEN_COLORS: Record<string, string> = {
  ETH: '#627EEA', USDC: '#2775CA', USDT: '#26A17B', DAI: '#F5AC37',
  WETH: '#627EEA', cbBTC: '#F7931A', ARB: '#28A0F0',
}

function ConfTokenIcon({ token, size = 28 }: { token: TokenInfo; size?: number }) {
  const [imgErr, setImgErr] = useState(false)
  const color = TOKEN_COLORS[token.symbol] ?? '#4a4a6a'
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      overflow: 'hidden', flexShrink: 0,
      background: imgErr ? color : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: '1.5px solid rgba(10,10,10,0.08)',
    }}>
      {!imgErr ? (
        <img
          src={token.logoUrl} alt={token.symbol}
          width={size} height={size}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.36, fontWeight: 800, color: '#fff', fontFamily: T.D }}>
          {token.symbol.slice(0, 2)}
        </span>
      )}
    </div>
  )
}

// ── Chain icon with fallback ────────────────────────────────────────────────
function ConfChainIcon({ chain, size = 16 }: { chain: { name: string; iconUrl: string }; size?: number }) {
  const [imgErr, setImgErr] = useState(false)
  return (
    <div style={{
      width: size, height: size, borderRadius: 4,
      overflow: 'hidden', flexShrink: 0,
      background: imgErr ? '#333' : 'transparent',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {!imgErr ? (
        <img
          src={chain.iconUrl} alt={chain.name}
          width={size} height={size}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <span style={{ fontSize: size * 0.55, fontWeight: 700, color: '#fff' }}>
          {chain.name.charAt(0)}
        </span>
      )}
    </div>
  )
}

// ── Known recipient helpers ─────────────────────────────────────────────────
export function isKnownRecipient(address: string): boolean {
  try {
    const known = JSON.parse(localStorage.getItem('rsend_known_recipients') || '[]')
    return known.includes(address.toLowerCase())
  } catch { return false }
}

export function saveKnownRecipient(address: string) {
  try {
    const known = JSON.parse(localStorage.getItem('rsend_known_recipients') || '[]')
    if (!known.includes(address.toLowerCase())) {
      known.push(address.toLowerCase())
      localStorage.setItem('rsend_known_recipients', JSON.stringify(known))
    }
  } catch {}
}

// ── Props ───────────────────────────────────────────────────────────────────
export interface TxConfirmationProps {
  isOpen: boolean
  onConfirm: () => void
  onCancel: () => void
  recipient: string

  // Token & amount
  tokenInfo: TokenInfo            // token selezionato (full registry entry)
  amount: string                  // importo human-readable (e.g. "100.50")
  eurValue: number | null         // controvalore EUR (da price service)
  feeAmount: string               // fee in token units (e.g. "0.50")
  netAmount: string               // netto al destinatario (e.g. "99.50")

  // Gas
  gasEstimate: {
    eth: string                   // gas in ETH (e.g. "0.001")
    eur: number | null            // gas in EUR
    level: 'low' | 'medium' | 'high'
  }

  // Chain
  chain: {
    name: string
    iconUrl: string
  }

  // Features (unchanged)
  estimatedTime?: string
  isHighValue?: boolean
  isNewRecipient?: boolean
  antiPhishingCode?: string
  isMobile?: boolean
}

export default function TxConfirmationSheet({
  isOpen, onConfirm, onCancel,
  recipient,
  tokenInfo, amount, eurValue,
  feeAmount, netAmount,
  gasEstimate, chain,
  estimatedTime,
  isHighValue, isNewRecipient,
  antiPhishingCode,
  isMobile: isMobileProp,
}: TxConfirmationProps) {
  const t = useTranslations('txConfirmation')
  const [isMobile, setIsMobile] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [expired, setExpired] = useState(false)
  const [copied, setCopied] = useState(false)
  const [holdProgress, setHoldProgress] = useState(0)
  const holdRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [mounted, setMounted] = useState(false)

  // Portal mount guard
  useEffect(() => { setMounted(true) }, [])

  // Detect mobile
  useEffect(() => {
    if (isMobileProp !== undefined) { setIsMobile(isMobileProp); return }
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [isMobileProp])

  // Reset state when sheet opens/closes
  useEffect(() => {
    if (!isOpen) { setElapsed(0); setExpired(false); setHoldProgress(0); return }
    setElapsed(0)
    setExpired(false)
    setHoldProgress(0)
  }, [isOpen])

  // Gas expiry timer
  useEffect(() => {
    if (!isOpen) return
    const interval = setInterval(() => {
      setElapsed(prev => {
        if (prev >= GAS_EXPIRY_SEC) { setExpired(true); clearInterval(interval); return GAS_EXPIRY_SEC }
        return prev + 1
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [isOpen])

  // ESC to close
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onCancel() }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isOpen, onCancel])

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(recipient)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [recipient])

  // ── Hold to confirm (high value) ──────────────────────────────────────────
  const handlePointerDown = useCallback(() => {
    if (expired || !isHighValue) return
    holdRef.current = setInterval(() => {
      setHoldProgress(prev => {
        if (prev >= 100) {
          if (holdRef.current) clearInterval(holdRef.current)
          onConfirm()
          return 100
        }
        return prev + (100 / (HOLD_DURATION / 50))
      })
    }, 50)
  }, [expired, isHighValue, onConfirm])

  const handlePointerUp = useCallback(() => {
    if (holdRef.current) clearInterval(holdRef.current)
    holdRef.current = null
    setHoldProgress(0)
  }, [])

  // Cleanup hold interval on unmount
  useEffect(() => {
    return () => { if (holdRef.current) clearInterval(holdRef.current) }
  }, [])

  const handleConfirmClick = () => {
    if (expired) { onCancel(); return }
    if (!isHighValue) { onConfirm(); return }
    // High value uses hold — click alone does nothing
  }

  // ── Swipe to dismiss (mobile) ─────────────────────────────────────────────
  const handleDragEnd = (_: unknown, info: PanInfo) => {
    if (info.velocity.y > 300 || info.offset.y > 150) {
      onCancel()
    }
  }

  // Format address for display
  const displayAddress = isMobile
    ? `${recipient.slice(0, 10)}...${recipient.slice(-8)}`
    : recipient

  const progressPct = Math.min((elapsed / GAS_EXPIRY_SEC) * 100, 100)

  // ── Content ───────────────────────────────────────────────────────────────
  const content = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          
          <span style={{ fontFamily: T.D, fontSize: 17, fontWeight: 700, color: T.text, letterSpacing: '-0.02em' }}>
            {t('confirmTransaction')}
          </span>
        </div>
        <button
          onClick={onCancel}
          style={{
            width: 32, height: 32, borderRadius: 10,
            background: 'rgba(10,10,10,0.08)',
            border: `1px solid ${T.border}`, color: T.muted,
            cursor: 'pointer', fontSize: 14,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >✕</button>
      </div>

      {/* Amount card */}
      <div style={{
        padding: '20px 16px', borderRadius: 16,
        background: 'rgba(10,10,10,0.04)',
        border: '1px solid rgba(10,10,10,0.10)',
        textAlign: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
          <ConfTokenIcon token={tokenInfo} size={isMobile ? 32 : 38} />
          <span style={{
            fontFamily: T.D,
            fontSize: isMobile ? 28 : 36,
            fontWeight: 700,
            color: T.text,
            letterSpacing: '-0.03em',
          }}>
            {amount} {tokenInfo.symbol}
          </span>
        </div>
        {eurValue != null && eurValue > 0 && (
          <div style={{ fontFamily: T.M, fontSize: 14, color: T.muted, marginTop: 6 }}>
            ≈ €{eurValue.toFixed(2)}
          </div>
        )}
      </div>

      {/* Recipient card */}
      <div style={{
        padding: '14px 16px', borderRadius: 16,
        background: 'rgba(10,10,10,0.04)',
        border: '1px solid rgba(10,10,10,0.10)',
      }}>
        <div style={{
          fontFamily: T.M, fontSize: 10, color: T.muted, marginBottom: 10,
          textTransform: 'uppercase', letterSpacing: '0.08em',
        }}>
          {t('recipient')}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Identicon address={recipient} size={36} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontFamily: T.M, fontSize: 12, color: T.text,
              wordBreak: 'break-all', lineHeight: 1.5,
            }}>
              {displayAddress}
            </div>
          </div>
          <button
            onClick={handleCopy}
            style={{
              width: 32, height: 32, borderRadius: 8, flexShrink: 0,
              background: 'rgba(10,10,10,0.08)',
              border: `1px solid ${T.border}`,
              cursor: 'pointer', fontSize: 12,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: copied ? T.success : T.muted,
              transition: 'color 0.2s',
            }}
          >
            {copied ? '✓' : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
                <path d="M2 10V2.5A.5.5 0 012.5 2H10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
            )}
          </button>
        </div>

        {/* New recipient warning */}
        {isNewRecipient && (
          <div style={{
            marginTop: 10, padding: '7px 10px', borderRadius: 8,
            background: `${T.amber}0d`, border: `1px solid ${T.amber}25`,
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{ fontSize: 12 }}>⚠️</span>
            <span style={{ fontFamily: T.D, fontSize: 11, fontWeight: 600, color: T.amber }}>
              {t('firstSendWarning')}
            </span>
          </div>
        )}
      </div>

      {/* Dettagli (unified) */}
      <div style={{
        padding: '12px 16px', borderRadius: 14,
        background: 'rgba(10,10,10,0.04)',
        border: '1px solid rgba(10,10,10,0.08)',
        display: 'flex', flexDirection: 'column', gap: 10,
      }}>
        {/* Token */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('token')}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ConfTokenIcon token={tokenInfo} size={16} />
            <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 600, color: T.text }}>
              {tokenInfo.symbol}
            </span>
            <span style={{ fontFamily: T.M, fontSize: 11, color: T.dim }}>
              ({tokenInfo.name})
            </span>
          </div>
        </div>

        {/* Rete */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('network')}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ConfChainIcon chain={chain} size={16} />
            <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 600, color: T.text }}>{chain.name}</span>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: T.success }} />
          </div>
        </div>

        {/* Fee RSends */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('feeRSends')}</span>
          <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 600, color: T.amber }}>
            {feeAmount} {tokenInfo.symbol} (0.5%)
          </span>
        </div>

        {/* Netto dest. */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('netRecipient')}</span>
          <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 700, color: T.text }}>
            {netAmount} {tokenInfo.symbol}
          </span>
        </div>

        {/* Gas Fee */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('gasFee')}</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 600, color: T.text }}>
              ~{gasEstimate.eth} ETH
              {gasEstimate.eur != null && gasEstimate.eur > 0 && (
                <span style={{ fontFamily: T.M, fontSize: 11, color: T.dim, marginLeft: 4 }}>
                  (~€{gasEstimate.eur.toFixed(2)})
                </span>
              )}
            </span>
            <GasLevelBar level={gasEstimate.level} />
          </div>
        </div>

        {/* Tempo */}
        {estimatedTime && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: T.M, fontSize: 11, color: T.muted }}>{t('time')}</span>
            <span style={{ fontFamily: T.D, fontSize: 13, fontWeight: 600, color: T.text }}>{estimatedTime}</span>
          </div>
        )}
      </div>

      {/* High value warning */}
      {isHighValue && (
        <div style={{
          padding: '10px 14px', borderRadius: 12,
          background: `${T.amber}0d`, border: `1px solid ${T.amber}30`,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 16 }}>⚠️</span>
          <span style={{ fontFamily: T.D, fontSize: 12, fontWeight: 600, color: T.amber }}>
            {t('highAmountWarning')}
          </span>
        </div>
      )}

      {/* Anti-phishing code */}
      {antiPhishingCode && (
        <div style={{
          padding: '10px 14px', borderRadius: 12,
          background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.15)',
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 14 }}>🔑</span>
          <span style={{ fontFamily: T.M, fontSize: 12, color: T.purple }}>
            {t('antiPhishingCode')} <strong>{antiPhishingCode}</strong>
          </span>
        </div>
      )}

      {/* Confirm button */}
      {isHighValue && !expired ? (
        <button
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          style={{
            position: 'relative', width: '100%', padding: 18, borderRadius: 14, border: 'none',
            fontFamily: T.D, fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em',
            background: 'rgba(10,10,10,0.08)',
            color: T.text, cursor: 'pointer',
            overflow: 'hidden', userSelect: 'none',
            WebkitUserSelect: 'none',
          }}
        >
          {/* Hold fill progress */}
          <div style={{
            position: 'absolute', top: 0, left: 0, bottom: 0,
            width: `${holdProgress}%`,
            background: `linear-gradient(135deg, ${T.terracotta}, #A8421F)`,
            transition: holdProgress === 0 ? 'width 0.15s ease' : 'none',
            borderRadius: 14,
          }} />
          <span style={{ position: 'relative', zIndex: 1, color: holdProgress > 50 ? '#FFFFFF' : T.text }}>
            {holdProgress > 0
              ? `${Math.round(holdProgress)}%`
              : t('holdToConfirm')
            }
          </span>
        </button>
      ) : (
        <button
          onClick={handleConfirmClick}
          style={{
            width: '100%', padding: 18, borderRadius: 14, border: 'none',
            fontFamily: T.D, fontSize: 16, fontWeight: 700, letterSpacing: '-0.01em',
            background: expired
              ? `linear-gradient(135deg, ${T.purple}, #c084fc)`
              : `linear-gradient(135deg, #C8512C, #A8421F)`,
            color: expired ? '#fff' : '#FFFFFF',
            cursor: 'pointer',
            boxShadow: expired
              ? `0 4px 20px ${T.purple}25`
              : `0 4px 20px rgba(200,81,44,0.15)`,
            transition: 'all 0.2s ease',
          }}
        >
          {expired ? t('refreshQuote') : t('confirmSend')}
        </button>
      )}

      {/* Cancel */}
      <button
        onClick={onCancel}
        style={{
          width: '100%', padding: 12, borderRadius: 14, border: 'none',
          fontFamily: T.D, fontSize: 13, fontWeight: 600,
          background: 'rgba(10,10,10,0.04)',
          color: T.muted, cursor: 'pointer',
        }}
      >
        {t('cancel')}
      </button>

      {/* Gas expiry progress bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontFamily: T.M, fontSize: 10, color: T.dim, flexShrink: 0 }}>
          {expired ? t('expired') : `${GAS_EXPIRY_SEC - elapsed}s`}
        </span>
        <div style={{
          flex: 1, height: 3, borderRadius: 2,
          background: 'rgba(10,10,10,0.08)',
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${progressPct}%`,
            height: '100%', borderRadius: 2,
            background: expired ? T.red : T.purple,
            transition: 'width 1s linear',
          }} />
        </div>
      </div>
    </div>
  )

  if (!mounted) return null

  // ── Render via portal ─────────────────────────────────────────────────────
  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            key="tx-confirm-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onCancel}
            style={{
              position: 'fixed', inset: 0, zIndex: 2000,
              background: 'rgba(0,0,0,0.60)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
            }}
          />

          {/* Sheet / Modal */}
          {!isMobile && (
            <div style={{
              position: 'fixed', inset: 0, zIndex: 2001,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              pointerEvents: 'none',
            }}>
              <motion.div
                key="tx-confirm-sheet-desktop"
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.95, y: 20 }}
                transition={{ duration: 0.3, ease: EASE }}
                style={{
                  width: '90%',
                  maxWidth: 480,
                  maxHeight: '85vh',
                  overflowY: 'auto',
                  background: '#FFFFFF',
                  borderRadius: 20,
                  border: '1px solid rgba(10,10,10,0.10)',
                  boxShadow: '0 40px 100px rgba(0,0,0,0.7)',
                  padding: 24,
                  pointerEvents: 'auto',
                }}
              >
                {content}
              </motion.div>
            </div>
          )}
          {isMobile && (
          <motion.div
            key="tx-confirm-sheet"
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            drag="y"
            dragConstraints={{ top: 0 }}
            dragElastic={0.15}
            onDragEnd={handleDragEnd}
            style={{
              position: 'fixed',
              bottom: 0, left: 0, right: 0,
              zIndex: 2001,
              background: '#FFFFFF',
              borderTopLeftRadius: 24,
              borderTopRightRadius: 24,
              border: '1px solid rgba(10,10,10,0.10)',
              borderBottom: 'none',
              boxShadow: '0 -16px 64px rgba(0,0,0,0.7)',
              padding: '16px 20px calc(20px + var(--sab, 0px))',
              maxHeight: '85vh',
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch' as never,
            }}
          >
            {/* Drag handle — mobile only */}
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 10 }}>
              <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(10,10,10,0.15)' }} />
            </div>
            {content}
          </motion.div>
          )}
        </>
      )}
    </AnimatePresence>,
    document.body,
  )
}
