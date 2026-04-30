'use client'

import { useState, useEffect, useCallback, useRef, useLayoutEffect } from 'react'
import { Link } from '@/i18n/navigation'
import { useTranslations } from 'next-intl'
import { useAccount, useChainId } from 'wagmi'
import dynamic from 'next/dynamic'
import { C } from '@/app/designTokens'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'

import TransferForm from '@/app/TransferForm'
import SwapModule from '@/app/SwapModule'
import { ChainFamilySwitch } from '@/components/shared/ChainFamilySwitch'
import NetworkSelector from '@/app/NetworkSelector'
import AccountHeader, { type NonEvmWalletProps } from '@/app/AccountHeader'
import { TransactionPersistence } from '@/components/TransactionPersistence'
import { ContactsPersistence } from '@/components/ContactsPersistence'
import { PostLoginMerge } from '@/components/auth/PostLoginMerge'
import { useUniversalWallet } from '@/hooks/useUniversalWallet'
import { useWallet as useSolanaWallet } from '@solana/wallet-adapter-react'
import { useTron } from '@/app/providers-tron'
import { useTabTransition } from '@/hooks/useTabTransition'
import '@/app/tab-transition.css'

// CommandCenter lazy — usa Recharts e WebSocket pesanti
const CommandCenter = dynamic(() => import('@/app/command-center'), {
  ssr: false,
  loading: () => (
    <div style={{ padding: 40, textAlign: 'center', color: C.sub, fontFamily: C.D }}>
      …
    </div>
  ),
})

type AppTab = 'send' | 'swap' | 'command'

const TAB_ORDER = ['send', 'swap', 'command'] as const satisfies readonly AppTab[]

