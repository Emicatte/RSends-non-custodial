

import { useState, useCallback } from 'react'
import { useAccount, usePublicClient } from 'wagmi'
import { encodeFunctionData, parseUnits, type Abi } from 'viem'
import { base, baseSepolia } from 'wagmi/chains'

// ── Stablecoin supportate per gasless ─────────────────────────────────────
const GASLESS_TOKENS: Record<string, `0x${string}`> = {
  USDC: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  EURC: '0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42',
}

export type PaymasterMode =
  | 'unavailable'   // Paymaster non configurato → TX standard
  | 'sponsored'     // gas coperto dal Paymaster aziendale
  | 'erc20'         // gas detratto dal token
  | 'estimating'    // stima in corso
  | 'error'

export interface PaymasterEstimate {
  mode:           PaymasterMode
  gasSponsored:   boolean
  estimatedGasUsd: string
  paymasterUrl:   string | null
}

// ── Hook ───────────────────────────────────────────────────────────────────
export function useGaslessPaymaster() {
  const { address } = useAccount()
  const publicClient = usePublicClient()

  const [mode,     setMode]     = useState<PaymasterMode>('unavailable')
  const [estimate, setEstimate] = useState<PaymasterEstimate | null>(null)
  const [error,    setError]    = useState('')

  // L3 — the Pimlico API key now lives server-side. The client only knows
  // whether gasless is enabled (a non-secret flag) and talks to our same-origin
  // proxy (/api/paymaster/<network>), which attaches the key.
  const enabled     = process.env.NEXT_PUBLIC_PAYMASTER_ENABLED === '1'
  const chainId     = publicClient?.chain?.id ?? base.id
  const isTestnet   = chainId === baseSepolia.id
  const networkSlug = isTestnet ? 'base-sepolia' : 'base'

  // Same-origin proxy to the Pimlico bundler (no key in the URL).
  const bundlerUrl = enabled ? `/api/paymaster/${networkSlug}` : null

  // ── Controlla se il token è idoneo per gasless ─────────────────────────
  const isGaslessEligible = useCallback((tokenSymbol: string): boolean => {
    return tokenSymbol.toUpperCase() in GASLESS_TOKENS
  }, [])

  // ── Stima costo gas (con o senza Paymaster) ────────────────────────────
  const estimateGas = useCallback(async (
    tokenSymbol: string
  ): Promise<PaymasterEstimate> => {
    setMode('estimating')
    try {
      const gp = await publicClient?.getGasPrice() ?? 1_500_000_000n
      const estimatedGasUnits = 80_000n // ERC20 split TX
      const ethPrice = 2200 // mock — in produzione usa Chainlink
      const gasCostUsd = (
        parseFloat((estimatedGasUnits * gp).toString()) * 1e-18 * ethPrice
      ).toFixed(4)

      if (!enabled || !isGaslessEligible(tokenSymbol)) {
        const est: PaymasterEstimate = {
          mode: 'unavailable',
          gasSponsored: false,
          estimatedGasUsd: gasCostUsd,
          paymasterUrl: null,
        }
        setEstimate(est)
        setMode('unavailable')
        return est
      }

      // Paymaster disponibile → sponsored
      const est: PaymasterEstimate = {
        mode: 'sponsored',
        gasSponsored: true,
        estimatedGasUsd: '0.0000',
        paymasterUrl: bundlerUrl,
      }
      setEstimate(est)
      setMode('sponsored')
      return est
    } catch (e) {
      setMode('error')
      setError('Errore stima Paymaster: ' + (e instanceof Error ? e.message : ''))
      const fallback: PaymasterEstimate = {
        mode: 'error', gasSponsored: false,
        estimatedGasUsd: '—', paymasterUrl: null,
      }
      setEstimate(fallback)
      return fallback
    }
  }, [publicClient, enabled, bundlerUrl, isGaslessEligible])

  
  const buildSponsoredTx = useCallback(async (params: {
    to:      `0x${string}`
    data:    `0x${string}`
    value?:  bigint
  }): Promise<{ sponsored: boolean; txHash?: string; error?: string }> => {
    if (!bundlerUrl || !address) {
      return { sponsored: false, error: 'Paymaster non configurato' }
    }

    try {
      // Stima gas dal bundler Pimlico
      const response = await fetch(bundlerUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0', id: 1,
          method:  'pm_sponsorUserOperation',
          params: [{
            sender:               address,
            nonce:                '0x0',
            initCode:             '0x',
            callData:             params.data,
            callGasLimit:         '0x0',
            verificationGasLimit: '0x0',
            preVerificationGas:   '0x0',
            maxFeePerGas:         '0x0',
            maxPriorityFeePerGas: '0x0',
            paymasterAndData:     '0x',
            signature:            '0x',
          }, 'latest'],
        }),
      })

      const json = await response.json()
      if (json.error) {
        return { sponsored: false, error: json.error.message }
      }

      return { sponsored: true }
    } catch (e) {
      return {
        sponsored: false,
        error: 'Paymaster non raggiungibile. Usando TX standard.',
      }
    }
  }, [bundlerUrl, address])

  const reset = useCallback(() => {
    setMode('unavailable'); setEstimate(null); setError('')
  }, [])

  return {
    mode, estimate, error,
    isGaslessEligible, estimateGas, buildSponsoredTx, reset,
    isSponsored: mode === 'sponsored',
    paymasterConfigured: enabled,
  }
}
