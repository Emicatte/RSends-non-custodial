'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { C } from '@/app/designTokens'

interface Props {
  onStop: () => Promise<any>
  activeCount: number
}

export default function EmergencyStop({ onStop, activeCount }: Props) {
  const [showConfirm, setShowConfirm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const handleStop = async () => {
    setLoading(true)
    try {
      const data = await onStop()
      setResult(`${data.paused_count ?? 0} rules paused`)
      setShowConfirm(false)
      setTimeout(() => setResult(null), 4000)
    } catch {
      setResult('Failed')
      setTimeout(() => setResult(null), 3000)
    }
    setLoading(false)
  }

  return (
    <div>
      <AnimatePresence mode="wait">
        {showConfirm ? (
          <motion.div
            key="confirm"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ type: 'spring', bounce: 0, duration: 0.3 }}
            style={{
              background: `${C.red}08`,
              border: `1px solid ${C.red}30`,
              borderRadius: 14,
              padding: 16,
              textAlign: 'center',
            }}
          >
            <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 700, color: C.red, marginBottom: 6 }}>
              Emergency Stop
            </div>
            <div style={{ fontFamily: C.M, fontSize: 11, color: C.sub, marginBottom: 14 }}>
              This will pause all {activeCount} active rules immediately.
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => setShowConfirm(false)}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 10,
                  background: 'rgba(10,10,10,0.04)',
                  border: `1px solid ${C.border}`,
                  color: C.sub, fontFamily: C.D, fontSize: 12,
                  fontWeight: 600, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleStop}
                disabled={loading}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: 10,
                  background: C.red, border: 'none',
                  color: '#fff', fontFamily: C.D, fontSize: 12,
                  fontWeight: 700, cursor: loading ? 'wait' : 'pointer',
                  opacity: loading ? 0.7 : 1,
                  boxShadow: `0 4px 16px ${C.red}40`,
                }}
              >
                {loading ? 'Stopping...' : 'CONFIRM STOP'}
              </button>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="button"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            {result ? (
              <div style={{
                padding: '10px 14px', borderRadius: 10,
                background: `${C.red}08`, border: `1px solid ${C.red}20`,
                textAlign: 'center',
                fontFamily: C.M, fontSize: 11, color: C.red,
              }}>
                {result}
              </div>
            ) : (
              <button
                onClick={() => setShowConfirm(true)}
                disabled={activeCount === 0}
                style={{
                  width: '100%', padding: '12px 0', borderRadius: 12,
                  background: activeCount > 0 ? `${C.red}12` : 'rgba(10,10,10,0.02)',
                  border: `1px solid ${activeCount > 0 ? `${C.red}25` : C.border}`,
                  color: activeCount > 0 ? C.red : C.dim,
                  fontFamily: C.D, fontSize: 12, fontWeight: 700,
                  cursor: activeCount > 0 ? 'pointer' : 'not-allowed',
                  transition: 'all 0.2s',
                  letterSpacing: '0.03em',
                }}
              >
                EMERGENCY STOP
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
