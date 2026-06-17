'use client'

import { useEffect, useState } from 'react'
import { useToast, type ToastItem, type ToastType } from '../../hooks/useToast'

const COLORS: Record<ToastType, { bg: string; border: string; icon: string }> = {
  success: { bg: 'rgba(0,214,143,0.08)', border: 'rgba(0,214,143,0.25)', icon: '#00D68F' },
  error:   { bg: 'rgba(255,76,106,0.08)', border: 'rgba(255,76,106,0.25)', icon: '#FF4C6A' },
  warning: { bg: 'rgba(255,181,71,0.08)', border: 'rgba(255,181,71,0.25)', icon: '#FFB547' },
  info:    { bg: 'rgba(59,130,246,0.08)', border: 'rgba(59,130,246,0.25)', icon: '#3B82F6' },
}

const ICONS: Record<ToastType, string> = {
  success: '\u2713',
  error: '\u2715',
  warning: '!',
  info: 'i',
}

function ToastEntry({ item, onDismiss }: { item: ToastItem; onDismiss: () => void }) {
  const [visible, setVisible] = useState(false)
  const c = COLORS[item.type]

  useEffect(() => {
    // Trigger enter animation on next frame
    const raf = requestAnimationFrame(() => setVisible(true))
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <div
      role="alert"
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 14px',
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderRadius: 12,
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        transform: visible ? 'translateX(0)' : 'translateX(120%)',
        opacity: visible ? 1 : 0,
        transition: 'transform 0.3s cubic-bezier(0.4,0,0.2,1), opacity 0.3s ease',
        maxWidth: 360,
        pointerEvents: 'auto',
      }}
    >
      {/* Icon */}
      <div style={{
        width: 22, height: 22, borderRadius: '50%',
        background: `${c.icon}20`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 700, color: c.icon,
        fontFamily: 'var(--font-mono)',
        flexShrink: 0,
      }}>
        {ICONS[item.type]}
      </div>

      {/* Message */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 600,
          color: '#0A0A0A', lineHeight: 1.3,
          overflow: 'hidden', textOverflow: 'ellipsis',
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        } as React.CSSProperties}>
          {item.message}
        </div>
      </div>

      {/* Action button */}
      {item.action && (
        <button
          onClick={item.action.onClick}
          style={{
            padding: '4px 10px', borderRadius: 8, border: 'none',
            background: 'rgba(10,10,10,0.08)', color: c.icon,
            fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
            cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
          }}
        >
          {item.action.label}
        </button>
      )}

      {/* Dismiss */}
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          width: 18, height: 18, borderRadius: '50%', border: 'none',
          background: 'rgba(10,10,10,0.08)', color: 'rgba(10,10,10,0.55)',
          fontSize: 10, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {'\u2715'}
      </button>
    </div>
  )
}

export function ToastContainer() {
  const { toasts, dismiss } = useToast()

  if (toasts.length === 0) return null

  return (
    <div
      aria-live="polite"
      style={{
        position: 'fixed', top: 16, right: 16,
        display: 'flex', flexDirection: 'column', gap: 8,
        zIndex: 99999,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <ToastEntry key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  )
}
