'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, useInView } from 'framer-motion'
import { C, EASE } from '@/app/designTokens'

const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

// ── Animated counter ──
function AnimatedNumber({ target, prefix = '', suffix = '', decimals = 2 }: { target: number; prefix?: string; suffix?: string; decimals?: number }) {
  const [value, setValue] = useState(0)
  const ref = useRef(null)
  const inView = useInView(ref, { once: true })
  const raf = useRef<number>(0)

  useEffect(() => {
    if (!inView) return
    const start = performance.now()
    const duration = 1200
    const animate = (now: number) => {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(eased * target)
      if (progress < 1) raf.current = requestAnimationFrame(animate)
    }
    raf.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf.current)
  }, [inView, target])

  return (
    <span ref={ref}>
      {prefix}{value.toFixed(decimals)}{suffix}
    </span>
  )
}

export default function PricingOverlay() {
  const [amount, setAmount] = useState(1000)
  const fee = amount * 0.005
  const recipient = amount - fee

  const comparisonRows = [
    { feature: 'Transaction Fee', rsend: '0.5%', traditional: '2.5 — 3.5%', web3: '0.3 — 1%' },
    { feature: 'Settlement Time', rsend: '~2 seconds', traditional: '1 — 3 days', web3: '~15 seconds' },
    { feature: 'Pre-TX Compliance', rsend: true, traditional: false, web3: false },
    { feature: 'On-Chain Transparency', rsend: true, traditional: false, web3: true },
    { feature: 'Minimum Amount', rsend: 'None', traditional: '$50+', web3: 'Varies' },
    { feature: 'Custody', rsend: 'Non-custodial', traditional: 'Custodial', web3: 'Varies' },
  ]

  return (
    <div>
      {/* Header */}
      <h2 style={{ fontFamily: C.D, fontSize: 24, fontWeight: 800, color: C.text, marginBottom: 4 }}>
        <span style={GRAD}>Pricing</span>
      </h2>
      <p style={{ fontFamily: C.M, fontSize: 12, color: C.dim, marginBottom: 28 }}>
        Simple, transparent, on-chain. One fee for everything.
      </p>

      {/* ═══ A) The Fee Model ═══ */}
      <div style={{ marginBottom: 36 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          The Fee Model
        </div>
        <div style={{
          background: C.bg, borderRadius: 16, padding: '28px 24px',
          border: `1px solid ${C.border}`, textAlign: 'center',
        }}>
          <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginBottom: 12 }}>
            $1,000 USDC TRANSACTION
          </div>

          {/* Animated bar */}
          <div style={{ position: 'relative', height: 40, borderRadius: 10, overflow: 'hidden', background: 'rgba(10,10,10,0.04)', marginBottom: 20 }}>
            <motion.div
              initial={{ width: 0 }}
              whileInView={{ width: '99.5%' }}
              viewport={{ once: true }}
              transition={{ duration: 1.2, ease: EASE }}
              style={{
                position: 'absolute', top: 0, left: 0, bottom: 0,
                background: `linear-gradient(90deg, ${C.green}, ${C.green}cc)`,
                borderRadius: '10px 0 0 10px',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <span style={{ fontFamily: C.D, fontSize: 13, fontWeight: 700, color: '#000' }}>
                99.5% → Recipient
              </span>
            </motion.div>
            <motion.div
              initial={{ width: 0 }}
              whileInView={{ width: '4%' }}
              viewport={{ once: true }}
              transition={{ duration: 1.2, ease: EASE, delay: 0.3 }}
              style={{
                position: 'absolute', top: 0, right: 0, bottom: 0,
                background: 'linear-gradient(135deg, #FF4C6A, #C8512C)',
                borderRadius: '0 10px 10px 0',
                minWidth: 40,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <span style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: '#fff' }}>0.5%</span>
            </motion.div>
          </div>

          {/* Amounts */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: 40 }}>
            <div>
              <div style={{ fontFamily: C.D, fontSize: 28, fontWeight: 800, color: C.green }}>
                $<AnimatedNumber target={995} decimals={2} />
              </div>
              <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginTop: 4 }}>Recipient receives</div>
            </div>
            <div style={{ width: 1, background: C.border }} />
            <div>
              <div style={{
                fontFamily: C.D, fontSize: 28, fontWeight: 800,
                background: 'linear-gradient(135deg, #FF4C6A, #C8512C)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>
                $<AnimatedNumber target={5} decimals={2} />
              </div>
              <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, marginTop: 4 }}>Protocol fee</div>
            </div>
          </div>
        </div>
      </div>

      {/* ═══ B) Comparison Table ═══ */}
      <div style={{ marginBottom: 36 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          How We Compare
        </div>
        <div style={{
          borderRadius: 14, overflow: 'hidden',
          border: `1px solid ${C.border}`,
        }}>
          {/* Header row */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr',
            padding: '10px 14px', borderBottom: `1px solid ${C.border}`,
            background: 'rgba(10,10,10,0.02)',
          }}>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Feature</span>
            <span style={{ fontFamily: C.D, fontSize: 10, fontWeight: 700, color: C.blue, textAlign: 'center' }}>RSends</span>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textAlign: 'center' }}>Traditional</span>
            <span style={{ fontFamily: C.M, fontSize: 9, color: C.dim, textAlign: 'center' }}>Other Web3</span>
          </div>

          {/* Data rows */}
          {comparisonRows.map((row, i) => (
            <motion.div
              key={row.feature}
              initial={{ opacity: 0, x: -10 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.06, duration: 0.3 }}
              style={{
                display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr',
                padding: '10px 14px', alignItems: 'center',
                borderBottom: i < comparisonRows.length - 1 ? `1px solid ${C.border}` : 'none',
              }}
            >
              <span style={{ fontFamily: C.M, fontSize: 11, color: C.sub }}>{row.feature}</span>
              <span style={{
                fontFamily: C.M, fontSize: 11, textAlign: 'center',
                color: typeof row.rsend === 'boolean' ? (row.rsend ? C.green : C.red) : C.text,
                fontWeight: 600,
                padding: '0 4px',
                background: 'rgba(59,130,246,0.04)',
                borderRadius: 4,
              }}>
                {typeof row.rsend === 'boolean' ? (row.rsend ? '✓' : '✗') : row.rsend}
              </span>
              <span style={{
                fontFamily: C.M, fontSize: 10, textAlign: 'center',
                color: typeof row.traditional === 'boolean' ? (row.traditional ? C.green : 'rgba(255,76,106,0.6)') : C.dim,
              }}>
                {typeof row.traditional === 'boolean' ? (row.traditional ? '✓' : '✗') : row.traditional}
              </span>
              <span style={{
                fontFamily: C.M, fontSize: 10, textAlign: 'center',
                color: typeof row.web3 === 'boolean' ? (row.web3 ? C.green : 'rgba(255,76,106,0.6)') : C.dim,
              }}>
                {typeof row.web3 === 'boolean' ? (row.web3 ? '✓' : '✗') : row.web3}
              </span>
            </motion.div>
          ))}
        </div>
      </div>

      {/* ═══ C) Fee Calculator ═══ */}
      <div>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Fee Calculator
        </div>
        <div style={{
          background: C.bg, borderRadius: 16, padding: '24px 20px',
          border: `1px solid ${C.border}`,
        }}>
          {/* Input */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontFamily: C.M, fontSize: 10, color: C.dim, display: 'block', marginBottom: 8 }}>
              Transaction Amount (USDC)
            </label>
            <input
              type="number"
              value={amount}
              onChange={e => setAmount(Math.max(0, parseFloat(e.target.value) || 0))}
              style={{
                width: '100%', padding: '14px 16px', borderRadius: 12,
                background: 'rgba(10,10,10,0.08)', border: '1px solid rgba(10,10,10,0.12)',
                color: C.text, fontFamily: C.D, fontSize: 20, fontWeight: 700,
                outline: 'none', boxSizing: 'border-box',
                transition: 'border-color 0.2s',
              }}
              onFocus={e => e.currentTarget.style.borderColor = 'rgba(59,130,246,0.4)'}
              onBlur={e => e.currentTarget.style.borderColor = 'rgba(10,10,10,0.12)'}
            />
            {/* Quick amounts */}
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              {[100, 500, 1000, 5000, 10000].map(v => (
                <button
                  key={v}
                  onClick={() => setAmount(v)}
                  style={{
                    padding: '4px 10px', borderRadius: 6, border: `1px solid ${C.border}`,
                    background: amount === v ? 'rgba(59,130,246,0.1)' : 'transparent',
                    color: amount === v ? C.blue : C.dim,
                    fontFamily: C.M, fontSize: 9, cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  ${v.toLocaleString()}
                </button>
              ))}
            </div>
          </div>

          {/* Results */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <div style={{
              padding: '16px 14px', borderRadius: 12,
              background: 'rgba(0,214,143,0.06)', border: `1px solid ${C.green}15`,
              textAlign: 'center',
            }}>
              <div style={{ fontFamily: C.D, fontSize: 22, fontWeight: 800, color: C.green }}>
                ${recipient.toFixed(2)}
              </div>
              <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 4 }}>Recipient receives</div>
            </div>
            <div style={{
              padding: '16px 14px', borderRadius: 12,
              background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
              textAlign: 'center',
            }}>
              <div style={{
                fontFamily: C.D, fontSize: 22, fontWeight: 800,
                background: 'linear-gradient(135deg, #FF4C6A, #C8512C)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>
                ${fee.toFixed(2)}
              </div>
              <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 4 }}>Protocol fee (0.5%)</div>
            </div>
            <div style={{
              padding: '16px 14px', borderRadius: 12,
              background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
              textAlign: 'center',
            }}>
              <div style={{ fontFamily: C.D, fontSize: 22, fontWeight: 800, color: C.sub }}>
                ~$0.02
              </div>
              <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, marginTop: 4 }}>Est. gas (Base L2)</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
