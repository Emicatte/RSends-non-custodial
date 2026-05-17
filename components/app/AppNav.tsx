'use client'

import { useEffect, useState } from 'react'
import { Link } from '@/i18n/navigation'
import { ChainFamilySwitch } from '@/components/shared/ChainFamilySwitch'
import NetworkSelector from '@/app/NetworkSelector'
import AccountHeader, { type NonEvmWalletProps } from '@/app/AccountHeader'
import { useUniversalWallet } from '@/hooks/useUniversalWallet'
import { useWallet as useSolanaWallet } from '@solana/wallet-adapter-react'
import { useTron } from '@/app/providers-tron'
import { C } from '@/app/designTokens'

export default function AppNav() {
  const [isMobile, setIsMobile] = useState(false)

  const wallet = useUniversalWallet()
  const activeFamily = wallet.activeFamily

  const { disconnect: solanaDisconnect } = useSolanaWallet()
  const tron = useTron()

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

  return (
    <>
      {/* Top accent bar */}
      <div
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: C.text,
          zIndex: 1001,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: 96,
            height: 3,
            background: C.purple,
          }}
        />
      </div>

      {/* Navbar — wallet-only */}
      <nav
        className="fixed left-0 right-0 z-[1000] flex items-center justify-between gap-4 bg-white/85 border-b border-black/[0.06] backdrop-blur-md px-3 md:px-6"
        style={{
          top: 3,
          height: isMobile ? 52 : 60,
          WebkitBackdropFilter: 'blur(16px) saturate(180%)',
        }}
      >
        <Link href="/" className="rp-brand flex items-center gap-2 no-underline">
          <img
            src="/favicon.svg"
            alt="RSends"
            width={28}
            height={28}
            className="rp-brand-dot rounded-[7px]"
          />
          {!isMobile && (
            <span
              className="font-display text-[16px] font-extrabold tracking-[-0.03em]"
              style={{ color: C.text }}
            >
              RSends
            </span>
          )}
        </Link>

        <div className="flex items-center gap-2">
          <div className="rp-chain-pills hidden md:flex">
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
    </>
  )
}
