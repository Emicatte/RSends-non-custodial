'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { C, EASE } from '@/app/designTokens'

const GRAD: React.CSSProperties = {
  color: '#C8512C',
}

export default function HowOverlay() {
  const [expandedStep, setExpandedStep] = useState<number | null>(null)

  const steps = [
    {
      n: '01', title: 'Connect', desc: 'Plug in your wallet. MetaMask, Coinbase, Ledger — whatever you use. No sign-up, no API keys.',
      detail: 'RSends uses wagmi v2 with RainbowKit. Once connected, the app detects your chain (Base, Ethereum, Arbitrum) and configures the contract interface automatically. Zero registration friction.',
    },
    {
      n: '02', title: 'Verify', desc: 'The compliance Oracle checks your transaction and signs off with an EIP-712 attestation. If it doesn\'t pass, nothing moves.',
      detail: 'Before any funds move, the Oracle performs AML screening and MiCA compliance verification. It returns a typed EIP-712 signature that the smart contract independently verifies on-chain. No trust assumptions.',
    },
    {
      n: '03', title: 'Execute', desc: 'FeeRouterV4 verifies the signature, splits the payment (99.5% recipient, 0.5% protocol), settles in ~2 seconds.',
      detail: 'The contract checks the Oracle signature on-chain, executes split routing, and emits events for the audit log. Final settlement on Base L2, gas under $0.05.',
    },
  ]

  const advancedFlows = [
    { title: 'Swap & Forward', desc: 'Pay in ETH, recipient gets USDC. Automatic DEX routing with compliance.' },
    { title: 'Auto-Split', desc: 'Programmable treasury routing — split payments across multiple wallets.' },
    { title: 'Sweeper', desc: 'Auto-forward incoming funds to configured destinations based on rules.' },
  ]

  return (
    <div>
      <h2 style={{ fontFamily: C.D, fontSize: 22, fontWeight: 600, color: C.text, marginBottom: 4 }}>
        How It <span style={GRAD}>Works</span>
      </h2>
      <p style={{ fontFamily: C.S, fontSize: 13, color: C.dim, marginBottom: 28 }}>
        Three steps. Connect, verify, settle. That's it.
      </p>

      {/* ═══ A) 3-Step Journey ═══ */}
      <div style={{ marginBottom: 32 }}>
        {steps.map((s, i) => (
          <motion.div
            key={s.n}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: i * 0.15, duration: 0.5, ease: EASE }}
            style={{ position: 'relative', paddingLeft: 32, marginBottom: i < steps.length - 1 ? 0 : 0 }}
          >
            {/* Connecting line */}
            {i < steps.length - 1 && (
              <motion.div
                initial={{ scaleY: 0 }}
                whileInView={{ scaleY: 1 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.15 + 0.3, duration: 0.4 }}
                style={{
                  position: 'absolute', left: 14, top: 46, width: 2, height: 'calc(100% - 20px)',
                  background: `linear-gradient(180deg, ${C.blue}40, ${C.blue}10)`,
                  transformOrigin: 'top',
                }}
              />
            )}

            <div style={{ display: 'flex', gap: 14, padding: '16px 0' }}>
              {/* Number badge */}
              <div style={{
                position: 'absolute', left: 0, top: 18,
                width: 30, height: 30, borderRadius: 10, flexShrink: 0,
                background: 'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(200,81,44,0.15))',
                border: `1px solid ${C.blue}30`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: C.M, fontSize: 10, fontWeight: 700, color: C.blue,
              }}>
                {s.n}
              </div>

              {/* Content */}
              <div style={{ flex: 1, marginLeft: 12 }}>
                <div style={{ marginBottom: 6 }}>
                  <span style={{ fontFamily: C.D, fontSize: 16, fontWeight: 600, color: C.text }}>{s.title}</span>
                </div>
                <p style={{ fontFamily: C.S, fontSize: 12, color: C.sub, lineHeight: 1.6, marginBottom: 8 }}>{s.desc}</p>

                {/* Technical details toggle */}
                <button
                  onClick={() => setExpandedStep(expandedStep === i ? null : i)}
                  style={{
                    padding: '4px 10px', borderRadius: 6, border: `1px solid ${C.border}`,
                    background: expandedStep === i ? 'rgba(59,130,246,0.08)' : 'transparent',
                    color: expandedStep === i ? C.blue : C.dim,
                    fontFamily: C.M, fontSize: 9, cursor: 'pointer', transition: 'all 0.2s',
                  }}
                >
                  {expandedStep === i ? '▾ Hide details' : '▸ Technical details'}
                </button>
                <motion.div
                  initial={false}
                  animate={{ height: expandedStep === i ? 'auto' : 0, opacity: expandedStep === i ? 1 : 0 }}
                  transition={{ duration: 0.3, ease: EASE }}
                  style={{ overflow: 'hidden' }}
                >
                  <div style={{
                    marginTop: 8, padding: '12px 14px', borderRadius: 10,
                    background: 'rgba(10,10,10,0.02)', border: `1px solid ${C.border}`,
                    fontFamily: C.M, fontSize: 10, color: C.dim, lineHeight: 1.6,
                  }}>
                    {s.detail}
                  </div>
                </motion.div>
              </div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* ═══ B) Advanced Flows ═══ */}
      <div>
        <div style={{ fontFamily: C.M, fontSize: 9, fontWeight: 700, color: C.dim, textTransform: 'uppercase' as const, letterSpacing: '0.1em', marginBottom: 14 }}>
          Advanced Flows
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          {advancedFlows.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, y: 10 }}
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
              <div style={{ fontFamily: C.D, fontSize: 13, fontWeight: 600, color: C.text, marginBottom: 4 }}>{f.title}</div>
              <div style={{ fontFamily: C.S, fontSize: 11, color: C.dim, lineHeight: 1.5 }}>{f.desc}</div>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  )
}
