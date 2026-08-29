/**
 * capture-mockups.ts — regenerate the two screenshots in components/landing/DeviceShowcase.tsx.
 *
 * ── Run it ──────────────────────────────────────────────────────────────────
 *
 *     cd apps/web
 *     npm i -D playwright && npx playwright install chromium     # one-off
 *     node scripts/capture-mockups.ts
 *
 * Node 22.6+ strips the types itself, so there is no build step. Playwright is
 * NOT a declared dependency of this workspace: the repo already keeps it
 * out-of-tree (see .claude/skills/verify/SKILL.md) and adding it would rewrite a
 * 1 MB lockfile shared with several checkouts. If the import fails, the message
 * below tells you the one command to run.
 *
 * ── Why a script and not two files someone once dragged in ──────────────────
 *
 * The section's claim is that the site shows the real product. That claim decays
 * the moment the UI moves and the PNGs do not. Everything here drives the REAL
 * routes — /en/app/payments and /pay/{id} — against a stub backend, so
 * regenerating after a UI change is one command rather than an afternoon.
 *
 * Nothing in this file may become a drawing of the product. If a capture cannot
 * be taken, fix the capture; do not hand-author a facsimile.
 *
 * ── What it draws from ──────────────────────────────────────────────────────
 *
 * The rig is the one documented in apps/web/.claude/skills/verify/SKILL.md: a
 * plain node http stub on 127.0.0.1:4545, a forged next-auth cookie, and
 * `next dev` pointed at the stub. Both surfaces reach it through a Next server
 * route — the dashboard via /api/backend/{path}, the checkout via
 * /api/pay/{intentId} — so one stub covers every backend read.
 *
 * The chain is faked separately, at the RPC layer. See "A deterministic fake
 * chain" below for why an injected wallet alone is not enough.
 *
 * ── Truthfulness rules these fixtures keep ──────────────────────────────────
 *
 *   - No real merchant, address, intent id, amount or API key, ever.
 *   - No aggregate figure is authored anywhere. /en/app/payments carries no
 *     metric cards, which is one reason it is the route captured rather than
 *     the /app home. (The home also renders a "Total balance" card, and RSends
 *     is non-custodial — it holds no funds, so there is no balance to show.)
 *   - USDC and USDT on Base only. Both are in the backend token registry for
 *     chain 8453 (services/backend/app/tokens/registry.py); EURC is in no
 *     registry at all and create-intent rejects it.
 */

import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = resolve(HERE, '..')
const OUT_DIR = resolve(WEB_ROOT, 'public/mockups')

const STUB_PORT = 4545
const WEB_PORT = 3100
const WEB_ORIGIN = `http://127.0.0.1:${WEB_PORT}`

/* ────────────────────────────────────────────────────────────────────────────
 * Capture geometry. These must stay in step with the width/height props in
 * components/landing/DeviceShowcase.tsx — those are what reserve the box, so a
 * ratio change here without a change there reintroduces layout shift.
 * ──────────────────────────────────────────────────────────────────────────── */
const SHOTS = {
  dashboard: { route: '/en/app/payments', width: 1440, height: 900, scale: 2, file: 'dashboard.png' },
  // 390x844 is the phone real payers arrive on. Note this is NOT in tension
  // with the 500x720 rendering floor in docs/INTEGRATION_CONTRACT.md: that
  // floor is the smallest viewport the checkout promises to survive, not a
  // smallest capture size. Capture at the real width; never capture narrow and
  // scale up.
  // 390 wide is the phone real payers arrive on. 750 rather than the 844 the
  // device reports: 844 is the whole screen, and the browser spends ~90 of it
  // on its own chrome, so 750 is what the page actually gets. Note this is NOT
  // in tension with the 500x720 rendering floor in docs/INTEGRATION_CONTRACT.md
  // — that floor is the smallest viewport the checkout promises to survive, not
  // a smallest capture size. Capture at the real width; never capture narrow
  // and scale up.
  pay: { route: '/pay/:intentId', width: 390, height: 750, scale: 3, file: 'pay.png' },
} as const

/* ────────────────────────────────────────────────────────────────────────────
 * FIXTURE — every value the screenshots show. One object so the committed
 * demo data is reviewable in one place.
 * ──────────────────────────────────────────────────────────────────────────── */
