import { NextRequest, NextResponse }  from 'next/server'
import {
  keccak256, toHex, type Hex,
  recoverTypedDataAddress, hashTypedData,
  createPublicClient, http, encodeFunctionData, encodeAbiParameters, toBytes,
} from 'viem'
import { getRegistry } from '@/lib/contractRegistry'
import { privateKeyToAccount } from 'viem/accounts'
import { randomBytes }         from 'crypto'
import { requireEnv }          from '@/lib/env'
import { getClientIp, checkRateLimit } from '@/lib/rateLimit'
import { logger }              from '@/lib/logger'

// ── Config ─────────────────────────────────────────────────────────────────
const ORACLE_PRIVATE_KEY = process.env.ORACLE_PRIVATE_KEY as Hex | undefined
// M1 — when 'remote', the EIP-712 digest is signed by the backend's dedicated
// oracle signer (KMS in prod) instead of a local ORACLE_PRIVATE_KEY, so the key
// never lives in this web tier. Default 'local' = unchanged behaviour.
const ORACLE_SIGNER_MODE = (process.env.ORACLE_SIGNER_MODE ?? 'local').toLowerCase()
// L1 — never expose oracle internals (signer address, router/domain config, env
// flags) in production. Set ORACLE_DEBUG=1 to re-enable for diagnostics.
const ORACLE_DEBUG = process.env.NODE_ENV !== 'production' || process.env.ORACLE_DEBUG === '1'
const BACKEND_URL = requireEnv('RPAGOS_BACKEND_URL')
// Shared secret authenticating this server-side oracle to the backend
// /api/internal/* endpoints (H3). Must match INTERNAL_PROXY_SECRET on backend.
const INTERNAL_SECRET = process.env.INTERNAL_PROXY_SECRET ?? ''

// ── Signing Guard — pre-flight check via backend ───────────────────────────
async function signingGuardCheck(params: {
  wallet: string; recipient: string; tokenIn: string;
  amountInWei: string; nonce: string; deadline: number;
  chainId: number; ipAddress: string | null; contractAddress: string;
}): Promise<{ allowed: boolean; reason?: string }> {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/internal/signing/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Secret': INTERNAL_SECRET },
      body: JSON.stringify({
        wallet: params.wallet,
        recipient: params.recipient,
        token_in: params.tokenIn,
        amount_in_wei: params.amountInWei,
        nonce: params.nonce,
        deadline: params.deadline,
        chain_id: params.chainId,
        ip_address: params.ipAddress,
        contract_address: params.contractAddress,
      }),
      signal: AbortSignal.timeout(3000), // 3s timeout
    })
    if (!resp.ok) return { allowed: false, reason: `guard_http_${resp.status}` }
    return await resp.json()
  } catch (err) {
    // Fail-closed: if backend guard is unreachable, block the signature
    logger.error('oracle/sign', 'Signing guard unreachable', { err: String(err) })
    return { allowed: false, reason: 'guard_unavailable (fail-closed)' }
  }
}

// ── Shared rate-limit — Redis-backed early gate via backend (M5) ───────────
// The in-memory limiter in the handler is a per-process fast-path; this makes
// the throttle shared + atomic across all instances and keys on the (now
// trusted) client IP. Fail-closed: a backend/Redis blip blocks signing,
// consistent with the rest of the signing path (signingGuardCheck).
async function sharedRateLimit(p: {
  bucket: string; key: string; max: number; windowSeconds: number
}): Promise<{ allowed: boolean; retryAfter?: number }> {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/internal/ratelimit/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Internal-Secret': INTERNAL_SECRET },
      body: JSON.stringify({
        bucket: p.bucket, key: p.key, max: p.max, window_seconds: p.windowSeconds,
      }),
      signal: AbortSignal.timeout(2000),
    })
    if (!resp.ok) return { allowed: false }
    const j = await resp.json()
    return { allowed: !!j.allowed, retryAfter: j.retry_after }
  } catch (err) {
    logger.error('oracle/sign', 'shared rate-limit unreachable', { err: String(err) })
    return { allowed: false }
  }
}

