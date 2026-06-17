/**
 * hooks/useTronWallet.ts — TronLink wallet connection hook
 *
 * TronLink inietta window.tronWeb e window.tronLink nel browser.
 * Questo hook gestisce connessione, firma e invio TX su TRON.
 */
'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

// ── Types ────────────────────────────────────────────────────────────────

interface TronWalletState {
  address: string | null
  isConnected: boolean
  isConnecting: boolean
  isInstalled: boolean
  network: 'mainnet' | 'shasta' | 'nile' | null
  balance: { trx: number; sun: number } | null
}

// ── Network detection ────────────────────────────────────────────────────

function detectTronNetwork(tw: any): 'mainnet' | 'shasta' | 'nile' | null {
  const host = tw?.fullNode?.host || ''
  if (host.includes('api.trongrid.io')) return 'mainnet'
  if (host.includes('shasta')) return 'shasta'
  if (host.includes('nile')) return 'nile'
  return null
}

// ── Hook ─────────────────────────────────────────────────────────────────

export function useTronWallet() {
  const [state, setState] = useState<TronWalletState>({
    address: null,
    isConnected: false,
    isConnecting: false,
    isInstalled: false,
    network: null,
    balance: null,
  })
  const connectingRef = useRef(false)

  // Detect TronLink installation + auto-detect if already connected
  useEffect(() => {
    const check = () => {
      const installed = typeof window !== 'undefined' && !!(window as any).tronLink
      setState(s => ({ ...s, isInstalled: installed }))

      const tw = (window as any).tronWeb
      if (tw && tw.ready && tw.defaultAddress?.base58) {
        setState(s => ({
          ...s,
          address: tw.defaultAddress.base58,
          isConnected: true,
          network: detectTronNetwork(tw),
        }))
      }
    }

    // TronLink may inject after page load
    if ((window as any).tronLink) {
      check()
    } else {
      window.addEventListener('tronLink#initialized', check, { once: true })
      // Fallback timeout in case the event never fires
      setTimeout(check, 2000)
    }

    return () => window.removeEventListener('tronLink#initialized', check)
  }, [])

  // Listen for account/network changes from TronLink
  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.message?.action === 'setAccount') {
        const addr = e.data.message.data?.address
        setState(s => ({
          ...s,
          address: addr || null,
          isConnected: !!addr,
        }))
      }
      if (e.data?.message?.action === 'setNode') {
        const tw = (window as any).tronWeb
        if (tw) setState(s => ({ ...s, network: detectTronNetwork(tw) }))
      }
      if (e.data?.message?.action === 'disconnect') {
        setState(s => ({ ...s, address: null, isConnected: false, balance: null }))
      }
    }
    window.addEventListener('message', handler)
    return () => window.removeEventListener('message', handler)
  }, [])

  // ── Connect ────────────────────────────────────────────────────────────

  const connect = useCallback(async () => {
    if (connectingRef.current) return
    connectingRef.current = true
    setState(s => ({ ...s, isConnecting: true }))

    try {
      const tronLink = (window as any).tronLink
      if (!tronLink) throw new Error('TronLink not installed')

      let res: any
      try {
        res = await tronLink.request({ method: 'tron_requestAccounts' })
      } catch (reqErr) {
        // Some TronLink versions throw instead of returning a code object
        res = reqErr
      }
      try { console.log('[RSend] TronLink response:', JSON.stringify(res)) } catch {}

      const code = res && typeof res === 'object' ? res.code : undefined
      // 4000 = request in queue / not logged in, 4001 = already accepted,
      // 4002 = user rejected. Only 4002 is a hard rejection.
      if (code === 4002) {
        throw new Error('User rejected connection')
      }

      // Ground truth: wait up to ~2s for tronWeb to become ready + have an address.
      // Newer TronLink versions may return void/undefined from request(), so we
      // rely on polling the injected tronWeb object rather than the response code.
      const tw: any = await (async () => {
        for (let i = 0; i < 10; i++) {
          const w = (window as any).tronWeb
          if (w && w.ready && w.defaultAddress?.base58) return w
          await new Promise(r => setTimeout(r, 200))
        }
        return (window as any).tronWeb
      })()

      if (tw && tw.defaultAddress?.base58) {
        setState(s => ({
          ...s,
          address: tw.defaultAddress.base58,
          isConnected: true,
          network: detectTronNetwork(tw),
        }))
      } else {
        throw new Error(
          `TronLink not ready after request (code=${code ?? 'undefined'}) — ` +
            `unlock wallet or approve the connection in the extension popup`,
        )
      }
    } catch (err) {
      console.error('[RSend] TronLink connect failed:', err)
    } finally {
      connectingRef.current = false
      setState(s => ({ ...s, isConnecting: false }))
    }
  }, [])

  // ── Disconnect ─────────────────────────────────────────────────────────

  const disconnect = useCallback(() => {
    setState({
      address: null,
      isConnected: false,
      isConnecting: false,
      isInstalled: state.isInstalled,
      network: null,
      balance: null,
    })
  }, [state.isInstalled])

  // ── Sign a transaction (opens TronLink popup) ─────────────────────────

  const signTransaction = useCallback(async (tx: any): Promise<any> => {
    const tw = (window as any).tronWeb
    if (!tw || !tw.ready) throw new Error('TronLink not ready')

    const signed = await tw.trx.sign(tx)
    return signed
  }, [])

  // ── Broadcast signed transaction ──────────────────────────────────────

  const broadcastTransaction = useCallback(async (signedTx: any): Promise<string> => {
    const tw = (window as any).tronWeb
    if (!tw) throw new Error('TronLink not ready')

    const result = await tw.trx.sendRawTransaction(signedTx)
    if (!result.result) throw new Error(result.message || 'Broadcast failed')
    return result.txid
  }, [])

  // ── Transfer TRX ──────────────────────────────────────────────────────

  const sendTRX = useCallback(async (to: string, amountSun: number): Promise<string> => {
    const tw = (window as any).tronWeb
    if (!tw || !tw.ready) throw new Error('TronLink not ready')

    try {
      const tx = await tw.transactionBuilder.sendTrx(to, amountSun, state.address)
      const signed = await tw.trx.sign(tx)
      const result = await tw.trx.sendRawTransaction(signed)
      if (!result.result) throw new Error('TRX transfer failed')
      return result.txid
    } catch (err) {
      console.error('[RSend] TRX transfer error:', err)
      throw err
    }
  }, [state.address])

  // ── Transfer TRC-20 ───────────────────────────────────────────────────

  const sendTRC20 = useCallback(async (
    contractAddress: string, to: string, amount: string
  ): Promise<string> => {
    const tw = (window as any).tronWeb
    if (!tw || !tw.ready) throw new Error('TronLink not ready')

    try {
      const contract = await tw.contract().at(contractAddress)
      const tx = await contract.transfer(to, amount).send()
      return tx // tx hash
    } catch (err) {
      console.error('[RSend] TRC-20 transfer error:', err)
      throw err
    }
  }, [])

  return {
    ...state,
    connect,
    disconnect,
    signTransaction,
    broadcastTransaction,
    sendTRX,
    sendTRC20,
  }
}