const NOW = Date.now()
const HOURS = (n: number) => new Date(NOW - n * 3_600_000).toISOString()
const IN_HOURS = (n: number) => new Date(NOW + n * 3_600_000).toISOString()
const IN_MINUTES = (n: number) => new Date(NOW + n * 60_000).toISOString()

/** Obviously synthetic, in the 0x0000…000N style. Never a real payee. */
const addr = (n: number) => `0x${n.toString(16).padStart(40, '0')}`
const txh = (seed: string) => `0x${seed.repeat(64).slice(0, 64)}`

const ORG_ID = 'org_demo'
const PAY_INTENT_ID = 'pi_0000000000000000000000000000abcd'

const FIXTURE = {
  org: {
    id: ORG_ID,
    name: 'Northwind Supply',
    role: 'admin',
    settlement_wallet: addr(1),
  },

  /** Seven invoices, mixed statuses, 120–1900 in token units, last 48 hours. */
  payments: [
    { intent_id: 'pi_0000000000000000000000000000001a', amount: 1_900, currency: 'USDC', chain: 'base', status: 'paid', recipient: addr(1), tx_hash: txh('a'), matched_tx_hash: txh('a'), created_at: HOURS(2), expires_at: IN_HOURS(22) },
    { intent_id: 'pi_0000000000000000000000000000002b', amount: 480, currency: 'USDT', chain: 'base', status: 'pending', recipient: addr(1), tx_hash: null, matched_tx_hash: null, created_at: HOURS(5), expires_at: IN_HOURS(19) },
    { intent_id: 'pi_0000000000000000000000000000003c', amount: 1_240, currency: 'USDC', chain: 'base', status: 'paid', recipient: addr(1), tx_hash: txh('b'), matched_tx_hash: txh('b'), created_at: HOURS(9), expires_at: IN_HOURS(15) },
    { intent_id: 'pi_0000000000000000000000000000004d', amount: 320, currency: 'USDC', chain: 'base', status: 'expired', recipient: addr(1), tx_hash: null, matched_tx_hash: null, created_at: HOURS(20), expires_at: HOURS(2) },
    { intent_id: 'pi_0000000000000000000000000000005e', amount: 875, currency: 'USDT', chain: 'base', status: 'paid', recipient: addr(1), tx_hash: txh('c'), matched_tx_hash: txh('c'), created_at: HOURS(26), expires_at: HOURS(2) },
    { intent_id: 'pi_0000000000000000000000000000006f', amount: 120, currency: 'USDC', chain: 'base', status: 'pending', recipient: addr(1), tx_hash: null, matched_tx_hash: null, created_at: HOURS(31), expires_at: IN_HOURS(4) },
    { intent_id: 'pi_00000000000000000000000000000070', amount: 1_450, currency: 'USDC', chain: 'base', status: 'paid', recipient: addr(1), tx_hash: txh('d'), matched_tx_hash: txh('d'), created_at: HOURS(44), expires_at: HOURS(20) },
  ],

  /**
   * The checkout intent. Base Sepolia, because that is the chain the product
   * actually runs on today and the chain the explorer link resolves against.
   * `fee` is supplied so the checkout never has to quote it on-chain.
   */
  payIntent: {
    intent_id: PAY_INTENT_ID,
    status: 'pending',
    // The checkout counts down in MM:SS, so a multi-hour window renders as
    // "357:57" and reads as a bug. Minutes is also what a real invoice gets.
    expires_at: IN_MINUTES(28),
    amount: 240,
    currency: 'USDC',
    chain: 'BASE_SEPOLIA',
    merchant_name: 'Northwind Supply',
    tx_hash: null,
    onchain: {
      invoiceId: txh('e'),
      merchant: addr(1),
      token: '0x036CbD53842c5426634e7929541eC2318f3dCF7e', // USDC, Base Sepolia
      amount: '240000000',
      fee: '600000',
      total: '240600000',
      maxFee: '600000',
      chainId: 84532,
      router: addr(2),
      decimals: 6,
      isNative: false,
      routerVersion: 1,
      permitType: null,
    },
  },

  /** The payer's wallet in the checkout capture. Synthetic, like everything else. */
  payer: addr(0xbeef),
  /**
   * The transaction the capture "makes". Fixed, so re-running produces the same
   * image, and not a hash from any chain — resolving it on BaseScan finds
   * nothing, which is the correct outcome for demo data.
   */
  payTxHash: '0x7b1c4a09e3d5f28c6b90ad4172e8c3f5d016b7a4e92c85df3016a7b4c2e9d580',
} as const

