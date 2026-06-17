/**
 * hooks/useUniversalWallet.ts — Unified multi-chain wallet interface
 *
 * Unifica EVM (wagmi) + Solana (@solana/wallet-adapter) + Tron (TronLink)
 * sotto un'unica interfaccia. L'utente può avere tutti e 3 connessi
 * contemporaneamente e switchare la famiglia attiva.
 */
'use client'

import { useState, useMemo } from 'react'
import { useAccount, useChainId } from 'wagmi'
import { useWallet as useSolanaWallet } from '@solana/wallet-adapter-react'
import { useTron } from '../app/providers-tron'
import type { ChainFamily, UniversalAddress } from '../lib/chain-adapters/types'

// ── Types ────────────────────────────────────────────────────────────────

export interface UnifiedWallet {
  /** Famiglia chain attiva */
  activeFamily: ChainFamily
  /** Indirizzo attivo (formato della chain corrente) */
  activeAddress: UniversalAddress | null
  /** Tutte le connessioni attive (utente può avere EVM + Solana + Tron) */
  connections: {
    evm: { address: string | null; chainId: number; isConnected: boolean }
    solana: { address: string | null; isConnected: boolean }
    tron: { address: string | null; isConnected: boolean }
  }
  /** Cambia la famiglia chain attiva */
  setActiveFamily: (family: ChainFamily) => void
  /** Numero totale di wallet connessi */
  connectedCount: number
}

// ── Hook ─────────────────────────────────────────────────────────────────

export function useUniversalWallet(): UnifiedWallet {
  const [activeFamily, setActiveFamily] = useState<ChainFamily>('evm')

  // EVM (wagmi)
  const { address: evmAddress, isConnected: evmConnected } = useAccount()
  const evmChainId = useChainId()

  // Solana
  let solAddress: string | null = null
  let solConnected = false
  try {
    const sol = useSolanaWallet()
    solAddress = sol.publicKey?.toBase58() ?? null
    solConnected = sol.connected
  } catch {
    // Solana provider non montato — OK, è opzionale
  }

  // Tron
  let tronAddress: string | null = null
  let tronConnected = false
  try {
    const tron = useTron()
    tronAddress = tron.address
    tronConnected = tron.isConnected
  } catch {
    // Tron provider non montato — OK, è opzionale
  }

  const connections = useMemo(() => ({
    evm: { address: evmAddress ?? null, chainId: evmChainId, isConnected: evmConnected },
    solana: { address: solAddress, isConnected: solConnected },
    tron: { address: tronAddress, isConnected: tronConnected },
  }), [evmAddress, evmChainId, evmConnected, solAddress, solConnected, tronAddress, tronConnected])

  const activeAddress: UniversalAddress | null = useMemo(() => {
    switch (activeFamily) {
      case 'evm':
        return evmAddress
          ? { raw: evmAddress, display: `${evmAddress.slice(0, 6)}...${evmAddress.slice(-4)}`, family: 'evm' as const }
          : null
      case 'solana':
        return solAddress
          ? { raw: solAddress, display: `${solAddress.slice(0, 4)}...${solAddress.slice(-4)}`, family: 'solana' as const }
          : null
      case 'tron':
        return tronAddress
          ? { raw: tronAddress, display: `${tronAddress.slice(0, 5)}...${tronAddress.slice(-4)}`, family: 'tron' as const }
          : null
    }
  }, [activeFamily, evmAddress, solAddress, tronAddress])

  const connectedCount = [evmConnected, solConnected, tronConnected].filter(Boolean).length

  return { activeFamily, activeAddress, connections, setActiveFamily, connectedCount }
}
