import { NextRequest, NextResponse }  from 'next/server'
import {
  keccak256, toHex, type Hex,
  recoverTypedDataAddress,
} from 'viem'
import { privateKeyToAccount } from 'viem/accounts'
import { randomBytes }         from 'crypto'
import { requireEnv }          from '@/lib/env'
import { getClientIp, checkRateLimit } from '@/lib/rateLimit'

// ── Config ─────────────────────────────────────────────────────────────────
const ORACLE_PRIVATE_KEY = process.env.ORACLE_PRIVATE_KEY as Hex | undefined
const BACKEND_URL = requireEnv('RPAGOS_BACKEND_URL')
// TEMP DEBUG — remove after verifying BACKEND_URL points to local in dev
console.log('[oracle/sign] BACKEND_URL =', BACKEND_URL)

// ── Signing Guard — pre-flight check via backend ───────────────────────────
async function signingGuardCheck(params: {
  wallet: string; recipient: string; tokenIn: string;
  amountInWei: string; nonce: string; deadline: number;
  chainId: number; ipAddress: string | null; contractAddress: string;
}): Promise<{ allowed: boolean; reason?: string }> {
  try {
    const resp = await fetch(`${BACKEND_URL}/api/internal/signing/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    console.error('[oracle/sign] Signing guard unreachable:', err)
    return { allowed: false, reason: 'guard_unavailable (fail-closed)' }
  }
}

// ── Audit log — fire-and-forget to backend ────────────────────────────────
function auditLog(params: Record<string, unknown>): void {
  fetch(`${BACKEND_URL}/api/internal/signing/audit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: AbortSignal.timeout(5000),
  }).catch(err => console.error('[oracle/sign] Audit log failed:', err))
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
  return { name: 'FeeRouterV4' as const, version: '4' as const, isV3: false }
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
    if (!ORACLE_PRIVATE_KEY) {
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
          console.warn('[oracle/sign] AML BLOCKED:', aml.details)
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
      console.warn('[oracle/sign] AML service unreachable:', amlErr)
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
        _debug: { chainId, contractAddr },
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
      // Audit denied attempt
      auditLog({
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
      })

      console.warn(`[oracle/sign] BLOCKED: ${guard.reason}`)
      return NextResponse.json({
        approved: false, oracleSignature: '0x',
        oracleNonce: nonce, oracleDeadline: Number(deadline),
        paymentRef: '0x', fiscalRef: '0x',
        riskScore, riskLevel: 'BLOCKED',
        rejectionReason: `Signing guard: ${guard.reason}`,
      }, { status: 429 })
    }

    const account = privateKeyToAccount(ORACLE_PRIVATE_KEY)
    const { name, version, isV3 } = getDomainConfig(Number(chainId))

    const domain = {
      name,
      version,
      chainId: Number(chainId),
      verifyingContract: contractAddr,
    }

    const types   = isV3 ? ORACLE_TYPES_V3 : ORACLE_TYPES_V4
    const message = isV3
      ? { sender: senderN, recipient: recipientN, token: tokenInN, amount: amountWei, nonce, deadline }
      : { sender: senderN, recipient: recipientN, tokenIn: tokenInN, tokenOut: tokenOutN, amountIn: amountWei, nonce, deadline }

    console.log('\n[oracle/sign] ═══ FIRMA ═══')
    console.log('  domain:     ', JSON.stringify(domain))
    console.log('  typehash:   ', isV3 ? 'V3 (token, amount)' : 'V4 (tokenIn, tokenOut, amountIn)')
    console.log('  sender:     ', senderN)
    console.log('  recipient:  ', recipientN)
    console.log('  amountWei:  ', amountWei.toString())
    console.log('  signerAddr: ', account.address)
    console.log('[oracle/sign] ════════════\n')

    const signature = await account.signTypedData({
      domain, types, primaryType: 'OracleApproval', message,
    })

    const recovered = await recoverTypedDataAddress({
      domain, types, primaryType: 'OracleApproval', message, signature,
    })

    if (recovered.toLowerCase() !== account.address.toLowerCase()) {
      console.error('[oracle/sign] ❌ SELF-VERIFICA FALLITA', { recovered, expected: account.address })
      return NextResponse.json({
        approved: false, riskLevel: 'BLOCKED',
        rejectionReason: 'Errore interno: firma non verificabile.',
        _debug: { recovered, expected: account.address },
      }, { status: 500 })
    }

    console.log('[oracle/sign] ✅ self-verifica OK —', recovered)

    // ── Audit log: record approved signature ───────────
    auditLog({
      signer_address: account.address,
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
    })

    return NextResponse.json({
      approved: true,
      oracleSignature: signature,
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
      _debug: {
        contractAddr,
        domainName:  name,
        domainVer:   version,
        typehash:    isV3 ? 'V3' : 'V4',
        amountWei:   amountWei.toString(),
        signer:      account.address,
        recovered,
        chainId:     Number(chainId),
      },
    })

  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.error('[oracle/sign] ❌ error:', message)
    return NextResponse.json({
      approved: false, error: message, riskLevel: 'BLOCKED',
      rejectionReason: 'Errore interno Oracle: ' + message.slice(0, 100),
    }, { status: 500 })
  }
}

// ── GET — health check ──────────────────────────────────────────────────────
export async function GET() {
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