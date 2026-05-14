'use client'

import { useState, useCallback } from 'react'
import {
  useAccount, usePublicClient,
  useSignTypedData, useWriteContract,
} from 'wagmi'
import { erc20Abi, maxUint256, keccak256, toBytes, type Abi } from 'viem'

// ── Costanti ───────────────────────────────────────────────────────────────
export const PERMIT2_ADDRESS =
  '0x000000000022D473030F116dDEE9F6B43aC78BA3' as `0x${string}`

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

// FeeRouterV3 ABI (solo transferWithPermit2)
const FEE_ROUTER_V3_ABI: Abi = [
  {
    name: 'transferWithPermit2',
    type: 'function',
    stateMutability: 'nonpayable',
    inputs: [
      {
        name: 'p',
        type: 'tuple',
        components: [
          { name: 'token',               type: 'address' },
          { name: 'amount',              type: 'uint256' },
          { name: 'permit2Nonce',        type: 'uint256' },
          { name: 'permit2Deadline',     type: 'uint256' },
          { name: 'permit2Signature',    type: 'bytes'   },
          { name: 'recipient',           type: 'address' },
          { name: 'paymentRef',          type: 'bytes32' },
          { name: 'fiscalRef',           type: 'bytes32' },
          { name: 'complianceNonce',     type: 'bytes32' },
          { name: 'complianceDeadline',  type: 'uint256' },
          { name: 'complianceSignature', type: 'bytes'   },
        ],
      },
      { name: 'sender', type: 'address' },
    ],
    outputs: [],
  },
]

// ── Tipi ───────────────────────────────────────────────────────────────────
export type Permit2FlowPhase =
  | 'idle'
  | 'checking_approval'    // verifica one-time approve token → Permit2
  | 'approving_permit2'    // TX approve Permit2 (una tantum per token)
  | 'preflight_compliance' // POST /api/v1/compliance/check
  | 'signing_permit2'      // firma EIP-712 Permit2 (off-chain)
  | 'executing'            // TX on-chain transferWithPermit2
  | 'done'
  | 'error'

export interface ComplianceCheckRequest {
  sender:    string
  recipient: string
  token:     string
  amount:    string  // formatted
  symbol:    string
  chainId:   number
}

export interface ComplianceCheckResponse {
  approved:            boolean
  complianceSignature: `0x${string}`
  complianceNonce:     `0x${string}`  // bytes32
  complianceDeadline:  number         // unix timestamp
  paymentRef:          `0x${string}`  // bytes32 keccak256
  fiscalRef:           `0x${string}`  // bytes32 keccak256
  riskScore:           number         // 0-100
  jurisdiction:        string         // 'IT', 'DE', 'EU'...
  rejectionReason?:    string
}

export interface Permit2FlowResult {
  txHash:    `0x${string}`
  paymentRef: `0x${string}`
  fiscalRef:  `0x${string}`
  complianceNonce: `0x${string}`
  riskScore:  number
}

// ── API Base URL ────────────────────────────────────────────────────────────
// Same-origin proxy → see app/api/backend/[...path]/route.ts
const API_BASE = '/api/backend'