/* ────────────────────────────────────────────────────────────────────────────
 * Stub backend
 * ──────────────────────────────────────────────────────────────────────────── */

function json(res: ServerResponse, body: unknown, status = 200) {
  const payload = JSON.stringify(body)
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) })
  res.end(payload)
}

function startStub(): Promise<{ close: () => Promise<void>; settle: () => void }> {
  // The checkout does not stop at "mined": once the payer's transaction is
  // on-chain it polls the backend until the merchant's record catches up, and
  // only then shows the completed card. So the stub has to do what the indexer
  // does — flip the intent to paid — or the capture sits on "Updating the
  // merchant's records" forever. `settle()` is that flip.
  let settled = false

  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const path = (req.url ?? '').split('?')[0]

    if (path === '/api/v1/user/onboarding') {
      return json(res, {
        consents_current: true,
        age_attested: true,
        email_verified: true,
        onboarding_status: 'company_submitted',
        approval_status: 'approved',
      })
    }

    if (path === '/api/v1/organizations') {
      return json(res, { organizations: [FIXTURE.org], active_org_id: FIXTURE.org.id })
    }

    if (path === '/api/v1/user/org/payment-intents') {
      return json(res, {
        total: FIXTURE.payments.length,
        page: 1,
        per_page: 20,
        records: FIXTURE.payments,
      })
    }

    if (path.startsWith('/api/v1/public/payment-intent/')) {
      return json(res, settled
        ? { ...FIXTURE.payIntent, status: 'paid', tx_hash: FIXTURE.payTxHash }
        : FIXTURE.payIntent)
    }

    // Everything else the /app shell probes (dormant custodial listeners, etc.)
    // answers empty rather than 404, so the console stays quiet in the capture.
    return json(res, {}, 200)
  })

  return new Promise(resolveReady => {
    server.listen(STUB_PORT, '127.0.0.1', () => {
      console.log(`  stub backend    http://127.0.0.1:${STUB_PORT}`)
      resolveReady({
        close: () => new Promise<void>(done => server.close(() => done())),
        settle: () => { settled = true },
      })
    })
  })
}

/* ────────────────────────────────────────────────────────────────────────────
 * Next dev server
 * ──────────────────────────────────────────────────────────────────────────── */

