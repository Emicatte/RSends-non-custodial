'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useAccount, useChainId } from 'wagmi'
import dynamic from 'next/dynamic'
import { motion } from 'framer-motion'
import { C } from '@/app/designTokens'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'

import TransferForm from '@/app/TransferForm'
import SwapModule from '@/app/SwapModule'

// CommandCenter lazy — usa Recharts e WebSocket pesanti
const CommandCenter = dynamic(() => import('@/app/command-center'), {
  ssr: false,
  loading: () => (
    <div style={{ padding: 40, textAlign: 'center', color: C.sub, fontFamily: C.D }}>
      Loading Command Center…
    </div>
  ),
})

type AppTab = 'send' | 'swap' | 'command'

const panelBase: React.CSSProperties = {
  transition: 'opacity 380ms cubic-bezier(0.16,1,0.3,1)',
  willChange: 'opacity',
}
const panelActive: React.CSSProperties = {
  ...panelBase,
  position: 'relative',
  opacity: 1,
  pointerEvents: 'auto',
  zIndex: 1,
}
const panelHidden: React.CSSProperties = {
  ...panelBase,
  position: 'absolute',
  top: 0,
  left: 0,
  right: 0,
  opacity: 0,
  pointerEvents: 'none',
  zIndex: 0,
}

export default function AppPage() {
  const [tab, setTab] = useState<AppTab>('send')
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  return (
    <>
      {/* Top bar accent — coerente con landing */}
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, height: 3,
        background: C.text, zIndex: 1001,
      }}>
        <div style={{
          position: 'absolute', top: 0, left: 0, width: 96, height: 3,
          background: C.purple,
        }} />
      </div>

      {/* Navbar /app */}
      <nav style={{
        position: 'fixed', top: 3, left: 0, right: 0, zIndex: 1000,
        height: isMobile ? 52 : 60,
        background: 'rgba(250,250,250,0.85)',
        borderBottom: `1px solid ${C.border}`,
        backdropFilter: 'blur(16px) saturate(180%)',
        WebkitBackdropFilter: 'blur(16px) saturate(180%)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: isMobile ? '0 12px' : '0 24px',
      }}>
        {/* Left: logo */}
        <Link href="/" style={{
          display: 'flex', alignItems: 'center', gap: 8,
          textDecoration: 'none',
        }}>
          <img src="/favicon.svg" alt="RSends" width={28} height={28} style={{ borderRadius: 7 }} />
          {!isMobile && (
            <span style={{
              fontFamily: C.D, fontSize: 16, fontWeight: 800,
              color: C.text, letterSpacing: '-0.03em',
            }}>
              RSends
            </span>
          )}
        </Link>

        {/* Center: tabs */}
        <div style={{
          display: 'flex', gap: 4, alignItems: 'center',
          position: isMobile ? 'static' : 'absolute',
          left: '50%',
          transform: isMobile ? 'none' : 'translateX(-50%)',
        }}>
          {([
            { key: 'send' as AppTab, label: 'Send' },
            { key: 'swap' as AppTab, label: 'Swap' },
            { key: 'command' as AppTab, label: isMobile ? 'CMD' : 'Command Center' },
          ]).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                position: 'relative',
                padding: isMobile ? '6px 10px' : '8px 16px',
                borderRadius: 8,
                border: 'none',
                background: 'transparent',
                color: tab === t.key ? C.text : C.sub,
                fontFamily: C.D,
                fontSize: isMobile ? 12 : 13,
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'color 0.2s',
              }}
            >
              {t.label}
              {tab === t.key && (
                <motion.div
                  layoutId="app-tab-indicator"
                  style={{
                    position: 'absolute',
                    bottom: -1,
                    left: 8, right: 8,
                    height: 2,
                    background: C.purple,
                    borderRadius: 1,
                  }}
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
            </button>
          ))}
        </div>

        {/* Right: wallet status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isConnected && address ? (
            <div style={{
              padding: '6px 12px',
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 20,
              fontFamily: C.M,
              fontSize: 11,
              color: C.text,
            }}>
              {address.slice(0, 6)}…{address.slice(-4)}
            </div>
          ) : (
            <div style={{
              padding: '6px 12px',
              background: C.text,
              color: C.bg,
              borderRadius: 3,
              fontFamily: C.D,
              fontSize: 12,
              fontWeight: 500,
            }}>
              Connect wallet
            </div>
          )}
        </div>
      </nav>

      {/* Main container */}
      <main style={{
        paddingTop: isMobile ? 75 : 90,
        paddingBottom: 80,
        minHeight: '100vh',
        background: C.bg,
      }}>
        <div style={{
          maxWidth: tab === 'command' ? 1200 : 520,
          margin: '0 auto',
          padding: '0 20px',
          position: 'relative',
        }}>
          {/* Send */}
          <div style={tab === 'send' ? panelActive : panelHidden}>
            <ErrorBoundary module="TransferForm">
              <TransferForm noCard />
            </ErrorBoundary>
          </div>

          {/* Swap */}
          <div style={tab === 'swap' ? panelActive : panelHidden}>
            <ErrorBoundary module="SwapModule">
              <SwapModule noCard onSwapComplete={() => {}} />
            </ErrorBoundary>
          </div>

          {/* Command Center */}
          <div style={tab === 'command' ? panelActive : panelHidden}>
            <ErrorBoundary module="CommandCenter">
              <CommandCenter
                ownerAddress={address}
                chainId={chainId}
                isVisible={tab === 'command'}
              />
            </ErrorBoundary>
          </div>
        </div>
      </main>
    </>
  )
}
