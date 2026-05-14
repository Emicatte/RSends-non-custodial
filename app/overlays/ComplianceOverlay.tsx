'use client'

import { useState, useEffect, useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { C, EASE } from '@/app/designTokens'

const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

// ── SVG Icons for the three pillars ──
function MiCAIcon({ active }: { active: boolean }) {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
      <rect x="4" y="8" width="32" height="24" rx="4" stroke={active ? '#3B82F6' : 'rgba(10,10,10,0.55)'} strokeWidth="1.5" fill="none">
        <animate attributeName="stroke-opacity" values="0.6;1;0.6" dur="3s" repeatCount="indefinite" />
      </rect>
      <path d="M12 16h16M12 20h12M12 24h8" stroke={active ? '#C8512C' : 'rgba(10,10,10,0.45)'} strokeWidth="1.2" strokeLinecap="round">
        <animate attributeName="stroke-dashoffset" from="40" to="0" dur="1.5s" fill="freeze" />
      </path>
      <circle cx="32" cy="12" r="4" fill={active ? '#3B82F6' : 'rgba(10,10,10,0.55)'}>
        <animate attributeName="r" values="3.5;4.5;3.5" dur="2s" repeatCount="indefinite" />
      </circle>
      <path d="M30.5 12l1 1 2-2" stroke="white" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function AMLIcon({ active }: { active: boolean }) {
  return (
    <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
      <path d="M20 6L8 14v10c0 6 5.3 11.6 12 13 6.7-1.4 12-7 12-13V14L20 6z" stroke={active ? C.green : 'rgba(10,10,10,0.55)'} strokeWidth="1.5" fill="none">
        <animate attributeName="stroke-dasharray" values="0,100;80,100" dur="1.5s" fill="freeze" />
      </path>
      <path d="M16 20l3 3 5-6" stroke={active ? C.green : 'rgba(10,10,10,0.45)'} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ── Pipeline step node ──
function PipelineNode({ step, index, total }: { step: { icon: string; title: string; desc: string }; index: number; total: number }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-40px' })

  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, position: 'relative' }}>
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={inView ? { opacity: 1, scale: 1 } : {}}
        transition={{ duration: 0.5, delay: index * 0.15, ease: EASE }}
        style={{
          width: 56, height: 56, borderRadius: 14,
          background: inView ? 'rgba(59,130,246,0.1)' : 'rgba(10,10,10,0.03)',
          border: `1px solid ${inView ? 'rgba(59,130,246,0.3)' : C.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, transition: 'all 0.5s ease',
          boxShadow: inView ? '0 0 20px rgba(59,130,246,0.15)' : 'none',
        }}
      >
        {step.icon}
      </motion.div>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.4, delay: index * 0.15 + 0.2, ease: EASE }}
        style={{ textAlign: 'center', marginTop: 10 }}
      >
        <div style={{ fontFamily: C.D, fontSize: 11, fontWeight: 700, color: C.text, marginBottom: 3 }}>{step.title}</div>
        <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim, lineHeight: 1.4, maxWidth: 100 }}>{step.desc}</div>
      </motion.div>
      {/* Connecting arrow */}
      {index < total - 1 && (
        <motion.div
          initial={{ scaleX: 0 }}
          animate={inView ? { scaleX: 1 } : {}}
          transition={{ duration: 0.4, delay: index * 0.15 + 0.1 }}
          style={{
            position: 'absolute', top: 28, left: '75%', width: '50%', height: 2,
            background: 'linear-gradient(90deg, rgba(59,130,246,0.4), rgba(59,130,246,0.1))',
            transformOrigin: 'left',
          }}
        />
      )}
    </div>
  )
}

// ── Typewriter effect ──
function Typewriter({ text, delay = 0, speed = 30 }: { text: string; delay?: number; speed?: number }) {
  const [displayed, setDisplayed] = useState('')
  const ref = useRef(null)
  const inView = useInView(ref, { once: true })

  useEffect(() => {
    if (!inView) return
    let i = 0
    const timer = setTimeout(() => {
      const iv = setInterval(() => {
        i++
        setDisplayed(text.slice(0, i))
        if (i >= text.length) clearInterval(iv)
      }, speed)
      return () => clearInterval(iv)
    }, delay)
    return () => clearTimeout(timer)
  }, [inView, text, delay, speed])

  return <span ref={ref}>{displayed}<span style={{ opacity: 0.4, animation: 'rpPulse 1s ease infinite' }}>|</span></span>
}

// ── Tooltip ──
function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false)
  return (
    <div
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
          style={{
            position: 'absolute', bottom: '110%', left: '50%', transform: 'translateX(-50%)',
            background: '#FAFAFA', border: `1px solid ${C.border}`, borderRadius: 8,
            padding: '6px 10px', whiteSpace: 'nowrap', zIndex: 10,
            fontFamily: C.M, fontSize: 9, color: C.sub, lineHeight: 1.4,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            pointerEvents: 'none',
          }}
        >
          {text}
        </motion.div>
      )}
    </div>
  )
}

export default function ComplianceOverlay() {
  const [expanded, setExpanded] = useState<string | null>(null)

  const pillars = [
    {
      key: 'mica',
      title: 'MiCA',
      subtitle: 'Markets in Crypto-Assets',
      Icon: MiCAIcon,
      details: {
        requires: 'Authorization for crypto-asset service providers (CASPs), transparency obligations, consumer protection, and governance requirements across EU member states.',
        implements: 'RSends operates as a non-custodial protocol with full transaction transparency. Every operation is verifiable on-chain with pre-transaction compliance attestation.',
        component: 'EIP-712 Oracle — cryptographic attestation signed before every transaction, ensuring compliance is verified pre-execution, not post-hoc.',
      },
    },
    {
      key: 'aml',
      title: 'AML',
      subtitle: 'Anti-Money Laundering',
      Icon: AMLIcon,
      details: {
        requires: 'Pre-transaction screening, suspicious activity detection, travel rule compliance, and ongoing monitoring of transaction patterns.',
        implements: 'Every transaction is screened by our Oracle before blockchain execution. Anomaly detection with Z-score analysis flags unusual patterns in real-time.',
        component: 'Pre-TX Oracle + Z-score Anomaly Detector — combines address screening, transaction pattern analysis, and risk scoring before any funds move.',
      },
    },
  ]

  const pipelineSteps = [
    { icon: '👤', title: 'User Intent', desc: 'Transaction parameters submitted' },
    { icon: '🔍', title: 'Oracle Check', desc: 'AML/KYC compliance verified' },
    { icon: '✍️', title: 'EIP-712 Sign', desc: 'Cryptographic attestation' },
    { icon: '🔐', title: 'Contract Verify', desc: 'On-chain signature check' },
    { icon: '⚡', title: 'Execute', desc: 'Transaction processed' },
  ]

  const badges = [
    { label: 'MiCA Framework Aligned', tip: 'Compliant with EU Markets in Crypto-Assets regulation' },
    { label: 'AML Pre-TX Screening', tip: 'Every transaction screened before blockchain execution' },
    { label: 'EIP-712 Cryptographic Attestation', tip: 'Typed structured data signing for compliance proof' },
    { label: 'On-Chain Audit Trail', tip: 'Immutable record of all compliance attestations' },
  ]

  return (
    <div>
      {/* Header */}
      <h2 style={{ fontFamily: C.D, fontSize: 24, fontWeight: 800, color: C.text, marginBottom: 4 }}>
        <span style={GRAD}>Compliance</span> Architecture
      </h2>
      <p style={{ fontFamily: C.M, fontSize: 12, color: C.dim, marginBottom: 28 }}>
        Built for the regulatory reality of European crypto markets
      </p>

      {/* ═══ A) The Compliance Trinity ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          The Compliance Trinity
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
          {pillars.map((p) => (
            <div key={p.key}>
              <motion.button
                onClick={() => setExpanded(expanded === p.key ? null : p.key)}
                whileHover={{ y: -2 }}
                whileTap={{ scale: 0.98 }}
                style={{
                  width: '100%', padding: '18px 14px', borderRadius: 14, cursor: 'pointer',
                  background: expanded === p.key ? 'rgba(59,130,246,0.08)' : 'rgba(10,10,10,0.03)',
                  border: `1px solid ${expanded === p.key ? 'rgba(59,130,246,0.25)' : C.border}`,
                  textAlign: 'center', transition: 'all 0.3s ease',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
                }}
              >
                <p.Icon active={expanded === p.key} />
                <div style={{ fontFamily: C.D, fontSize: 14, fontWeight: 700, color: C.text }}>{p.title}</div>
                <div style={{ fontFamily: C.M, fontSize: 9, color: C.dim }}>{p.subtitle}</div>
              </motion.button>
            </div>
          ))}
        </div>

        {/* Expanded detail panel */}
        {pillars.map((p) => (
          <motion.div
            key={`detail-${p.key}`}
            initial={false}
            animate={{
              height: expanded === p.key ? 'auto' : 0,
              opacity: expanded === p.key ? 1 : 0,
            }}
            transition={{ duration: 0.35, ease: EASE }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{
              marginTop: 10, padding: '18px 16px', borderRadius: 14,
              background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
            }}>
              {[
                { label: 'What it requires', text: p.details.requires },
                { label: 'How RSends implements it', text: p.details.implements },
                { label: 'Technical component', text: p.details.component },
              ].map((d) => (
                <div key={d.label} style={{ marginBottom: 12 }}>
                  <div style={{ fontFamily: C.D, fontSize: 10, fontWeight: 700, color: C.blue, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                    {d.label}
                  </div>
                  <div style={{ fontFamily: C.M, fontSize: 11, color: C.sub, lineHeight: 1.6 }}>
                    {d.text}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        ))}
      </div>

      {/* ═══ B) Pre-Transaction Oracle Pipeline ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Pre-Transaction Oracle
        </div>
        <div style={{
          background: C.bg, borderRadius: 16, padding: '24px 16px',
          border: `1px solid ${C.border}`, position: 'relative', overflow: 'hidden',
        }}>
          {/* Animated green particle line */}
          <div style={{
            position: 'absolute', top: 52, left: 0, right: 0, height: 2,
            background: 'rgba(59,130,246,0.05)',
          }}>
            <div style={{
              width: 30, height: 2,
              background: 'linear-gradient(90deg, transparent, #3B82F6, transparent)',
              animation: 'rpShimmer 3s linear infinite',
              backgroundSize: '200% 100%',
            }} />
          </div>

          <div style={{ display: 'flex', gap: 4, position: 'relative' }}>
            {pipelineSteps.map((step, i) => (
              <PipelineNode key={step.title} step={step} index={i} total={pipelineSteps.length} />
            ))}
          </div>
        </div>
      </div>

      {/* ═══ D) Compliance Badges ═══ */}
      <div>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Certifications & Standards
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {badges.map((b, i) => (
            <Tooltip key={b.label} text={b.tip}>
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08, duration: 0.3 }}
                style={{
                  padding: '7px 12px', borderRadius: 8,
                  background: 'rgba(10,10,10,0.03)',
                  border: `1px solid ${C.border}`,
                  fontFamily: C.M, fontSize: 9, color: C.sub,
                  cursor: 'default',
                  backgroundImage: 'linear-gradient(90deg, transparent, rgba(10,10,10,0.04), transparent)',
                  backgroundSize: '200% 100%',
                  animation: 'rpShimmer 4s linear infinite',
                  animationDelay: `${i * 0.5}s`,
                }}
              >
                {b.label}
              </motion.div>
            </Tooltip>
          ))}
        </div>
      </div>
    </div>
  )
}
