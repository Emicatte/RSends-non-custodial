'use client'

import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { C } from '@/app/designTokens'

const fadeUp = {
  initial: { opacity: 0, y: 30 } as const,
  whileInView: { opacity: 1, y: 0 } as const,
  viewport: { once: true, margin: '-60px' },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] },
}

const cardStyle: React.CSSProperties = {
  background: 'rgba(10,10,10,0.5)',
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: 28,
  backdropFilter: 'blur(12px)',
  transition: 'border-color 0.2s',
}

const dividerStyle: React.CSSProperties = {
  width: '100%', height: 1,
  background: 'linear-gradient(90deg, transparent, rgba(10,10,10,0.06) 20%, rgba(10,10,10,0.06) 80%, transparent)',
  margin: '80px 0',
}

function HoverCard({ children, style, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  const [hov, setHov] = useState(false)
  return (
    <div
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}
      style={{
        ...cardStyle, ...style,
        borderColor: hov ? 'rgba(10,10,10,0.12)' : C.border,
      }}
      {...rest}
    >{children}</div>
  )
}

function SLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: C.M, fontSize: 11, fontWeight: 600, color: C.purple,
      letterSpacing: '0.12em', textTransform: 'uppercase', marginBottom: 14,
    }}>{children}</div>
  )
}

function STitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontFamily: C.D, fontSize: 'clamp(26px, 4vw, 36px)', fontWeight: 700,
      color: C.text, lineHeight: 1.2, margin: '0 0 40px',
    }}>{children}</h2>
  )
}

function IconGrid({ color = C.purple, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect x="5" y="5" width="9" height="9" rx="2" stroke={color} strokeWidth="2"/>
      <rect x="18" y="5" width="9" height="9" rx="2" stroke={color} strokeWidth="2"/>
      <rect x="5" y="18" width="9" height="9" rx="2" stroke={color} strokeWidth="2"/>
      <rect x="18" y="18" width="9" height="9" rx="2" stroke={color} strokeWidth="2"/>
    </svg>
  )
}