// ── Hook ───────────────────────────────────────────────────────────────────
export function usePermit2Flow(feeRouterV3: `0x${string}`) {
  const { address } = useAccount()
  const publicClient = usePublicClient()
  const { signTypedDataAsync } = useSignTypedData()
  const { writeContractAsync } = useWriteContract()

  const [phase,         setPhase]         = useState<Permit2FlowPhase>('idle')
  const [result,        setResult]        = useState<Permit2FlowResult | null>(null)
  const [error,         setError]         = useState('')
  const [complianceData, setComplianceData] = useState<ComplianceCheckResponse | null>(null)
  const [riskScore,     setRiskScore]     = useState<number | null>(null)

  // ── FASE 0: One-time approve token → Permit2 ──────────────────────────
  const ensurePermit2Approval = useCallback(async (
    token: `0x${string}`
  ): Promise<boolean> => {
    if (!address || !publicClient) return false
    setPhase('checking_approval')
    try {
      const current = await publicClient.readContract({
        address: token, abi: erc20Abi,
        functionName: 'allowance',
        args: [address, PERMIT2_ADDRESS],
      }) as bigint

      if (current > 0n) return true // già approvato

      setPhase('approving_permit2')
      await writeContractAsync({
        address: token, abi: erc20Abi,
        functionName: 'approve',
        args: [PERMIT2_ADDRESS, maxUint256],
      })
      return true
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('rejected') || m.includes('denied')
          ? 'Approvazione Permit2 annullata.'
          : 'Errore Permit2 approval: ' + m.slice(0, 80)
      )
      setPhase('error')
      return false
    }
  }, [address, publicClient, writeContractAsync])

  // ── FASE 1: Pre-Flight Compliance Check ───────────────────────────────
  const preflightCompliance = useCallback(async (
    req: ComplianceCheckRequest
  ): Promise<ComplianceCheckResponse | null> => {
    setPhase('preflight_compliance')
    try {
      const res = await fetch(`${API_BASE}/api/v1/compliance/check`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(req),
        signal:  AbortSignal.timeout(10_000),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        setError(`Compliance check fallito (${res.status}): ${err.detail ?? 'errore sconosciuto'}`)
        setPhase('error')
        return null
      }

      const data: ComplianceCheckResponse = await res.json()

      if (!data.approved) {
        setError(`Transazione non approvata dall'AML Oracle: ${data.rejectionReason ?? 'indirizzo a rischio'}`)
        setPhase('error')
        return null
      }

      setComplianceData(data)
      setRiskScore(data.riskScore)
      return data
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('AbortError') || m.includes('timeout')
          ? 'Compliance Oracle non raggiungibile. Riprova.'
          : 'Errore compliance: ' + m.slice(0, 80)
      )
      setPhase('error')
      return null
    }
  }, [])

  // ── FASE 2: EIP-712 Permit2 Sign (off-chain) ──────────────────────────
  const signPermit2 = useCallback(async (params: {
    token:   `0x${string}`
    amount:  bigint
    chainId: number
  }): Promise<{ signature: `0x${string}`; nonce: bigint; deadline: bigint } | null> => {
    if (!address || !publicClient) return null
    setPhase('signing_permit2')
    try {
      // Legge nonce corrente da Permit2
      const data = await publicClient.readContract({
        address: PERMIT2_ADDRESS,
        abi:     PERMIT2_ABI,
        functionName: 'allowance',
        args: [address, params.token, feeRouterV3],
      }) as [bigint, number, number]

      const nonce    = BigInt(data[2])
      const deadline = BigInt(Math.floor(Date.now() / 1000) + 1800) // 30 min

      // EIP-712 typed data per ISignatureTransfer.PermitTransferFrom
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
        spender:   feeRouterV3,
        nonce,
        deadline,
      } as const

      const signature = await signTypedDataAsync({
        domain, types, message,
        primaryType: 'PermitTransferFrom',
      })

      return { signature, nonce, deadline }
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('rejected') || m.includes('denied')
          ? 'Firma Permit2 annullata. Nessun costo addebitato.'
          : 'Errore firma EIP-712: ' + m.slice(0, 80)
      )
      setPhase('error')
      return null
    }
  }, [address, publicClient, feeRouterV3, signTypedDataAsync])

  // ── FASE 3: Atomic Execution on-chain ─────────────────────────────────
  const executeTransfer = useCallback(async (params: {
    token:               `0x${string}`
    amount:              bigint
    recipient:           `0x${string}`
    permit2Signature:    `0x${string}`
    permit2Nonce:        bigint
    permit2Deadline:     bigint
    complianceData:      ComplianceCheckResponse
  }): Promise<`0x${string}` | null> => {
    if (!address) return null
    setPhase('executing')
    try {
      const hash = await writeContractAsync({
        address: feeRouterV3,
        abi:     FEE_ROUTER_V3_ABI,
        functionName: 'transferWithPermit2',
        args: [
          {
            token:               params.token,
            amount:              params.amount,
            permit2Nonce:        params.permit2Nonce,
            permit2Deadline:     params.permit2Deadline,
            permit2Signature:    params.permit2Signature,
            recipient:           params.recipient,
            paymentRef:          params.complianceData.paymentRef,
            fiscalRef:           params.complianceData.fiscalRef,
            complianceNonce:     params.complianceData.complianceNonce,
            complianceDeadline:  BigInt(params.complianceData.complianceDeadline),
            complianceSignature: params.complianceData.complianceSignature,
          },
          address,
        ],
      })
      return hash
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError(
        m.includes('rejected') || m.includes('denied')
          ? 'Transazione annullata. Nessun costo addebitato.'
          : m.includes('ComplianceSignatureInvalid')
          ? 'Firma di compliance non valida. Richiedi una nuova approvazione.'
          : m.includes('ComplianceSignatureExpired')
          ? 'Approvazione AML scaduta. Ricomincia il flusso.'
          : m.includes('RecipientBlacklisted')
          ? 'Destinatario bloccato on-chain. Transazione non permessa.'
          : 'Errore esecuzione: ' + m.slice(0, 100)
      )
      setPhase('error')
      return null
    }
  }, [address, feeRouterV3, writeContractAsync])

  // ── FLUSSO COMPLETO: tutto in sequenza ────────────────────────────────
  const runFullFlow = useCallback(async (params: {
    token:     `0x${string}`
    amount:    bigint
    amountFormatted: string
    symbol:    string
    recipient: `0x${string}`
    chainId:   number
  }): Promise<Permit2FlowResult | null> => {
    if (!address) return null
    setError('')

    try {
      // 0. One-time approve → Permit2
      const approved = await ensurePermit2Approval(params.token)
      if (!approved) return null

      // 1. Pre-flight compliance check
      const compliance = await preflightCompliance({
        sender:    address,
        recipient: params.recipient,
        token:     params.token,
        amount:    params.amountFormatted,
        symbol:    params.symbol,
        chainId:   params.chainId,
      })
      if (!compliance) return null

      // 2. Sign Permit2 EIP-712 (off-chain)
      const permit2Result = await signPermit2({
        token:   params.token,
        amount:  params.amount,
        chainId: params.chainId,
      })
      if (!permit2Result) return null

      // 3. Execute on-chain (1 TX atomica)
      const txHash = await executeTransfer({
        token:            params.token,
        amount:           params.amount,
        recipient:        params.recipient,
        permit2Signature: permit2Result.signature,
        permit2Nonce:     permit2Result.nonce,
        permit2Deadline:  permit2Result.deadline,
        complianceData:   compliance,
      })
      if (!txHash) return null

      const res: Permit2FlowResult = {
        txHash,
        paymentRef:      compliance.paymentRef,
        fiscalRef:       compliance.fiscalRef,
        complianceNonce: compliance.complianceNonce,
        riskScore:       compliance.riskScore,
      }
      setResult(res)
      setPhase('done')
      return res
    } catch (e) {
      const m = e instanceof Error ? e.message : ''
      setError('Errore inaspettato: ' + m.slice(0, 100))
      setPhase('error')
      return null
    }
  }, [address, ensurePermit2Approval, preflightCompliance, signPermit2, executeTransfer])

  const reset = useCallback(() => {
    setPhase('idle'); setResult(null); setError('')
    setComplianceData(null); setRiskScore(null)
  }, [])

  return {
    phase, result, error, riskScore, complianceData,
    runFullFlow, reset,
    isLoading: !['idle','done','error'].includes(phase),
    isDone:    phase === 'done',
    isError:   phase === 'error',
  }
}
