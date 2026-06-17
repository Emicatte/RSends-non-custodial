'use client'

/**
 * app/providers-tron.tsx — Tron wallet context provider
 *
 * TronLink non ha un provider React ufficiale,
 * quindi usiamo il nostro hook + context.
 * Caricato via dynamic() con ssr: false in providers.tsx.
 */

import { createContext, useContext } from 'react'
import { useTronWallet } from '../hooks/useTronWallet'

type TronContext = ReturnType<typeof useTronWallet>

const TronWalletContext = createContext<TronContext | null>(null)

export function TronProvider({ children }: { children: React.ReactNode }) {
  const tron = useTronWallet()
  return (
    <TronWalletContext.Provider value={tron}>
      {children}
    </TronWalletContext.Provider>
  )
}

export function useTron(): TronContext {
  const ctx = useContext(TronWalletContext)
  if (!ctx) throw new Error('useTron must be used within TronProvider')
  return ctx
}
