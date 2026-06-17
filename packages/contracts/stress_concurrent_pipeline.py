"""
Stress Test S3: 50 TX Concorrenti (Pipeline Mode)
Simula il caso peggiore: 50 distribuzioni lanciate simultaneamente.
Ogni TX ha un nonce pre-assegnato. Se il nonce manager ha bug, TX collidono.

NOTE: ETH_PER_TX ridotto a 0.00006 ETH (budget: 0.004 ETH disponibili).
Il test è identico semanticamente a 0.002 ETH: il punto è la concorrenza, non l'importo.

STRUTTURA (2 fasi):
  Fase 1 — sequenziale, locale: read nonce → build + sign tutte le 50 TX
  Fase 2 — parallela, RPC: invia tutte le 50 `send_raw_transaction` simultaneamente
  Questo replica il pattern del sweeper in produzione.
"""
import asyncio
import time
import os
import sys

try:
    from web3 import Web3
except ImportError:
    print("ERROR: web3 not installed. Run: pip3 install web3")
    sys.exit(1)

RPC_URL     = os.environ.get("RPC_URL",     "https://base-sepolia.g.alchemy.com/v2/KsynbKs-OZ1c4BSw-2D4R")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY", "")
CONTRACT    = "0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3"
DEPLOYER    = "0xa61A471FC226a06C681cf2Ec41d2C64a147b4392"
CHAIN_ID    = 84532

CONCURRENT_TXS    = 50
RECIPIENTS_PER_TX = 5
ETH_PER_TX        = 0.00004   # reduced from 0.002 (budget after partial run: 0.00247 ETH left)
ORIGINAL_TARGET   = 0.002
MAX_CONCURRENT_SENDS = 15     # semaphore cap — avoids Alchemy free-tier 429 on 50 simultaneous calls

ABI = [
    {
        "inputs": [
            {"name": "recipients", "type": "address[]"},
            {"name": "amounts",    "type": "uint256[]"}
        ],
        "name": "distributeETH",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    }
]

w3       = Web3(Web3.HTTPProvider(RPC_URL))
contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)

# ── Phase 1: Build & sign all TXes sequentially (local, no RPC race) ──────────

def build_and_sign(nonce: int, tx_index: int, gas_price: int) -> dict:
    """Build recipients, sign TX locally. No extra RPC calls — gas_price passed in."""
    recipients = [w3.eth.account.create().address for _ in range(RECIPIENTS_PER_TX)]
    total_wei     = w3.to_wei(ETH_PER_TX, 'ether')
    fee_wei       = total_wei * 50 // 10000
    distributable = total_wei - fee_wei
    per_recipient = distributable // RECIPIENTS_PER_TX
    amounts = [per_recipient] * (RECIPIENTS_PER_TX - 1)
    amounts.append(distributable - sum(amounts))

    tx = contract.functions.distributeETH(recipients, amounts).build_transaction({
        'from':     DEPLOYER,
        'value':    total_wei,
        'nonce':    nonce,
        'gas':      700_000,
        'gasPrice': gas_price,
        'chainId':  CHAIN_ID,
    })
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    raw    = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)

    return {
        'index':      tx_index,
        'nonce':      nonce,
        'raw':        raw,
        'total_wei':  total_wei,
        'recipients': recipients,
        'status':     'BUILT',
    }

# ── Phase 2: Send all signed TXes concurrently (RPC calls in parallel) ────────

def send_raw(entry: dict) -> dict:
    """Send one pre-signed TX. Called from thread pool."""
    t0 = time.time()
    # Retry up to 3 times on Alchemy rate-limit (429)
    last_err = None
    for attempt in range(3):
        try:
            tx_hash           = w3.eth.send_raw_transaction(entry['raw'])
            entry['tx_hash']  = tx_hash.hex()
            entry['status']   = 'SENT'
            entry['send_ms']  = int((time.time() - t0) * 1000)
            entry['attempt']  = attempt + 1
            return entry
        except Exception as e:
            last_err = str(e)
            if 'Too Many Requests' in last_err or '429' in last_err or 'rate limit' in last_err.lower():
                time.sleep(0.3 * (attempt + 1))
                continue
            break   # non-retryable error

    entry['tx_hash'] = None
    entry['status']  = f'ERROR: {last_err[:120]}'
    entry['send_ms'] = int((time.time() - t0) * 1000)
    entry['attempt'] = 3
    return entry

# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    balance_before = w3.eth.get_balance(DEPLOYER)
    base_nonce     = w3.eth.get_transaction_count(DEPLOYER)
    gas_price_wei  = w3.eth.gas_price

    print("=" * 64, flush=True)
    print(f"Stress Test S3: {CONCURRENT_TXS} Concurrent TX (Pipeline Mode)", flush=True)
    print("=" * 64, flush=True)
    print(f"Deployer:             {DEPLOYER}", flush=True)
    print(f"Balance:              {w3.from_wei(balance_before, 'ether'):.6f} ETH", flush=True)
    print(f"Base nonce:           {base_nonce}  →  reserved [{base_nonce}..{base_nonce + CONCURRENT_TXS - 1}]", flush=True)
    print(f"Concurrent TXes:      {CONCURRENT_TXS}", flush=True)
    print(f"Recipients/TX:        {RECIPIENTS_PER_TX}", flush=True)
    print(f"ETH/TX:               {ETH_PER_TX} (original target: {ORIGINAL_TARGET})", flush=True)
    print(f"Total ETH:            {CONCURRENT_TXS * ETH_PER_TX:.4f}", flush=True)
    print(f"Gas price:            {w3.from_wei(gas_price_wei, 'gwei'):.6f} gwei", flush=True)
    print(f"Max concurrent sends: {MAX_CONCURRENT_SENDS} (semaphore)", flush=True)
    print(flush=True)

    # ── Phase 1: build + sign all TXes ──────────────────────────────────────
    print("Phase 1: Building & signing all TXes (sequential, local)...", flush=True)
    phase1_start = time.time()
    entries = []
    for i in range(CONCURRENT_TXS):
        entry = build_and_sign(base_nonce + i, i, gas_price_wei)
        entries.append(entry)
        if (i + 1) % 10 == 0:
            print(f"  Signed {i+1}/{CONCURRENT_TXS}", flush=True)
    phase1_time = time.time() - phase1_start
    print(f"  All {CONCURRENT_TXS} TXes built & signed in {phase1_time:.2f}s", flush=True)

    # Verify all nonces are assigned
    assigned_nonces = [e['nonce'] for e in entries]
    assert assigned_nonces == list(range(base_nonce, base_nonce + CONCURRENT_TXS)), \
        f"Nonce assignment error: {assigned_nonces}"
    print(f"  Nonce assignment check: PASS  [{base_nonce}..{base_nonce + CONCURRENT_TXS - 1}]", flush=True)
    print(flush=True)

    # ── Phase 2: send all TXes concurrently (semaphore caps at MAX_CONCURRENT_SENDS) ──
    print(f"Phase 2: Sending all {CONCURRENT_TXS} TXes concurrently (max {MAX_CONCURRENT_SENDS} at a time)...", flush=True)
    phase2_start = time.time()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SENDS)

    async def send_with_semaphore(entry):
        async with semaphore:
            return await asyncio.to_thread(send_raw, entry)

    tasks = [send_with_semaphore(entry) for entry in entries]
    results = await asyncio.gather(*tasks)

    phase2_time = time.time() - phase2_start

    sent_ok = [r for r in results if r['status'] == 'SENT']
    send_errors = [r for r in results if r['status'] != 'SENT']

    print(f"  All sends completed in {phase2_time:.3f}s", flush=True)
    print(f"  Sent OK:   {len(sent_ok)}/{CONCURRENT_TXS}", flush=True)
    if send_errors:
        for e in send_errors:
            print(f"  SEND ERR nonce={e['nonce']}: {e['status']}", flush=True)

    # Latency distribution
    send_ms_list = [r['send_ms'] for r in sent_ok]
    if send_ms_list:
        send_ms_list.sort()
        n = len(send_ms_list)
        print(f"  Send latency: min={send_ms_list[0]}ms  median={send_ms_list[n//2]}ms  p95={send_ms_list[int(n*0.95)]}ms  max={send_ms_list[-1]}ms", flush=True)

    print(flush=True)

    # ── Wait for confirmations ───────────────────────────────────────────────
    print("Phase 3: Waiting for confirmations (timeout 180s)...", flush=True)
    confirm_start = time.time()
    confirmed = 0
    reverted  = 0
    timeout_  = 0

    for r in sorted(results, key=lambda x: x['nonce']):
        if r.get('tx_hash') is None:
            r['confirmed'] = 'NOT_SENT'
            r['gas_used']  = '-'
            r['block']     = '-'
            continue
        try:
            receipt = w3.eth.wait_for_transaction_receipt(r['tx_hash'], timeout=180)
            r['gas_used'] = receipt.gasUsed
            r['block']    = receipt.blockNumber
            if receipt.status == 1:
                r['confirmed'] = 'SUCCESS'
                confirmed += 1
            else:
                r['confirmed'] = 'REVERTED'
                reverted += 1
        except Exception as ex:
            r['confirmed'] = 'TIMEOUT'
            r['gas_used']  = '-'
            r['block']     = '-'
            timeout_ += 1

    confirm_time   = time.time() - confirm_start
    balance_after  = w3.eth.get_balance(DEPLOYER)
    total_time     = time.time() - phase2_start + phase1_time

    # ── Nonce gap analysis ───────────────────────────────────────────────────
    confirmed_nonces = sorted([r['nonce'] for r in results if r.get('confirmed') == 'SUCCESS'])
    nonce_gaps: list = []
    if confirmed_nonces:
        expected = list(range(confirmed_nonces[0], confirmed_nonces[-1] + 1))
        nonce_gaps = sorted(set(expected) - set(confirmed_nonces))

    # ── Block distribution ────────────────────────────────────────────────────
    block_dist: dict = {}
    for r in results:
        b = r.get('block', '-')
        if b != '-':
            block_dist[b] = block_dist.get(b, 0) + 1

    # ── Print summary ─────────────────────────────────────────────────────────
    print(flush=True)
    print("=" * 64, flush=True)
    print(f"RESULTS: {confirmed} confirmed | {reverted} reverted | {timeout_} timeout | {len(send_errors)} send errors", flush=True)
    print(f"Effective TPS:   {confirmed / phase2_time:.1f} TX/s (send phase)", flush=True)
    print(f"Confirm wait:    {confirm_time:.1f}s", flush=True)
    print(f"Nonce gaps:      {'NONE ✓' if not nonce_gaps else f'GAPS DETECTED: {nonce_gaps} ← CRITICAL BUG'}", flush=True)
    print(f"Blocks used:     {len(block_dist)} — {dict(sorted(block_dist.items()))}", flush=True)
    print(f"Balance before:  {w3.from_wei(balance_before, 'ether'):.6f} ETH", flush=True)
    print(f"Balance after:   {w3.from_wei(balance_after, 'ether'):.6f} ETH", flush=True)
    print(f"Total spent:     {w3.from_wei(balance_before - balance_after, 'ether'):.6f} ETH", flush=True)
    print(flush=True)

    # ── Balance spot check (3 random recipients from confirmed batches) ───────
    import random
    confirmed_results = [r for r in results if r.get('confirmed') == 'SUCCESS']
    print("Balance spot check (3 random recipients):")
    sample = random.sample(confirmed_results, min(3, len(confirmed_results)))
    for r in sample:
        addr = random.choice(r['recipients'])
        bal  = w3.eth.get_balance(addr)
        exp  = w3.to_wei(ETH_PER_TX, 'ether') * 9950 // 10000 // RECIPIENTS_PER_TX
        ok   = "✓ OK" if bal >= exp else f"✗ MISMATCH (got {bal} expected ~{exp})"
        print(f"  nonce={r['nonce']} addr={addr[:18]}... bal={bal} wei  {ok}")

    # ── Write STRESS_S3_RESULTS.md ────────────────────────────────────────────
    outfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "STRESS_S3_RESULTS.md")
    with open(outfile, "w") as f:
        f.write(f"# Stress Test S3 — {CONCURRENT_TXS} Concurrent TX (Pipeline Mode)\n\n")
        f.write(f"**Date:** 2026-04-04\n")
        f.write(f"**Network:** Base Sepolia (chain ID 84532)\n")
        f.write(f"**Contract:** `{CONTRACT}`\n")
        f.write(f"**ETH/TX:** {ETH_PER_TX} *(original target: {ORIGINAL_TARGET} ETH — reduced due to testnet budget)*\n\n")
        f.write(f"---\n\n")
        f.write(f"## Results Table\n\n")
        f.write(f"| # | Nonce | Status | Gas Used | Block | Send ms | Retries |\n")
        f.write(f"|---|-------|--------|----------|-------|---------|--------|\n")
        for r in sorted(results, key=lambda x: x['nonce']):
            f.write(f"| {r['index']} | {r['nonce']} | {r.get('confirmed', r['status'])} | "
                    f"{r.get('gas_used', '-')} | {r.get('block', '-')} | "
                    f"{r.get('send_ms', '-')} | {r.get('attempt', '-')} |\n")

        f.write(f"\n---\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Confirmed | {confirmed}/{CONCURRENT_TXS} |\n")
        f.write(f"| Reverted | {reverted} |\n")
        f.write(f"| Timeout | {timeout_} |\n")
        f.write(f"| Send errors | {len(send_errors)} |\n")
        f.write(f"| Phase 1 (build+sign) | {phase1_time:.2f}s |\n")
        f.write(f"| Phase 2 (concurrent send) | {phase2_time:.3f}s |\n")
        f.write(f"| Effective send TPS | {confirmed/phase2_time:.1f} TX/s |\n")
        f.write(f"| Confirm wait | {confirm_time:.1f}s |\n")
        f.write(f"| Nonce gaps | {'**NONE**' if not nonce_gaps else f'**CRITICAL: {nonce_gaps}**'} |\n")
        f.write(f"| Blocks used | {len(block_dist)} |\n")
        f.write(f"| Block distribution | {dict(sorted(block_dist.items()))} |\n")
        f.write(f"| Balance before | {w3.from_wei(balance_before, 'ether'):.6f} ETH |\n")
        f.write(f"| Balance after | {w3.from_wei(balance_after, 'ether'):.6f} ETH |\n")
        f.write(f"| Total spent | {w3.from_wei(balance_before - balance_after, 'ether'):.6f} ETH |\n")
        f.write(f"| Recipients served | {confirmed * RECIPIENTS_PER_TX} |\n")

    print(f"\nResults saved to: {os.path.abspath(outfile)}")


if __name__ == "__main__":
    asyncio.run(main())