async function startWeb(): Promise<ChildProcess> {
  const child = spawn('npx', ['next', 'dev', '-p', String(WEB_PORT)], {
    cwd: WEB_ROOT,
    env: {
      ...process.env,
      RPAGOS_BACKEND_URL: `http://127.0.0.1:${STUB_PORT}`,
      NEXT_PUBLIC_RPAGOS_BACKEND_URL: `http://127.0.0.1:${STUB_PORT}`,
      NEXTAUTH_URL: WEB_ORIGIN,
      // /pay imports RainbowKit, which throws `No projectId found` at module
      // load with an empty value. Any non-empty string gets past it;
      // WalletConnect itself is unused here. See CLAUDE.md.
      NEXT_PUBLIC_WC_PROJECT_ID: process.env.NEXT_PUBLIC_WC_PROJECT_ID || 'capture-mockups-local',
      NEXT_PUBLIC_TARGET_CHAIN_ID: '84532',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  child.stderr?.on('data', d => process.stderr.write(`  [next] ${d}`))

  await new Promise<void>((ready, fail) => {
    const timer = setTimeout(() => fail(new Error('next dev did not become ready in 120s')), 120_000)
    child.stdout?.on('data', (d: Buffer) => {
      if (/Ready in|started server on/i.test(d.toString())) {
        clearTimeout(timer)
        ready()
      }
    })
    child.on('exit', code => {
      clearTimeout(timer)
      fail(new Error(`next dev exited early with code ${code}`))
    })
  })

  console.log(`  next dev        ${WEB_ORIGIN}`)
  return child
}

/* ────────────────────────────────────────────────────────────────────────────
 * Forged session — the /app routes are behind getServerSession + the
 * onboarding gate. next-auth signs its own cookie, so we borrow the app's
 * encoder and the local NEXTAUTH_SECRET rather than reimplementing the JWE.
 * ──────────────────────────────────────────────────────────────────────────── */

async function sessionCookie() {
  const webRequire = createRequire(resolve(WEB_ROOT, 'package.json'))
  const { encode } = webRequire('next-auth/jwt')
  const secret = process.env.NEXTAUTH_SECRET
  if (!secret) {
    throw new Error('NEXTAUTH_SECRET is unset. Run with the one from apps/web/.env.local.')
  }
  const value = await encode({
    token: {
      sub: 'user_capture',
      name: 'Demo',
      email: 'demo@example.test',
      access_token: 'stub-access-token',
    },
    secret,
    maxAge: 3600,
  })
  // No __Secure- prefix: the capture runs over plain http on 127.0.0.1.
  return { name: 'next-auth.session-token', value, domain: '127.0.0.1', path: '/' }
}

/* ────────────────────────────────────────────────────────────────────────────
 * A deterministic fake chain.
 *
 * The confirmation state is the point of the /pay capture — it is the moment
 * that shows the product worked — and it is only reachable after a transaction
 * mines. Reaching it needs BOTH halves of wagmi, which do not share a path:
 *
 *   - WRITES and the account go through the connector, i.e. window.ethereum.
 *     That is the injected provider below.
 *   - READS (quoteFee, allowance, balanceOf, and the receipt poll) go through
 *     the configured http transport — for Base Sepolia that is
 *     https://sepolia.base.org (app/providers-wallet-stack.tsx). Injecting a
 *     provider does nothing for those, which is why the first attempt at this
 *     capture sat on "Not enough USDC in this wallet": the balance read was
 *     answered by the real network, for an address that holds nothing.
 *
 * So the RPC endpoint is intercepted too. Nothing here touches a real chain and
 * nothing is signed. The transaction is fictional and its hash is obviously so.
 * ──────────────────────────────────────────────────────────────────────────── */

const CHAIN_ID_HEX = '0x14a34' // 84532, Base Sepolia
const BLOCK_HASH = `0x${'1'.repeat(64)}`
const MAX_UINT = `0x${'f'.repeat(64)}`

/** ABI-encode a single uint256 return value. */
const uint256 = (v: bigint | number) => `0x${BigInt(v).toString(16).padStart(64, '0')}`

/** The three ERC-20 reads the checkout makes before it will let anyone pay. */
const ERC20_READS: Record<string, string> = {
  '0xdd62ed3e': MAX_UINT, // allowance(address,address) — so no approve step
  '0x70a08231': MAX_UINT, // balanceOf(address)
  '0x7ecebe00': uint256(0), // nonces(address)
}

/**
 * wagmi batches every read through Multicall3.aggregate3, so in practice the
 * ONLY selector that ever arrives is 0x82ad56cb and the individual reads are
 * buried in its argument. Answering the outer call with a bare uint256 (which
 * is what the first version of this did) decodes as a failed batch, and the
 * checkout correctly reports the network as unreachable.
 *
 * viem is borrowed from the app rather than reimplemented: the encoding has to
 * match what the page decodes with, and there is exactly one way to be sure.
 */
const MULTICALL3_AGGREGATE3 = '0x82ad56cb'
const viem = createRequire(resolve(WEB_ROOT, 'package.json'))('viem') as typeof import('viem')

const AGGREGATE3_INPUT = [{
  type: 'tuple[]',
  components: [
    { name: 'target', type: 'address' },
    { name: 'allowFailure', type: 'bool' },
    { name: 'callData', type: 'bytes' },
  ],
}] as const
const AGGREGATE3_OUTPUT = [{
  type: 'tuple[]',
  components: [
    { name: 'success', type: 'bool' },
    { name: 'returnData', type: 'bytes' },
  ],
}] as const

/** Answer one contract read. `fallbackValue` covers quoteFee, whose return is
 *  a single uint256 like the rest. */
function answerCall(callData: string, fallbackValue: bigint): string {
  return ERC20_READS[callData.slice(0, 10).toLowerCase()] ?? uint256(fallbackValue)
}

function answerEthCall(data: string, fallbackValue: bigint): string {
  if (data.slice(0, 10).toLowerCase() !== MULTICALL3_AGGREGATE3) {
    return answerCall(data, fallbackValue)
  }
  const [calls] = viem.decodeAbiParameters(
    AGGREGATE3_INPUT,
    `0x${data.slice(10)}` as `0x${string}`,
  ) as unknown as [Array<{ target: string; allowFailure: boolean; callData: string }>]

  return viem.encodeAbiParameters(
    AGGREGATE3_OUTPUT,
    [calls.map(c => ({
      success: true,
      returnData: answerCall(c.callData, fallbackValue) as `0x${string}`,
    }))] as never,
  )
}

function fakeReceipt(txHash: string, payer: string, router: string) {
  return {
    transactionHash: txHash,
    transactionIndex: '0x0',
    blockHash: BLOCK_HASH,
    blockNumber: '0x10',
    from: payer,
    to: router,
    cumulativeGasUsed: '0x5208',
    gasUsed: '0x5208',
    effectiveGasPrice: '0x3b9aca00',
    contractAddress: null,
    logs: [],
    logsBloom: `0x${'0'.repeat(512)}`,
    status: '0x1',
    type: '0x2',
  }
}

/**
 * Answer the JSON-RPC the read transport sends. `feeBaseUnits` is the reply to
 * any eth_call that is not one of the three ERC-20 reads — in practice that is
 * quoteFee(token, amount), whose return is a single uint256.
 */
function rpcReply(method: string, params: unknown[], ctx: {
  txHash: string
  payer: string
  router: string
  feeBaseUnits: bigint
}): unknown {
  switch (method) {
    case 'eth_chainId': return CHAIN_ID_HEX
    case 'net_version': return String(parseInt(CHAIN_ID_HEX, 16))
    case 'eth_blockNumber': return '0x10'
    case 'eth_gasPrice':
    case 'eth_maxPriorityFeePerGas': return '0x3b9aca00'
    case 'eth_estimateGas': return '0x5208'
    case 'eth_getBalance': return MAX_UINT
    case 'eth_getTransactionCount': return '0x1'
    case 'eth_getLogs': return []
    case 'eth_getTransactionReceipt': return fakeReceipt(ctx.txHash, ctx.payer, ctx.router)
    case 'eth_getTransactionByHash':
      return {
        hash: ctx.txHash, blockNumber: '0x10', blockHash: BLOCK_HASH,
        from: ctx.payer, to: ctx.router, value: '0x0', input: '0x',
        nonce: '0x1', transactionIndex: '0x0', type: '0x2', gas: '0x5208',
      }
    case 'eth_getBlockByNumber':
    case 'eth_getBlockByHash':
      return {
        number: '0x10', hash: BLOCK_HASH, parentHash: `0x${'0'.repeat(64)}`,
        timestamp: `0x${Math.floor(Date.now() / 1000).toString(16)}`,
        baseFeePerGas: '0x7', gasLimit: '0x1c9c380', gasUsed: '0x5208',
        miner: `0x${'0'.repeat(40)}`, transactions: [], difficulty: '0x0',
        totalDifficulty: '0x0', extraData: '0x', size: '0x0',
        stateRoot: `0x${'0'.repeat(64)}`, receiptsRoot: `0x${'0'.repeat(64)}`,
        transactionsRoot: `0x${'0'.repeat(64)}`, sha3Uncles: `0x${'0'.repeat(64)}`,
        logsBloom: `0x${'0'.repeat(512)}`, uncles: [], nonce: '0x0', mixHash: `0x${'0'.repeat(64)}`,
      }
    case 'eth_call':
      return answerEthCall(
        String((params?.[0] as { data?: string })?.data ?? ''),
        ctx.feeBaseUnits,
      )
    default: return null
  }
}

/**
 * The connector half: an injected provider that is already connected, already
 * on Base Sepolia, and returns a fixed hash when asked to send. wagmi
 * reconnects to it on mount (reconnectOnMount is on in CheckoutClient), so the
 * capture never has to drive the wallet-picker modal.
 */
function walletInitScript(payer: string, txHash: string) {
  return `(() => {
    const PAYER = ${JSON.stringify(payer)};
    const CHAIN = ${JSON.stringify(CHAIN_ID_HEX)};
    const TX = ${JSON.stringify(txHash)};

    const handlers = {
      eth_chainId: () => CHAIN,
      net_version: () => String(parseInt(CHAIN, 16)),
      eth_accounts: () => [PAYER],
      eth_requestAccounts: () => [PAYER],
      eth_sendTransaction: () => TX,
      wallet_switchEthereumChain: () => null,
    };

    const provider = {
      isMetaMask: true,
      request: async ({ method, params }) => {
        const h = handlers[method];
        if (!h) throw Object.assign(new Error('unsupported: ' + method), { code: 4200 });
        return h(params);
      },
      on: () => provider,
      removeListener: () => provider,
    };

    window.ethereum = provider;

    // wagmi's injected connector finds a wallet either on window.ethereum or
    // through EIP-6963. Announce on both, and re-announce on request, because
    // the page may ask after this script has already run.
    const detail = Object.freeze({
      info: { uuid: '00000000-0000-4000-8000-000000000000', name: 'Demo Wallet', icon: 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E', rdns: 'test.capture.wallet' },
      provider,
    });
    const announce = () => window.dispatchEvent(new CustomEvent('eip6963:announceProvider', { detail }));
    window.addEventListener('eip6963:requestProvider', announce);
    announce();
  })()`
}

/* ────────────────────────────────────────────────────────────────────────────
 * Capture
 * ──────────────────────────────────────────────────────────────────────────── */

async function main() {
  let chromium
  try {
    ;({ chromium } = await import('playwright'))
  } catch {
    console.error(
      'playwright is not installed.\n\n' +
        '  cd apps/web && npm i -D playwright && npx playwright install chromium\n',
    )
    process.exit(1)
  }

  await mkdir(OUT_DIR, { recursive: true })
  console.log('capture-mockups')

  const stub = await startStub()
  const web = await startWeb()
  const browser = await chromium.launch()

  try {
    const cookie = await sessionCookie()

    // ── 1. The merchant surface, on a laptop ──
    {
      const ctx = await browser.newContext({
        viewport: { width: SHOTS.dashboard.width, height: SHOTS.dashboard.height },
        deviceScaleFactor: SHOTS.dashboard.scale,
        colorScheme: 'light',
        // Nothing may be caught mid-fade: the capture has to be the settled
        // frame, or the screenshot shows a half-animated page forever.
        reducedMotion: 'reduce',
      })
      await ctx.addCookies([cookie])
      const page = await ctx.newPage()
      // NOT networkidle: the dashboard polls on an interval, so the network
      // never goes quiet and the wait would always time out. Wait for real rows
      // instead — an empty table is a silent failure, and a timer would hide it.
      await page.goto(`${WEB_ORIGIN}${SHOTS.dashboard.route}`, { waitUntil: 'domcontentloaded' })
      await page.waitForSelector('table tbody tr', { timeout: 90_000 })
      await page.screenshot({ path: resolve(OUT_DIR, SHOTS.dashboard.file) })
      console.log(`  wrote           public/mockups/${SHOTS.dashboard.file}`)
      await ctx.close()
    }

    // ── 2. The payer surface, on a phone ──
    {
      const ctx = await browser.newContext({
        viewport: { width: SHOTS.pay.width, height: SHOTS.pay.height },
        deviceScaleFactor: SHOTS.pay.scale,
        colorScheme: 'light',
        reducedMotion: 'reduce',
        isMobile: true,
        hasTouch: true,
      })
      await ctx.addInitScript(walletInitScript(FIXTURE.payer, FIXTURE.payTxHash))

      // The read transport. Base Sepolia resolves to sepolia.base.org here
      // because no ALCHEMY_KEY is set; the alchemy pattern is routed too so the
      // capture behaves the same on a machine that has one.
      const rpcCtx = {
        txHash: FIXTURE.payTxHash,
        payer: FIXTURE.payer,
        router: FIXTURE.payIntent.onchain.router,
        feeBaseUnits: BigInt(FIXTURE.payIntent.onchain.fee),
      }
      // Regex, not a glob: Playwright's glob has no scheme wildcard, and a
      // pattern that silently matches nothing looks exactly like a working
      // interception until the checkout says the wallet is empty.
      for (const pattern of [/\.base\.org\//, /\.g\.alchemy\.com\//]) {
        await ctx.route(pattern, async route => {
          const body = route.request().postDataJSON()
          const answer = (one: { id?: unknown; method: string; params?: unknown[] }) => {
            const result = rpcReply(one.method, one.params ?? [], rpcCtx)
            // CAPTURE_DEBUG=1 prints every read. Worth keeping: when this rig
            // breaks it breaks silently, as a checkout that just will not
            // advance, and the selector log is what says which read is wrong.
            if (process.env.CAPTURE_DEBUG) {
              const data = String((one.params?.[0] as { data?: string })?.data ?? '')
              const selector = one.method === 'eth_call' ? ` ${data.slice(0, 10)}` : ''
              console.log(`  [rpc] ${one.method}${selector} -> ${JSON.stringify(result)?.slice(0, 80)}`)
            }
            return { jsonrpc: '2.0', id: one.id ?? 1, result }
          }
          await route.fulfill({
            contentType: 'application/json',
            body: JSON.stringify(Array.isArray(body) ? body.map(answer) : answer(body)),
          })
        })
      }

      const page = await ctx.newPage()
      page.on('console', m => {
        if (m.type() === 'error') console.log(`  [pay console] ${m.text().slice(0, 160)}`)
      })
      await page.goto(`${WEB_ORIGIN}/pay/${PAY_INTENT_ID}`, { waitUntil: 'domcontentloaded' })
      await capturePayConfirmation(page, stub.settle)
      await page.screenshot({ path: resolve(OUT_DIR, SHOTS.pay.file) })
      console.log(`  wrote           public/mockups/${SHOTS.pay.file}`)
      await ctx.close()
    }
  } finally {
    await browser.close()
    web.kill('SIGTERM')
    await stub.close()
  }

  console.log(
    '\nVerify AVIF negotiation against a production build (next/image picks the\n' +
      'format per request, so there is nothing to look for in .next):\n\n' +
      "  npm run build && npm start &\n" +
      "  curl -sI -H 'Accept: image/avif,image/webp,*/*' \\\n" +
      "    'http://localhost:3000/_next/image?url=%2Fmockups%2Fdashboard.png&w=1920&q=75' | grep -i content-type\n",
  )
}

/**
 * Drive the checkout from "connect" to the confirmation card. Kept in one
 * function because it is the fragile part: it depends on the checkout's button
 * copy, and it should fail loudly rather than screenshot a half-finished flow.
 */
async function capturePayConfirmation(page: import('playwright').Page, settle: () => void) {
  // The wallet reconnects on mount, so the pay CTA appears without anyone
  // touching the wallet-picker modal. Waiting for the button by name is also
  // the balance assertion: while the read transport is answering wrongly the
  // checkout shows "Not enough USDC in this wallet" and no CTA at all.
  const payButton = page.getByRole('button', { name: /^pay\b/i }).first()
  try {
    await payButton.waitFor({ state: 'visible', timeout: 60_000 })
  } catch (err) {
    // What the checkout says is the diagnosis. Print it rather than making the
    // next person re-run this blind.
    console.error('\n  checkout never offered a pay button. It said:\n')
    console.error(`  ${(await page.locator('body').innerText()).replace(/\n+/g, '\n  ')}\n`)
    throw err
  }
  await payButton.click()

  // Wait for the transaction to mine, THEN let the backend catch up — the same
  // order the real system runs in, and the reason the card can be trusted.
  await page.getByText(/confirmed on-chain/i).first().waitFor({ state: 'visible', timeout: 60_000 })
  settle()

  // The success card. Fail rather than screenshot a spinner: a half-finished
  // flow in the shop window is worse than no section.
  try {
    await page.getByText(/payment (confirmed|complete)/i).first().waitFor({
      state: 'visible',
      timeout: 60_000,
    })
  } catch (err) {
    console.error('\n  the payment never confirmed. The checkout said:\n')
    console.error(`  ${(await page.locator('body').innerText()).replace(/\n+/g, '\n  ')}\n`)
    throw err
  }
  // One frame for the card to settle; reducedMotion means there is no fade to
  // wait out, only layout.
  await page.waitForTimeout(500)
}

main().catch(err => {
  console.error(err)
  process.exit(1)
})