function IconSplit({ color = C.purple, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 6V14M16 14L8 22M16 14L24 22" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconRoute({ color = C.purple, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M6 8H20C23.3 8 26 10.7 26 14C26 17.3 23.3 20 20 20H12C8.7 20 6 22.7 6 26" stroke={color} strokeWidth="2" strokeLinecap="round"/>
      <path d="M22 24L26 26L22 28" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconDash({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect x="4" y="6" width="24" height="20" rx="3" stroke={color} strokeWidth="2"/>
      <path d="M4 12H28M10 6V12" stroke={color} strokeWidth="2"/>
      <circle cx="20" cy="20" r="3" stroke={color} strokeWidth="1.5"/>
    </svg>
  )
}

function IconBell({ color = C.amber, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 4C12 4 9 7 9 11V18L6 22H26L23 18V11C23 7 20 4 16 4Z" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
      <path d="M13 22V23C13 24.7 14.3 26 16 26C17.7 26 19 24.7 19 23V22" stroke={color} strokeWidth="2"/>
    </svg>
  )
}

function IconShield({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 4L6 9V16C6 22 10 27 16 28C22 27 26 22 26 16V9L16 4Z" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
      <path d="M12 16L15 19L21 13" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

function IconGlobe({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="10" stroke={color} strokeWidth="2"/>
      <path d="M6 16H26M16 6C19 10 19 22 16 26M16 6C13 10 13 22 16 26" stroke={color} strokeWidth="1.5"/>
    </svg>
  )
}

function IconMoney({ color = C.green, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="10" stroke={color} strokeWidth="2"/>
      <path d="M16 10V22M12 14C12 12.3 13.8 11 16 11C18.2 11 20 12.3 20 14C20 15.7 18.2 17 16 17C13.8 17 12 18.3 12 20C12 21.7 13.8 23 16 23" stroke={color} strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  )
}

function IconHandshake({ color = C.blue, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M4 16L10 10L16 16L22 10L28 16" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M10 16V24M22 16V24" stroke={color} strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
}

function IconBank({ color = C.purple, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M16 4L4 12H28L16 4Z" stroke={color} strokeWidth="2" strokeLinejoin="round"/>
      <path d="M8 12V24M14 12V24M20 12V24M26 12V24" stroke={color} strokeWidth="2"/>
      <path d="M4 24H28" stroke={color} strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
}

function IconChart({ color = C.amber, size = 32 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <path d="M6 26V14L12 18L18 8L26 16" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M6 26H26" stroke={color} strokeWidth="2" strokeLinecap="round"/>
    </svg>
  )
}

function useIsMobile(bp = 768) {
  const [m, setM] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${bp}px)`)
    setM(mq.matches)
    const h = (e: MediaQueryListEvent) => setM(e.matches)
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [bp])
  return m
}

export default function CommandCenterOverlay({ onClose, onGoToCommand }: { onClose: () => void; onGoToCommand: () => void }) {
  const howItWorksRef = useRef<HTMLDivElement>(null)
  const isMobile = useIsMobile()

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => {
      document.body.style.overflow = prev
      document.removeEventListener('keydown', h)
    }
  }, [onClose])

  const steps = [
    { num: '01', title: 'Funds Arrive', desc: 'Deposits hit your RSends address. Any supported chain — EVM, Tron, or Solana. No code required.' },
    { num: '02', title: 'Rules Applied', desc: 'Rules you configured are applied automatically. AML screening runs in real-time.' },
    { num: '03', title: 'Splits Execute', desc: 'Funds split and route across wallets and chains. Deterministic, atomic execution.' },
    { num: '04', title: 'Recipients Paid', desc: 'Each recipient gets their share. You see everything live in the dashboard.' },
  ]

  const features = [
    { icon: <IconSplit color={C.purple} />, title: 'Split Contracts', desc: 'Define how funds are divided. Set it once — execution is deterministic and automatic.' },
    { icon: <IconRoute color={C.purple} />, title: 'Route Management', desc: 'Forward funds across wallets and chains. Create complex routing rules with no code.' },
    { icon: <IconDash color={C.green} />, title: 'Real-Time Dashboard', desc: 'See every transaction as it happens. Status, amounts, chains, recipients — all live.' },
    { icon: <IconBell color={C.amber} />, title: 'Alerts', desc: 'Telegram and webhook notifications for critical events. Never miss a payment.' },
    { icon: <IconShield color={C.green} />, title: 'Compliance', desc: 'AML screening, audit logs. Built-in compliance for regulated flows.' },
    { icon: <IconGlobe color={C.blue} />, title: 'Multi-Chain', desc: 'Base, Ethereum, Arbitrum, Optimism, Tron, and more. Manage all chains from one place.' },
  ]

  const useCases = [
    { icon: <IconMoney color={C.green} />, title: 'Payroll Distribution', desc: 'Split salary payments across multiple wallets. One transaction, multiple recipients.' },
    { icon: <IconHandshake color={C.blue} />, title: 'Affiliate Payouts', desc: 'Automatic commission splits. Transparent, auditable, and on-chain.' },
    { icon: <IconBank color={C.purple} />, title: 'Treasury Automation', desc: 'Sweep, forward, and rebalance without manual intervention or scripts.' },
    { icon: <IconChart color={C.amber} />, title: 'OTC Settlement', desc: 'Multi-party settlement with compliance checks built in from day one.' },
  ]

  const comparisons = [
    { title: 'Wallets', desc: "Can send. Can't split. Can't automate. Can't screen. Manual, one-at-a-time.", highlight: false },
    { title: 'Scripts', desc: 'Break at scale. No retry. No audit trail. No monitoring. Fragile.', highlight: false },
    { title: 'RSends', desc: 'Execution engine with splits, AML, matching, webhooks, and ledger. Always on. Zero maintenance.', highlight: true },
  ]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3 }}
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: C.bg, overflowY: 'auto', overflowX: 'hidden',
      }}
    >
      {/* Sticky nav bar */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: isMobile ? '14px 16px' : '16px 32px',
        background: 'rgba(250,250,250,0.8)',
        backdropFilter: 'blur(12px)',
        borderBottom: `1px solid ${C.border}`,
      }}>
        <button
          onClick={onClose}
          onMouseEnter={e => (e.currentTarget.style.color = C.text)}
          onMouseLeave={e => (e.currentTarget.style.color = C.sub)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'none', border: 'none', cursor: 'pointer',
            color: C.sub, fontFamily: C.D, fontSize: 14, transition: 'color 0.15s',
          }}
        >← Back to RSends</button>
        <button onClick={onClose} style={{
          background: 'rgba(10,10,10,0.08)', border: 'none',
          borderRadius: '50%', width: 36, height: 36, cursor: 'pointer',
          color: C.sub, fontSize: 18, display: 'grid', placeItems: 'center',
          transition: 'background 0.15s',
        }}>×</button>
      </div>

      {/* Content */}
      <div style={{
        maxWidth: 1100, margin: '0 auto',
        padding: isMobile ? '0 20px 80px' : '0 32px 100px',
      }}>

        {/* Hero */}
        <motion.div {...fadeUp} style={{
          textAlign: 'center',
          padding: isMobile ? '60px 0 0' : '80px 0 0',
        }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
            <IconGrid color={C.purple} size={44} />
            <h1 style={{
              fontFamily: C.D, fontSize: 'clamp(32px, 5vw, 44px)', fontWeight: 700,
              color: C.text, margin: 0,
            }}>Command Center</h1>
          </div>
          <p style={{
            fontFamily: C.D, fontSize: 'clamp(20px, 3vw, 28px)', fontWeight: 600,
            margin: '0 0 12px',
            color: '#C8512C',
          }}>Manage everything from one dashboard</p>
          <p style={{
            fontFamily: C.S, fontSize: 16, color: C.sub, margin: '0 0 36px',
            maxWidth: 560, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6,
          }}>
            No-code transaction management. Split payments, route funds, track everything in real-time.
            Built for businesses that move money at scale.
          </p>
          <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button style={{
              fontFamily: C.D, fontSize: 15, fontWeight: 600, cursor: 'pointer',
              padding: '13px 30px', borderRadius: 12, border: 'none',
              background: C.purple, color: '#fff', transition: 'all 0.2s',
              boxShadow: '0 4px 24px rgba(200,81,44,0.25)',
            }} onClick={onGoToCommand}>Launch Command Center →</button>
            <button onClick={() => howItWorksRef.current?.scrollIntoView({ behavior: 'smooth' })} style={{
              fontFamily: C.D, fontSize: 15, fontWeight: 600, cursor: 'pointer',
              padding: '13px 30px', borderRadius: 12,
              border: `1.5px solid ${C.border}`, background: 'transparent',
              color: C.sub, transition: 'all 0.2s',
            }}>Watch Demo</button>
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* How it works */}
        <motion.div {...fadeUp} ref={howItWorksRef}>
          <SLabel>HOW IT WORKS</SLabel>
          <STitle>Set your rules. We execute.</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
            gap: isMobile ? 24 : 40,
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
              {steps.map(s => (
                <div key={s.num} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                  <div style={{
                    fontFamily: C.M, fontSize: 32, fontWeight: 700,
                    color: C.purple, opacity: 0.25, lineHeight: 1, flexShrink: 0, width: 44,
                    textAlign: 'right',
                  }}>{s.num}</div>
                  <div>
                    <div style={{ fontFamily: C.D, fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 6 }}>{s.title}</div>
                    <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{s.desc}</div>
                  </div>
                </div>
              ))}
            </div>
            {!isMobile && (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <div style={{
                  background: 'rgba(255,255,255,0.6)',
                  border: `1px solid ${C.border}`,
                  borderRadius: 16, padding: 32, width: '100%',
                  textAlign: 'center',
                }}>
                  <IconGrid color={C.purple} size={56} />
                  <div style={{
                    fontFamily: C.D, fontSize: 18, fontWeight: 600,
                    color: C.text, marginTop: 20, marginBottom: 8,
                  }}>Dashboard Preview</div>
                  <div style={{
                    fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.5,
                  }}>
                    Live transactions, split rules, routing config, compliance reports — all in one view.
                  </div>
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: 12, marginTop: 24,
                  }}>
                    {['Transactions', 'Split Rules', 'Alerts'].map(label => (
                      <div key={label} style={{
                        padding: '12px 8px', borderRadius: 10,
                        background: 'rgba(200,81,44,0.06)',
                        border: `1px solid rgba(200,81,44,0.15)`,
                        fontFamily: C.M, fontSize: 11, color: C.purple,
                      }}>{label}</div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Features */}
        <motion.div {...fadeUp}>
          <SLabel>FEATURES</SLabel>
          <STitle>Everything you need to manage money</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)',
            gap: 20,
          }}>
            {features.map(f => (
              <HoverCard key={f.title}>
                <div style={{ marginBottom: 14 }}>{f.icon}</div>
                <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 600, color: C.text, marginBottom: 8 }}>{f.title}</div>
                <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{f.desc}</div>
              </HoverCard>
            ))}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Use Cases */}
        <motion.div {...fadeUp}>
          <SLabel>USE CASES</SLabel>
          <STitle>Built for real flows</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, 1fr)',
            gap: 20,
          }}>
            {useCases.map(u => (
              <HoverCard key={u.title} style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                <div style={{ flexShrink: 0, marginTop: 2 }}>{u.icon}</div>
                <div>
                  <div style={{ fontFamily: C.D, fontSize: 16, fontWeight: 600, color: C.text, marginBottom: 8 }}>{u.title}</div>
                  <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{u.desc}</div>
                </div>
              </HoverCard>
            ))}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Why RSends */}
        <motion.div {...fadeUp}>
          <SLabel>WHY RSENDS</SLabel>
          <STitle>Why not just use a wallet or a script?</STitle>
          <div style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : 'repeat(3, 1fr)',
            gap: 20,
          }}>
            {comparisons.map(c => (
              <div key={c.title} style={{
                padding: 28, borderRadius: 16,
                border: c.highlight ? `1.5px solid ${C.purple}` : `1px solid ${C.border}`,
                background: c.highlight ? 'rgba(200,81,44,0.06)' : 'rgba(10,10,10,0.3)',
                boxShadow: c.highlight ? '0 0 40px rgba(200,81,44,0.08)' : 'none',
                opacity: c.highlight ? 1 : 0.6,
              }}>
                <div style={{
                  fontFamily: C.D, fontSize: 18, fontWeight: 700, marginBottom: 12,
                  color: c.highlight ? C.purple : C.text,
                }}>{c.title}</div>
                <div style={{ fontFamily: C.S, fontSize: 14, color: C.sub, lineHeight: 1.6 }}>{c.desc}</div>
              </div>
            ))}
          </div>
        </motion.div>

        <div style={dividerStyle} />

        {/* Final CTA */}
        <motion.div {...fadeUp} style={{ textAlign: 'center', padding: '20px 0' }}>
          <h2 style={{
            fontFamily: C.D, fontSize: 'clamp(26px, 4vw, 36px)', fontWeight: 700,
            margin: '0 0 14px',
            color: '#C8512C',
          }}>Take control of your payments</h2>
          <p style={{
            fontFamily: C.S, fontSize: 16, color: C.sub, margin: '0 0 32px', lineHeight: 1.6,
          }}>No code. No scripts. One dashboard for everything.</p>
          <button style={{
            fontFamily: C.D, fontSize: 16, fontWeight: 600, cursor: 'pointer',
            padding: '14px 36px', borderRadius: 12, border: 'none',
            background: C.purple, color: '#fff', transition: 'all 0.2s',
            boxShadow: '0 4px 24px rgba(200,81,44,0.25)',
          }} onClick={onGoToCommand}>Launch Command Center →</button>
        </motion.div>

      </div>
    </motion.div>
  )
}