// ── Remote oracle signer (M1) — sign the EIP-712 digest via backend KMS ────
// Delegates digest signing to the backend's dedicated oracle signer so the key
// never lives in this web tier. Gated by the H3 internal secret. Throws on any
// failure → the route's outer try/catch fail-closes (no signature emitted).
async function remoteSignDigest(
  digest: Hex,
): Promise<{ signature: Hex; signerAddress: string; signatures: Hex[]; signerAddresses: string[] }> {
  const resp = await fetch(`${BACKEND_URL}/api/internal/oracle/sign-digest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Internal-Secret': INTERNAL_SECRET },
    body: JSON.stringify({ digest }),
    signal: AbortSignal.timeout(3000),
  })
  if (!resp.ok) throw new Error(`remote oracle signer HTTP ${resp.status}`)
  const j = await resp.json()
  return {
    signature: j.signature as Hex,
    signerAddress: j.signer_address as string,
    // V5/V6 multisig: signatures ascending by signer address. Fall back to the
    // single primary signature when the backend predates the multi field.
    signatures: (j.signatures ?? [j.signature]) as Hex[],
    signerAddresses: (j.signer_addresses ?? [j.signer_address]) as string[],
  }
}

// ── Audit log — returns Promise<void> so callers can handle failures ────
// (errors propagate; callers decide whether to await or fire-and-forget
// with an explicit .catch() — see usage at the two call sites below).
async function auditLog(params: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/internal/signing/audit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Internal-Secret': INTERNAL_SECRET },
    body: JSON.stringify(params),
    signal: AbortSignal.timeout(5000),
  })
  if (!res.ok) {
    throw new Error(`audit log HTTP ${res.status}`)
  }
}

function routerForChain(chainId: number): `0x${string}` {
  const ZERO = '0x0000000000000000000000000000000000000000' as `0x${string}`
  switch (chainId) {
    case 8453:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE ?? ZERO) as `0x${string}`
    case 84532:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA ?? ZERO) as `0x${string}`
    case 1:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ETH ?? ZERO) as `0x${string}`
    case 10:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_OPTIMISM ?? ZERO) as `0x${string}`
    case 42161:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ARBITRUM ?? ZERO) as `0x${string}`
    case 137:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_POLYGON ?? ZERO) as `0x${string}`
    case 56:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BNB ?? ZERO) as `0x${string}`
    case 43114:
      return (process.env.NEXT_PUBLIC_FEE_ROUTER_V4_AVALANCHE ?? ZERO) as `0x${string}`
    case 728126428:
      return (process.env.TRON_FEE_ROUTER_MAINNET ?? ZERO) as `0x${string}`
    default:
      return ZERO
  }
}

const CHAIN_NAMES: Record<number, string> = {
  1: 'ETHEREUM', 10: 'OPTIMISM', 56: 'BNB', 137: 'POLYGON',
  8453: 'BASE', 42161: 'ARBITRUM', 43114: 'AVALANCHE', 84532: 'BASE_SEPOLIA',
  728126428: 'TRON',
}
function chainName(id: number): string { return CHAIN_NAMES[id] ?? `CHAIN_${id}` }

// ── EIP-712 per chain ──────────────────────────────────────────────────────
// Sepolia: contratto deployato con domain V3 (name="FeeRouterV3", version="3")
//          e typehash V3 (token, amount) — 6 campi
// Mainnet: nuovo deploy con FeeRouterV4.sol → domain V4 e typehash V4
//          (tokenIn, tokenOut, amountIn) — 7 campi

const ORACLE_TYPES_V3 = {
  OracleApproval: [
    { name: 'sender',    type: 'address' },
    { name: 'recipient', type: 'address' },
    { name: 'token',     type: 'address' },
    { name: 'amount',    type: 'uint256' },
    { name: 'nonce',     type: 'bytes32' },
    { name: 'deadline',  type: 'uint256' },
  ],
} as const

const ORACLE_TYPES_V4 = {
  OracleApproval: [
    { name: 'sender',    type: 'address' },
    { name: 'recipient', type: 'address' },
    { name: 'tokenIn',   type: 'address' },
    { name: 'tokenOut',  type: 'address' },
    { name: 'amountIn',  type: 'uint256' },
    { name: 'nonce',     type: 'bytes32' },
    { name: 'deadline',  type: 'uint256' },
  ],
} as const

function getDomainConfig(chainId: number) {
  if (chainId === 84532) {
    return { name: 'FeeRouterV3' as const, version: '3' as const, isV3: true }
  }
  // M2/M1-B: a chain whose registry declares a V5/V6 router uses the bumped
  // EIP-712 domain (name="FeeRouterV6", version="6"). Same OracleApproval
  // struct as V4 — only the domain name/version (and bytes[] arity) differ.
  if (getRegistry(chainId)?.version === 'v6') {
    return { name: 'FeeRouterV6' as const, version: '6' as const, isV3: false }
  }
  return { name: 'FeeRouterV4' as const, version: '4' as const, isV3: false }
}

// ── M2: EIP-712 domain self-check ──────────────────────────────────────────
// Guards against an oracle↔contract version/arity drift (e.g. signing the V4
// domain for a freshly-deployed V6 router) that would otherwise brick 100% of
// payments silently. We compute the EIP-712 domain separator the oracle is
// signing under and compare it to the contract's on-chain domainSeparator().
const DOMAIN_SEP_ABI = [{
  name: 'domainSeparator', type: 'function', stateMutability: 'view',
  inputs: [], outputs: [{ name: '', type: 'bytes32' }],
}] as const

const EIP712_DOMAIN_TYPEHASH = keccak256(
  toBytes('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'),
)

function localDomainSeparator(
  name: string, version: string, chainId: number, verifyingContract: `0x${string}`,
): `0x${string}` {
  return keccak256(encodeAbiParameters(
    [{ type: 'bytes32' }, { type: 'bytes32' }, { type: 'bytes32' }, { type: 'uint256' }, { type: 'address' }],
    [EIP712_DOMAIN_TYPEHASH, keccak256(toBytes(name)), keccak256(toBytes(version)), BigInt(chainId), verifyingContract],
  ))
}

const _domainCache = new Map<string, { ok: boolean; expiresAt: number }>()
const DOMAIN_CACHE_TTL_MS = 5 * 60_000

// Returns null when OK (or undeterminable — fail-OPEN on RPC error to preserve
// availability), or an error string on a CONFIRMED mismatch (fail-CLOSED).
async function checkDomainBinding(
  chainId: number, contractAddr: `0x${string}`, name: string, version: string,
): Promise<string | null> {
  const localSep = localDomainSeparator(name, version, chainId, contractAddr).toLowerCase()
  const key = `${chainId}:${contractAddr.toLowerCase()}:${localSep}`
  const cached = _domainCache.get(key)
  if (cached && cached.expiresAt > Date.now()) {
    return cached.ok ? null : `EIP-712 domain mismatch for ${name}/${version} (cached)`
  }
  const rpcUrl = getRegistry(chainId)?.rpcUrl
  if (!rpcUrl) return null // cannot determine → do not block
  try {
    const client = createPublicClient({ transport: http(rpcUrl) })
    const data = encodeFunctionData({ abi: DOMAIN_SEP_ABI, functionName: 'domainSeparator' })
    const res = await client.call({ to: contractAddr, data })
    const onchain = (res.data ?? '0x').toLowerCase()
    const ok = onchain === localSep
    _domainCache.set(key, { ok, expiresAt: Date.now() + DOMAIN_CACHE_TTL_MS })
    return ok ? null
      : `EIP-712 domain mismatch: oracle signs ${name}/${version} but the deployed contract domainSeparator differs (version/arity drift)`
  } catch (err) {
    logger.warn('oracle/sign', 'domain self-check RPC failed (fail-open)', { err: String(err) })
    return null
  }
}

const EUR_RATES: Record<string, number> = {
  ETH: 2200, USDC: 0.92, USDT: 0.92, EURC: 1.0,
  CBBTC: 88000, WBTC: 88000, DEGEN: 0.003,
  BNB: 600, POL: 0.45, AVAX: 35, CELO: 0.75,
  OP: 2.5, USDB: 1.0, ARB: 1.1, BTCB: 88000, CUSD: 0.92,
  TRX: 0.12, USDD: 0.92,
}

const BLACKLIST = new Set([
  '0x722122df12d4e14e13ac3b6895a86e84145b6967',
  '0xd90e2f925da726b50c4ed8d0fb90ad053324f31b',
  '0xd96f2b1c14db8458374d9aca76e26c3950113463',
  '0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfba9d',
])

// ── POST ────────────────────────────────────────────────────────────────────
export async function POST(req: NextRequest) {
  try {
    // Per-IP rate limit. Max 10 sign requests per IP per minute.
    // Chosen because /api/oracle/sign is a heavy endpoint (calls backend
    // signing guard + AML check + EIP-712 signing); legitimate UX needs
    // are bounded by ~1 tx per 6s. 10/min gives ~6x headroom for retries
    // and network blips while throttling abuse before it reaches the
    // backend guard / AML stack.
    const clientIp = getClientIp(req)
    const rate = checkRateLimit(clientIp, {
      max: 10,
      windowMs: 60_000,
      key: 'oracle-sign',
    })
    if (!rate.allowed) {
      return NextResponse.json(
        {
          approved: false,
          error: 'RATE_LIMIT_EXCEEDED',
          rejectionReason: 'Too many signing requests. Try again later.',
          retry_after: rate.retryAfter,
        },
        {
          status: 429,
          headers: { 'Retry-After': String(rate.retryAfter ?? 60) },
        },
      )
    }

    // Shared Redis early gate (M5) — authoritative across instances, keyed on
    // the trusted client IP; runs before the heavy AML + EIP-712 signing work.
    const shared = await sharedRateLimit({
      bucket: 'oracle-sign', key: clientIp, max: 10, windowSeconds: 60,
    })
    if (!shared.allowed) {
      return NextResponse.json(
        {
          approved: false,
          error: 'RATE_LIMIT_EXCEEDED',
          rejectionReason: 'Too many signing requests. Try again later.',
          retry_after: shared.retryAfter,
        },
        {
          status: 429,
          headers: { 'Retry-After': String(shared.retryAfter ?? 60) },
        },
      )
    }

    const body = await req.json().catch(() => null)
    if (!body) return NextResponse.json({ error: 'Body JSON non valido' }, { status: 400 })

    const {
      sender,
      recipient,
      tokenIn     = '0x0000000000000000000000000000000000000000',
      tokenOut    = '0x0000000000000000000000000000000000000000',
      amountInWei,
      amountIn    = '0',
      symbol      = 'ETH',
      chainId     = 84532,
    } = body

    if (!sender || !recipient) {
      return NextResponse.json({ error: 'sender e recipient obbligatori' }, { status: 400 })
    }
    if (!amountInWei || amountInWei === '0') {
      return NextResponse.json({ error: 'amountInWei obbligatorio e > 0' }, { status: 400 })
    }
    if (ORACLE_SIGNER_MODE !== 'remote' && !ORACLE_PRIVATE_KEY) {
      return NextResponse.json({
        approved: false, riskLevel: 'BLOCKED',
        rejectionReason: 'Servizio Oracle non configurato. Aggiungi ORACLE_PRIVATE_KEY.',
      }, { status: 503 })
    }

    const senderN    = sender.toLowerCase()    as `0x${string}`
    const recipientN = recipient.toLowerCase() as `0x${string}`
    const tokenInN   = tokenIn.toLowerCase()   as `0x${string}`
    const tokenOutN  = tokenOut.toLowerCase()  as `0x${string}`
    const symUpper   = (symbol as string).toUpperCase()

    if (BLACKLIST.has(senderN) || BLACKLIST.has(recipientN)) {
      return NextResponse.json({
        approved: false, oracleSignature: '0x',
        oracleNonce: ('0x' + '0'.repeat(64)) as Hex,
        oracleDeadline: 0, paymentRef: '0x', fiscalRef: '0x',
        riskScore: 100, riskLevel: 'BLOCKED', jurisdiction: 'BLOCKED',
        rejectionReason: 'Transazione negata per policy di conformità AML.',
      })
    }

    const eurRate  = EUR_RATES[symUpper] ?? 1
    const eurValue = parseFloat(amountIn) * eurRate
    let riskScore  = 5
    if (eurValue > 50_000) riskScore = 35
    else if (eurValue > 10_000) riskScore = 20
    else if (eurValue > 5_000)  riskScore = 10
    let riskLevel = riskScore >= 80 ? 'BLOCKED' : riskScore >= 60 ? 'HIGH' : riskScore >= 30 ? 'MEDIUM' : 'LOW'

    // ── Backend AML check (screening + monitoring) ────────
    try {
      const amlResp = await fetch(`${BACKEND_URL}/api/v1/aml/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sender: senderN,
          recipient: recipientN,
          amount_eur: eurValue,
          chain_id: Number(chainId),
          token_symbol: symUpper,
        }),
        signal: AbortSignal.timeout(3000),
      })
      if (amlResp.ok) {
        const aml = await amlResp.json()
        if (!aml.approved) {
          logger.warn('oracle/sign', 'AML BLOCKED', { details: aml.details })
          return NextResponse.json({
            approved: false, oracleSignature: '0x',
            oracleNonce: ('0x' + '0'.repeat(64)) as Hex,
            oracleDeadline: 0, paymentRef: '0x', fiscalRef: '0x',
            riskScore: 100, riskLevel: 'BLOCKED', jurisdiction: 'BLOCKED',
            rejectionReason: `AML: ${aml.details}`,
          }, { status: 403 })
        }
        // Upgrade risk level if AML says higher
        if (aml.risk_level === 'high' && riskScore < 60) {
          riskScore = 60
          riskLevel = 'HIGH'
        } else if (aml.risk_level === 'medium' && riskScore < 30) {
          riskScore = 30
          riskLevel = 'MEDIUM'
        }
      }
    } catch (amlErr) {
      // AML service unreachable — log but don't block (local blacklist already checked)
      logger.warn('oracle/sign', 'AML service unreachable', { err: String(amlErr) })
    }

    let amountWei: bigint
    try { amountWei = BigInt(amountInWei) }
    catch { return NextResponse.json({ error: `amountInWei non valido: ${amountInWei}` }, { status: 400 }) }

    const nonce    = ('0x' + randomBytes(32).toString('hex')) as Hex
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 600) // 10 min (was 20 min)

    const paymentRef = keccak256(toHex(`PAY-${Date.now()}-${randomBytes(4).toString('hex')}`))
    const fiscalRef  = keccak256(toHex(`FISCAL-${symUpper}-${Date.now()}`))

    const contractAddr = routerForChain(Number(chainId))
    const ZERO = '0x0000000000000000000000000000000000000000'
    if (contractAddr === ZERO) {
      return NextResponse.json({
        approved: false, riskLevel: 'BLOCKED',
        rejectionReason: `Contratto FeeRouter non configurato su chainId=${chainId}.`,
        ...(ORACLE_DEBUG ? { _debug: { chainId, contractAddr } } : {}),
      }, { status: 503 })
    }

    // ── Signing Guard: backend nonce + parameter validation
    // (per-IP rate limit already applied at the top of POST)
    const guard = await signingGuardCheck({
      wallet: senderN,
      recipient: recipientN,
      tokenIn: tokenInN,
      amountInWei: amountInWei,
      nonce,
      deadline: Number(deadline),
      chainId: Number(chainId),
      ipAddress: clientIp,
      contractAddress: contractAddr,
    })

    if (!guard.allowed) {
      const account = ORACLE_PRIVATE_KEY ? privateKeyToAccount(ORACLE_PRIVATE_KEY) : null
      // Audit denied attempt — fire-and-forget so we don't add latency
      // to the rejection path, but .catch surfaces any failure to the
      // logger so it can't be silently lost.
      void auditLog({
        signer_address: account?.address ?? 'NOT_CONFIGURED',
        chain_id: Number(chainId),
        sender: senderN,
        recipient: recipientN,
        token_in: tokenInN,
        amount_in_wei: amountInWei,
        nonce,
        deadline: Number(deadline),
        approved: false,
        denial_reason: guard.reason,
        risk_score: riskScore,
        risk_level: riskLevel,
        ip_address: clientIp,
        user_agent: req.headers.get('user-agent'),
      }).catch(err => logger.error('oracle/sign', 'Audit log failed (denied)', { err: String(err) }))

      logger.warn('oracle/sign', 'BLOCKED', { reason: guard.reason })
      return NextResponse.json({
        approved: false, oracleSignature: '0x',
        oracleNonce: nonce, oracleDeadline: Number(deadline),
        paymentRef: '0x', fiscalRef: '0x',
        riskScore, riskLevel: 'BLOCKED',
        rejectionReason: `Signing guard: ${guard.reason}`,
      }, { status: 429 })
    }

    const { name, version, isV3 } = getDomainConfig(Number(chainId))

    const domain = {
      name,
      version,
      chainId: Number(chainId),
      verifyingContract: contractAddr,
    }

    // M2: refuse to sign if the oracle's EIP-712 domain doesn't match the
    // deployed contract (version/arity drift) — fail-closed instead of emitting
    // a signature every payment would reject.
    const domainErr = await checkDomainBinding(Number(chainId), contractAddr, name, version)
    if (domainErr) {
      logger.error('oracle/sign', 'DOMAIN BINDING MISMATCH', { domainErr, chainId: Number(chainId), contractAddr })
      return NextResponse.json({
        approved: false, riskLevel: 'BLOCKED',
        rejectionReason: `Errore di configurazione oracle: ${domainErr}`,
      }, { status: 503 })
    }

    const types   = isV3 ? ORACLE_TYPES_V3 : ORACLE_TYPES_V4
    const message = isV3
      ? { sender: senderN, recipient: recipientN, token: tokenInN, amount: amountWei, nonce, deadline }
      : { sender: senderN, recipient: recipientN, tokenIn: tokenInN, tokenOut: tokenOutN, amountIn: amountWei, nonce, deadline }

    // M1: sign via the backend KMS oracle signer (remote) or a local key.
    // `signatures` is the V5/V6 multisig array (ascending by signer); for a
    // single-signer oracle (V4) it is just [signature].
    let signature: Hex
    let signerAddress: string
    let signatures: Hex[]
    if (ORACLE_SIGNER_MODE === 'remote') {
      const digest = hashTypedData({ domain, types, primaryType: 'OracleApproval', message })
      const remote = await remoteSignDigest(digest)
      signature = remote.signature
      signerAddress = remote.signerAddress
      signatures = remote.signatures
    } else {
      const account = privateKeyToAccount(ORACLE_PRIVATE_KEY as Hex)
      signature = await account.signTypedData({
        domain, types, primaryType: 'OracleApproval', message,
      })
      signerAddress = account.address
      signatures = [signature]
    }

    const recovered = await recoverTypedDataAddress({
      domain, types, primaryType: 'OracleApproval', message, signature,
    })

    if (recovered.toLowerCase() !== signerAddress.toLowerCase()) {
      logger.error('oracle/sign', 'SELF-VERIFICA FALLITA', { recovered, expected: signerAddress })
      return NextResponse.json({
        approved: false, riskLevel: 'BLOCKED',
        rejectionReason: 'Errore interno: firma non verificabile.',
        ...(ORACLE_DEBUG ? { _debug: { recovered, expected: signerAddress } } : {}),
      }, { status: 500 })
    }

    // ── Audit log: record approved signature ───────────
    // Fire-and-forget to keep the signing response on its tight latency
    // SLA. .catch ensures any backend failure surfaces to the logger
    // instead of being silently lost.
    void auditLog({
      signer_address: signerAddress,
      chain_id: Number(chainId),
      sender: senderN,
      recipient: recipientN,
      token_in: tokenInN,
      amount_in_wei: amountInWei,
      nonce,
      deadline: Number(deadline),
      approved: true,
      risk_score: riskScore,
      risk_level: riskLevel,
      ip_address: clientIp,
      user_agent: req.headers.get('user-agent'),
    }).catch(err => logger.error('oracle/sign', 'Audit log failed (approved)', { err: String(err) }))

    return NextResponse.json({
      approved: true,
      oracleSignature: signature,
      oracleSignatures: signatures,   // V5/V6 multisig (bytes[]); [signature] for V4
      oracleNonce:     nonce,
      oracleDeadline:  Number(deadline),
      paymentRef,
      fiscalRef,
      riskScore,
      riskLevel,
      jurisdiction:    'EU_UNKNOWN',
      eurValue:        Math.round(eurValue * 100) / 100,
      isEurc:          symUpper === 'EURC',
      isSwap:          tokenInN !== tokenOutN,
      sourceChain:     chainName(Number(chainId)),
      gasless:         Number(chainId) !== 1,
      ...(ORACLE_DEBUG ? { _debug: {
        contractAddr,
        domainName:  name,
        domainVer:   version,
        typehash:    isV3 ? 'V3' : 'V4',
        amountWei:   amountWei.toString(),
        signer:      signerAddress,
        recovered,
        chainId:     Number(chainId),
      } } : {}),
    })

  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    logger.error('oracle/sign', 'unhandled error', { message })
    return NextResponse.json({
      approved: false, error: message, riskLevel: 'BLOCKED',
      rejectionReason: 'Errore interno Oracle: ' + message.slice(0, 100),
    }, { status: 500 })
  }
}