export default function AppPage() {
  const { tab, phase, direction, transitionTo } = useTabTransition<AppTab>('send', TAB_ORDER)
  const tabsContainerRef = useRef<HTMLDivElement>(null)
  const indicatorRef = useRef<HTMLDivElement>(null)

  const { address } = useAccount()
  const chainId = useChainId()
  const [isMobile, setIsMobile] = useState(false)
  const t = useTranslations('dapp')

  // Universal wallet (EVM / Solana / Tron) — source of truth for activeFamily
  const wallet = useUniversalWallet()
  const activeFamily = wallet.activeFamily

  const { disconnect: solanaDisconnect } = useSolanaWallet()
  const tron = useTron()

  // Build nonEvmWallet prop for AccountHeader when active family is Tron/Solana
  const nonEvmWallet: NonEvmWalletProps | undefined = (() => {
    if (activeFamily === 'evm') return undefined
    const conn = activeFamily === 'tron' ? wallet.connections.tron : wallet.connections.solana
    if (!conn?.address) return undefined
    return {
      family: activeFamily as 'tron' | 'solana',
      address: conn.address,
      disconnect: activeFamily === 'tron' ? tron.disconnect : solanaDisconnect,
    }
  })()

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [])

  const handleTabClick = useCallback((next: AppTab) => {
    transitionTo(next)
  }, [transitionTo])

  useLayoutEffect(() => {
    const measure = () => {
      if (!tabsContainerRef.current || !indicatorRef.current) return
      const btn = tabsContainerRef.current.querySelector<HTMLButtonElement>(`[data-tab="${tab}"]`)
      if (!btn) return
      const btnRect = btn.getBoundingClientRect()
      const containerRect = tabsContainerRef.current.getBoundingClientRect()
      const left = btnRect.left - containerRect.left
      const width = btnRect.width
      indicatorRef.current.style.transform = `translateX(${left}px)`
      indicatorRef.current.style.width = `${width}px`
    }

    measure()

    if (typeof document !== 'undefined' && 'fonts' in document) {
      document.fonts.ready.then(measure).catch(() => {})
    }

    window.addEventListener('resize', measure)

    let ro: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined' && tabsContainerRef.current) {
      ro = new ResizeObserver(measure)
      ro.observe(tabsContainerRef.current)
    }

    const safetyTimer = setTimeout(measure, 120)

    return () => {
      window.removeEventListener('resize', measure)
      if (ro) ro.disconnect()
      clearTimeout(safetyTimer)
    }
  }, [tab, isMobile])

  const tabItems: { key: AppTab; label: string }[] = [
    { key: 'send',    label: t('tabs.send') },
    { key: 'swap',    label: t('tabs.swap') },
    { key: 'command', label: t('tabs.flow') },
  ]

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

      {/* Navbar /app — wallet-only: logo, chain family, network, wallet */}
      <nav
        data-phase={phase}
        data-dir={direction}
        className="fixed left-0 right-0 z-[1000] flex items-center justify-between gap-4 bg-white/85 border-b border-black/[0.06] backdrop-blur-md px-3 md:px-6"
        style={{
          top: 3,
          height: isMobile ? 52 : 60,
          WebkitBackdropFilter: 'blur(16px) saturate(180%)',
        }}
      >
        {/* Left: logo (links to /app) */}
        <Link href="/app" className="rp-brand flex items-center gap-2 no-underline">
          <img
            src="/favicon.svg"
            alt="RSends"
            width={28}
            height={28}
            className="rp-brand-dot rounded-[7px]"
          />
          {!isMobile && (
            <span className="font-display text-[16px] font-extrabold tracking-[-0.03em]" style={{ color: C.text }}>
              RSends
            </span>
          )}
        </Link>

        {/* Right: cluster ChainFamily | Network | Wallet */}
        <div className="flex items-center gap-2">
          <div className="rp-chain-pills">
            <ChainFamilySwitch
              active={activeFamily}
              onSelect={(family) => wallet.setActiveFamily(family)}
              connections={wallet.connections}
            />
          </div>
          <NetworkSelector />
          <div className="rp-wallet">
            <AccountHeader nonEvmWallet={nonEvmWallet} />
          </div>
        </div>
      </nav>

      {/* Main container */}
      <main style={{
        paddingTop: isMobile ? 75 : 90,
        paddingBottom: 80,
        minHeight: '100vh',
        background: C.bg,
      }}>
        {/* Tabs row — moved from navbar into body */}
        <div
          style={{
            maxWidth: 680,
            margin: '0 auto',
            padding: '0 20px',
            marginBottom: 16,
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <div
            ref={tabsContainerRef}
            className="flex items-center gap-1 relative"
            role="tablist"
            aria-label="App sections"
          >
            {tabItems.map(({ key, label }) => {
              const active = tab === key
              return (
                <button
                  key={key}
                  data-tab={key}
                  onClick={() => handleTabClick(key)}
                  role="tab"
                  aria-selected={active}
                  aria-current={active ? 'page' : undefined}
                  className={[
                    'rounded-md transition-colors font-display relative',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-black/20 focus-visible:ring-offset-0',
                    isMobile ? 'px-3 py-1.5 text-[12px]' : 'px-3 py-1.5 text-sm',
                    active
                      ? 'bg-neutral-100 text-black font-medium'
                      : 'text-black/60 hover:text-black hover:bg-black/[0.03]',
                  ].join(' ')}
                  style={{ zIndex: 1 }}
                >
                  {label}
                </button>
              )
            })}
            <div ref={indicatorRef} className="rp-tab-indicator" aria-hidden="true" />
          </div>
        </div>

        <div
          className="rp-tab-stage"
          data-phase={phase}
          data-dir={direction}
          style={{
            maxWidth: 680,
            margin: '0 auto',
            padding: '0 20px',
            position: 'relative',
            minHeight: isMobile ? 320 : 400,
          }}
        >
          {/* Send */}
          <div
            className="rp-panel rp-panel-border"
            data-active={tab === 'send'}
            data-phase={phase}
            data-dir={direction}
          >
            <ErrorBoundary module="TransferForm">
              <TransferForm noCard />
            </ErrorBoundary>
          </div>

          {/* Swap */}
          <div
            className="rp-panel rp-panel-border"
            data-active={tab === 'swap'}
            data-phase={phase}
            data-dir={direction}
          >
            <ErrorBoundary module="SwapModule">
              <SwapModule noCard onSwapComplete={() => {}} />
            </ErrorBoundary>
          </div>

          {/* Flow */}
          <div
            className="rp-panel rp-panel-border"
            data-active={tab === 'command'}
            data-phase={phase}
            data-dir={direction}
          >
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

      <TransactionPersistence />
      <ContactsPersistence />
      <PostLoginMerge />
    </>
  )
}
