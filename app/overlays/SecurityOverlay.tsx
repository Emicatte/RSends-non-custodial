'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { C, EASE } from '@/app/designTokens'

const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

export default function SecurityOverlay() {
  const [expandedLayer, setExpandedLayer] = useState<number | null>(null)
  const [threatDone, setThreatDone] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => setThreatDone(true), 3200)
    return () => clearTimeout(t)
  }, [])

  const layers = [
    { title: 'Blockchain Foundation', desc: 'Base L2 with Ethereum settlement finality', tag: 'L1', color: C.blue, detail: 'Transactions execute on Base L2 for minimal gas costs (~$0.01), with full security inherited from Ethereum L1. Settlement finality via Optimism Bedrock.' },
    { title: 'Infrastructure', desc: 'HMAC-SHA256, rate limiting, SSL termination', tag: 'L2', color: C.amber, detail: 'All API requests are HMAC-SHA256 signed. Rate limiting at both API and transaction level. Nginx SSL termination at the edge. Monitored around the clock.' },
    { title: 'Smart Contract', desc: 'ReentrancyGuard, OpenZeppelin, FeeRouterV4', tag: 'L3', color: C.purple, detail: 'FeeRouterV4.sol inherits from OpenZeppelin\'s ReentrancyGuard and Ownable. All state-changing functions are protected. Contract verified on Basescan.' },
    { title: 'Compliance Engine', desc: 'EIP-712 Oracle, AML/MiCA screening', tag: 'L4', color: C.green, detail: 'Every transaction requires a valid EIP-712 typed signature from the compliance Oracle. Screens against AML databases and ensures MiCA compliance. Nothing moves without it.' },
    { title: 'Monitoring', desc: 'Sentry, Prometheus, Z-score anomaly detection', tag: 'L5', color: '#FF4C6A', detail: 'Real-time error tracking, metrics collection, and custom Z-score anomaly detection. Unusual transaction patterns get flagged instantly.' },
  ]

  const features = [
    { title: 'Oracle-Gated TX', desc: 'Every transaction needs cryptographic approval from the compliance Oracle before execution. No exceptions.' },
    { title: 'On-Chain Verification', desc: 'The smart contract verifies Oracle signatures independently. Verify, don\'t trust.' },
    { title: 'Anomaly Detection', desc: 'Z-score statistical analysis flags transactions deviating from normal patterns in real-time.' },
    { title: 'Rate Limiting', desc: 'API and transaction-level rate limiting. Abuse gets blocked before it reaches the contract.' },
    { title: 'HMAC Integrity', desc: 'All backend communications are HMAC-SHA256 signed. Tampered requests get rejected.' },
    { title: 'Infrastructure Security', desc: 'SSL termination, Docker isolation, automated backups, least-privilege access. Standard ops.' },
  ]

  return (
    <div>
      {/* ═══ A) Threat Landscape Intro ═══ */}
      <motion.div
        animate={{ opacity: threatDone ? 0 : 1, y: threatDone ? -20 : 0, height: threatDone ? 0 : 'auto' }}
        transition={{ duration: 0.6, ease: EASE }}
        style={{ overflow: 'hidden', marginBottom: threatDone ? 0 : 24 }}
      >
        <div style={{ textAlign: 'center', padding: '24px 0' }}>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6, ease: EASE }}
            style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6, maxWidth: 480, margin: '0 auto', marginBottom: 8 }}
          >
            Most DeFi protocols bolt on security after the fact. We architected RSends around compliance and safety from the first commit.
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.2, duration: 0.6, ease: EASE }}
            style={{ fontFamily: C.M, fontSize: 11, color: C.dim }}
          >
            Five layers. No shortcuts.
          </motion.div>
        </div>
      </motion.div>

      <h2 style={{ fontFamily: C.D, fontSize: 22, fontWeight: 600, color: C.text, marginBottom: 4 }}>
        <span style={GRAD}>Security</span> Architecture
      </h2>
      <p style={{ fontFamily: C.S, fontSize: 13, color: C.dim, marginBottom: 28 }}>
        How we keep your funds and data safe — layer by layer.
      </p>

      {/* ═══ B) Security Layer Stack ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Security Layer Stack
        </div>
        <div style={{ display: 'flex', flexDirection: 'column-reverse', gap: 6 }}>
          {layers.map((layer, i) => (
            <motion.div
              key={layer.title}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.12, duration: 0.4, ease: EASE }}
            >
              <motion.button
                onClick={() => setExpandedLayer(expandedLayer === i ? null : i)}
                whileHover={{ y: -1 }}
                style={{
                  width: '100%', padding: '14px 16px', borderRadius: 14, cursor: 'pointer',
                  background: expandedLayer === i ? `${layer.color}10` : 'rgba(10,10,10,0.02)',
                  border: `1px solid ${expandedLayer === i ? `${layer.color}40` : C.border}`,
                  display: 'flex', alignItems: 'center', gap: 12,
                  transition: 'all 0.25s ease', textAlign: 'left',
                  boxShadow: expandedLayer === i ? `0 0 20px ${layer.color}15, inset 0 0 20px ${layer.color}05` : 'none',
                }}
              >
                <div style={{
                  width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                  background: `${layer.color}12`, border: `1px solid ${layer.color}25`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: C.M, fontSize: 11, fontWeight: 700, color: layer.color,
                }}>
                  {layer.tag}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 600, color: C.text }}>{layer.title}</div>
                  <div style={{ fontFamily: C.S, fontSize: 11, color: C.dim }}>{layer.desc}</div>
                </div>
              </motion.button>
              <motion.div
                initial={false}
                animate={{ height: expandedLayer === i ? 'auto' : 0, opacity: expandedLayer === i ? 1 : 0 }}
                transition={{ duration: 0.3, ease: EASE }}
                style={{ overflow: 'hidden' }}
              >
                <div style={{
                  margin: '6px 0 0 48px', padding: '12px 14px', borderRadius: 10,
                  background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
                  fontFamily: C.M, fontSize: 11, color: C.sub, lineHeight: 1.6,
                }}>
                  {layer.detail}
                </div>
              </motion.div>
            </motion.div>
          ))}
        </div>

        {/* Animated particle rising through layers */}
        <div style={{ position: 'relative', height: 4, margin: '12px 0', overflow: 'hidden', borderRadius: 2, background: 'rgba(10,10,10,0.03)' }}>
          <div style={{
            width: 40, height: '100%',
            background: `linear-gradient(90deg, transparent, ${C.green}, transparent)`,
            animation: 'rpShimmer 2.5s linear infinite',
            backgroundSize: '200% 100%',
          }} />
        </div>
      </div>

      {/* ═══ C) Security Features Grid ═══ */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 14 }}>
          Security Features
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {features.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08, duration: 0.35, ease: EASE }}
              style={{
                padding: '16px', borderRadius: 14,
                background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
                cursor: 'default',
                gridColumn: i === 0 ? '1 / -1' : undefined,
              }}
            >
              <div style={{ fontFamily: C.D, fontSize: 12, fontWeight: 600, color: C.text, marginBottom: 4 }}>{f.title}</div>
              <div style={{ fontFamily: C.S, fontSize: 11, color: C.dim, lineHeight: 1.5 }}>{f.desc}</div>
            </motion.div>
          ))}
        </div>
        {/* Technical note */}
        <div style={{
          marginTop: 12, padding: '10px 14px', borderRadius: 8,
          borderLeft: `2px solid ${C.blue}30`,
          background: 'rgba(10,10,10,0.015)',
        }}>
          <div style={{ fontFamily: C.M, fontSize: 10, color: C.dim, lineHeight: 1.6 }}>
            // FeeRouterV4.sol — all state-changing functions inherit ReentrancyGuard.
            <br />// Oracle signatures verified on-chain via ecrecover. No off-chain trust.
          </div>
        </div>
      </div>

      {/* ═══ D) System Status ═══ */}
      <div style={{
        padding: '14px 18px', borderRadius: 14,
        background: 'rgba(0,214,143,0.04)', border: `1px solid ${C.green}15`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ position: 'relative', width: 8, height: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: C.green }} />
            <div style={{ position: 'absolute', inset: -4, borderRadius: '50%', border: `2px solid ${C.green}`, animation: 'rsPulse 2s ease infinite' }} />
          </div>
          <span style={{ fontFamily: C.D, fontSize: 12, fontWeight: 700, color: C.green }}>All Systems Operational</span>
        </div>
        <a
          href="https://basescan.org/address/0x81d78BDD917D5A43a9E424B905407495b8f2c0f4"
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontFamily: C.M, fontSize: 10, color: C.sub, textDecoration: 'none' }}
        >
          Contract verified on Basescan →
        </a>
      </div>
    </div>
  )
}