// ── GET — health check ──────────────────────────────────────────────────────
export async function GET() {
  // L1 — in production this endpoint leaked signer address, all router
  // addresses, domain config and env flags. Return only a liveness ping unless
  // ORACLE_DEBUG=1.
  if (!ORACLE_DEBUG) {
    return NextResponse.json({ status: 'online' })
  }

  const account = ORACLE_PRIVATE_KEY
    ? privateKeyToAccount(ORACLE_PRIVATE_KEY as Hex)
    : null

  const routers = {
    8453:      routerForChain(8453),
    84532:     routerForChain(84532),
    1:         routerForChain(1),
    10:        routerForChain(10),
    42161:     routerForChain(42161),
    137:       routerForChain(137),
    56:        routerForChain(56),
    43114:     routerForChain(43114),
    728126428: routerForChain(728126428),
  }

  const { keccak256: k256, encodeAbiParameters, parseAbiParameters } = await import('viem')
  function computeDomainHash(name: string, version: string, chainId: number, addr: string): string {
    try {
      const encoded = encodeAbiParameters(
        parseAbiParameters('bytes32, bytes32, bytes32, uint256, address'),
        [
          k256(new TextEncoder().encode('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')),
          k256(new TextEncoder().encode(name)),
          k256(new TextEncoder().encode(version)),
          BigInt(chainId),
          addr as `0x${string}`,
        ]
      )
      return k256(encoded)
    } catch { return 'errore calcolo' }
  }

  const ZERO = '0x0000000000000000000000000000000000000000'
  return NextResponse.json({
    status:        'online',
    version:       '4.8.0',
    configured:    !!ORACLE_PRIVATE_KEY,
    signerAddress: account?.address ?? 'NOT_CONFIGURED',
    routers,
    domainConfig: {
      84532:     { name: 'FeeRouterV3', version: '3', typehash: 'V3' },
      8453:      { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      1:         { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      10:        { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      42161:     { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      137:       { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      56:        { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      43114:     { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
      728126428: { name: 'FeeRouterV4', version: '4', typehash: 'V4' },
    },
    domainSeparatorHash: {
      84532: routers[84532] !== ZERO ? computeDomainHash('FeeRouterV3', '3', 84532, routers[84532]) : 'N/A',
      8453:  routers[8453]  !== ZERO ? computeDomainHash('FeeRouterV4', '4', 8453,  routers[8453])  : 'N/A — deploy needed',
    },
    envDebug: {
      NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA: process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE_SEPOLIA ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_BASE:         process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BASE         ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_ETH:          process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ETH          ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_OPTIMISM:     process.env.NEXT_PUBLIC_FEE_ROUTER_V4_OPTIMISM     ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_ARBITRUM:     process.env.NEXT_PUBLIC_FEE_ROUTER_V4_ARBITRUM     ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_POLYGON:      process.env.NEXT_PUBLIC_FEE_ROUTER_V4_POLYGON      ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_BNB:          process.env.NEXT_PUBLIC_FEE_ROUTER_V4_BNB          ? '✅' : '❌',
      NEXT_PUBLIC_FEE_ROUTER_V4_AVALANCHE:    process.env.NEXT_PUBLIC_FEE_ROUTER_V4_AVALANCHE    ? '✅' : '❌',
      TRON_FEE_ROUTER_MAINNET:                process.env.TRON_FEE_ROUTER_MAINNET                ? '✅' : '❌',
      ORACLE_PRIVATE_KEY:                     process.env.ORACLE_PRIVATE_KEY                     ? '✅' : '❌',
    },
  })
}