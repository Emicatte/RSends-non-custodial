
import { useState, useCallback } from 'react'
import {
  useAccount, usePublicClient,
  useSignTypedData, useWriteContract,
} from 'wagmi'
import { erc20Abi, maxUint256 } from 'viem'

// ── Costanti ───────────────────────────────────────────────────────────────
export const PERMIT2_ADDRESS =
  '0x000000000022D473030F116dDEE9F6B43aC78BA3' as `0x${string}`

// ABI minima Permit2
const PERMIT2_ABI = [
  {
    name: 'allowance',
    type: 'function' as const,
    stateMutability: 'view' as const,
    inputs: [
      { name: 'owner',   type: 'address' as const },
      { name: 'token',   type: 'address' as const },
      { name: 'spender', type: 'address' as const },
    ],
    outputs: [
      { name: 'amount',     type: 'uint160' as const },
      { name: 'expiration', type: 'uint48'  as const },
      { name: 'nonce',      type: 'uint48'  as const },
    ],
  },
] as const

// ── Tipi ───────────────────────────────────────────────────────────────────
export type Permit2Phase =
  | 'idle'
  | 'checking_approval'   // legge allowance token → Permit2
  | 'approving_permit2'   // approve one-time in corso
  | 'wait_approval'       // attesa conferma approve on-chain
  | 'ready'               // pronto per firma
  | 'signing'             // signTypedData in corso
  | 'signed'              // firma ottenuta
  | 'error'

export interface Permit2Result {
  signature: `0x${string}`
  nonce:     bigint
  deadline:  bigint
  amount:    bigint
  token:     `0x${string}`
  spender:   `0x${string}`
}

// ── Hook ───────────────────────────────────────────────────────────────────
export function usePermit2(spender: `0x${string}`) {
  const { address } = useAccount()
  const publicClient = usePublicClient()
  const { signTypedDataAsync }  = useSignTypedData()
  const { writeContractAsync }  = useWriteContract()

  const [phase,  setPhase]  = useState<Permit2Phase>('idle')
  const [result, setResult] = useState<Permit2Result | null>(null)
  const [error,  setError]  = useState('')

  // ── Step 1: assicura che il token sia approvato a Permit2 ──────────────
  const ensureApproval = useCallback(async (
    token: `0x${string}`
  ): Promise<boolean> => {
    if (!address || !publicClient) return false
    setPhase('checking_approval')
    try {
      const allowance = await publicClient.readContract({
        address: token, abi: erc20Abi,
        functionName: 'allowance',
        args: [address, PERMIT2_ADDRESS],
      }) as bigint

      if (allowance > 0n) { setPhase('ready'); return true }

      // One-time infinite approve al contratto Permit2
      setPhase('approving_permit2')
      await writeContractAsync({
        address: token, abi: erc20Abi,
        functionName: 'approve',
        args: [PERMIT2_ADDRESS, maxUint256],
      })
      setPhase('ready')
      return true
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('rejected') || m.includes('denied')
          ? 'Approvazione Permit2 annullata dall\'utente.'
          : 'Errore approvazione Permit2: ' + m.slice(0, 80)
      )
      setPhase('error')
      return false
    }
  }, [address, publicClient, writeContractAsync])

  // ── Step 2: firma EIP-712 off-chain PermitTransferFrom ─────────────────
  const signPermit = useCallback(async (params: {
    token:   `0x${string}`
    amount:  bigint
    chainId: number
  }): Promise<Permit2Result | null> => {
    if (!address || !publicClient) return null
    setPhase('signing')
    try {
      // Legge nonce corrente da Permit2
      const data = await publicClient.readContract({
        address: PERMIT2_ADDRESS,
        abi: PERMIT2_ABI,
        functionName: 'allowance',
        args: [address, params.token, spender],
      }) as [bigint, number, number]

      const nonce    = BigInt(data[2])
      const deadline = BigInt(Math.floor(Date.now() / 1000) + 3600) // 1h

      // Struttura EIP-712 per PermitTransferFrom
      const domain = {
        name:              'Permit2',
        chainId:           params.chainId,
        verifyingContract: PERMIT2_ADDRESS,
      } as const

      const types = {
        PermitTransferFrom: [
          { name: 'permitted', type: 'TokenPermissions' as const },
          { name: 'spender',   type: 'address'          as const },
          { name: 'nonce',     type: 'uint256'           as const },
          { name: 'deadline',  type: 'uint256'           as const },
        ],
        TokenPermissions: [
          { name: 'token',  type: 'address' as const },
          { name: 'amount', type: 'uint256' as const },
        ],
      } as const

      const message = {
        permitted: { token: params.token, amount: params.amount },
        spender,
        nonce,
        deadline,
      } as const

      const signature = await signTypedDataAsync({
        domain, types, message,
        primaryType: 'PermitTransferFrom',
      })

      const res: Permit2Result = {
        signature, nonce, deadline,
        amount: params.amount,
        token:  params.token,
        spender,
      }
      setResult(res)
      setPhase('signed')
      return res
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('rejected') || m.includes('denied')
          ? 'Firma Permit annullata. Nessun costo addebitato.'
          : 'Errore firma EIP-712: ' + m.slice(0, 80)
      )
      setPhase('error')
      return null
    }
  }, [address, publicClient, spender, signTypedDataAsync])

  // ── Flusso completo: ensure + sign ────────────────────────────────────
  const runPermitFlow = useCallback(async (params: {
    token:   `0x${string}`
    amount:  bigint
    chainId: number
  }): Promise<Permit2Result | null> => {
    const approved = await ensureApproval(params.token)
    if (!approved) return null
    return signPermit(params)
  }, [ensureApproval, signPermit])

  const reset = useCallback(() => {
    setPhase('idle'); setResult(null); setError('')
  }, [])

  return {
    phase, result, error,
    ensureApproval, signPermit, runPermitFlow, reset,
    isLoading: phase === 'checking_approval' || phase === 'approving_permit2' || phase === 'signing',
    isSigned:  phase === 'signed',
    isError:   phase === 'error',
  }
}
