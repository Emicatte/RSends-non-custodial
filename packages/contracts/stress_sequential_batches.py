"""
Stress Test S2: 20 Batch Sequenziali Rapidi
Simula 20 pagamenti che arrivano in rapida successione.
Ogni batch distribuisce a 10 wallet diversi.

NOTE: ETH_PER_BATCH ridotto a 0.0015 ETH (invece di 0.005 ETH) perché
il balance deployer è ~0.034 ETH (non 0.15 ETH come richiesto dal test originale).
Questo non cambia la semantica del test: il nonce management e il throughput
sono identici indipendentemente dall'amount per batch.
"""
import time
import json
import os
import sys

try:
    from web3 import Web3
    from web3.exceptions import TransactionNotFound
except ImportError:
    print("ERROR: web3 not installed. Run: pip3 install web3")
    sys.exit(1)

RPC_URL      = os.environ.get("RPC_URL", "https://base-sepolia.g.alchemy.com/v2/KsynbKs-OZ1c4BSw-2D4R")
PRIVATE_KEY  = os.environ.get("PRIVATE_KEY", "")
CONTRACT     = "0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3"
DEPLOYER     = "0xa61A471FC226a06C681cf2Ec41d2C64a147b4392"
CHAIN_ID     = 84532

NUM_BATCHES          = 20
RECIPIENTS_PER_BATCH = 10
ETH_PER_BATCH        = 0.0015   # 0.0015 ETH per batch = 0.03 ETH totale (budget-constrained)
ORIGINAL_TARGET      = 0.005    # target originale dell'utente (per documentare scaling)

# ABI minimo per distributeETH
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

# ── Setup ──────────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("ERROR: Cannot connect to RPC")
    sys.exit(1)

contract = w3.eth.contract(address=Web3.to_checksum_address(CONTRACT), abi=ABI)

balance_before = w3.eth.get_balance(DEPLOYER)
current_nonce  = w3.eth.get_transaction_count(DEPLOYER)
gas_price      = w3.eth.gas_price   # current base gas price

print("=" * 60)
print(f"Stress Test S2: {NUM_BATCHES} Sequential Batches")
print("=" * 60)
print(f"Deployer:         {DEPLOYER}")
print(f"Contract:         {CONTRACT}")
print(f"Starting nonce:   {current_nonce}")
print(f"Balance before:   {w3.from_wei(balance_before, 'ether'):.6f} ETH")
print(f"Batches:          {NUM_BATCHES}")
print(f"Recipients/batch: {RECIPIENTS_PER_BATCH}")
print(f"ETH/batch:        {ETH_PER_BATCH} ETH  (original target: {ORIGINAL_TARGET} ETH)")
print(f"Total ETH:        {NUM_BATCHES * ETH_PER_BATCH} ETH")
print(f"Gas price:        {w3.from_wei(gas_price, 'gwei'):.6f} gwei")
print()

results      = []
send_start   = time.time()

for batch_num in range(NUM_BATCHES):
    batch_t0 = time.time()

    # Genera recipient casuali (fresh account per ogni batch)
    recipients = [w3.eth.account.create().address for _ in range(RECIPIENTS_PER_BATCH)]

    # Calcola amounts: distributable = msg.value * 9950 / 10000
    total_wei    = w3.to_wei(ETH_PER_BATCH, 'ether')
    fee_wei      = total_wei * 50 // 10000      # 0.5% fee
    distributable = total_wei - fee_wei
    per_recipient = distributable // RECIPIENTS_PER_BATCH
    amounts = [per_recipient] * (RECIPIENTS_PER_BATCH - 1)
    amounts.append(distributable - sum(amounts))  # dust to last recipient

    # Costruisci TX con nonce esplicito — chiave del test
    # Gas limit 700,000 è sufficiente per 10 recipient (actual ~413K)
    tx = contract.functions.distributeETH(recipients, amounts).build_transaction({
        'from':   DEPLOYER,
        'value':  total_wei,
        'nonce':  current_nonce,
        'gas':    700_000,
        'gasPrice': gas_price,   # legacy pricing — più stabile su testnet
        'chainId': CHAIN_ID,
    })

    # Firma
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)

    # Invia senza aspettare conferma
    raw = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
    try:
        tx_hash     = w3.eth.send_raw_transaction(raw)
        tx_hash_hex = tx_hash.hex()
        status      = "SENT"
    except Exception as e:
        tx_hash_hex = "FAILED"
        status      = f"ERROR: {str(e)[:100]}"

    elapsed_ms = int((time.time() - batch_t0) * 1000)

    results.append({
        'batch':          batch_num + 1,
        'nonce':          current_nonce,
        'tx_hash':        tx_hash_hex,
        'status':         status,
        'recipients':     RECIPIENTS_PER_BATCH,
        'amount_eth':     ETH_PER_BATCH,
        'send_time_ms':   elapsed_ms,
        'recipient_addrs': recipients,  # keep for balance verification
    })

    print(f"Batch {batch_num+1:2d} | nonce={current_nonce} | {status} | {elapsed_ms}ms | {tx_hash_hex[:20]}...")
    current_nonce += 1

total_send_time = time.time() - send_start
print()
print(f"{'=' * 60}")
print(f"All {NUM_BATCHES} batches sent in {total_send_time:.2f}s")
print(f"Avg send latency: {total_send_time / NUM_BATCHES * 1000:.1f}ms per batch")
print(f"Send throughput:  {NUM_BATCHES / total_send_time:.1f} batches/s")
print()

# ── Attendi conferme ───────────────────────────────────────────────────────────
print("Waiting for confirmations (timeout 120s)...")
confirm_start = time.time()
confirmed     = 0
reverted      = 0
failed_count  = 0

for r in results:
    if r['tx_hash'] == "FAILED":
        r['confirmed']    = 'NOT_SENT'
        r['gas_used']     = '-'
        r['block']        = '-'
        failed_count += 1
        continue
    try:
        receipt = w3.eth.wait_for_transaction_receipt(r['tx_hash'], timeout=120)
        r['gas_used'] = receipt.gasUsed
        r['block']    = receipt.blockNumber
        if receipt.status == 1:
            r['confirmed'] = 'SUCCESS'
            confirmed += 1
        else:
            r['confirmed'] = 'REVERTED'
            reverted += 1
        print(f"  Batch {r['batch']:2d} confirmed | block={r['block']} | gas={r['gas_used']:,}")
    except Exception as e:
        r['confirmed'] = f'TIMEOUT'
        r['gas_used']  = '-'
        r['block']     = '-'
        failed_count += 1
        print(f"  Batch {r['batch']:2d} TIMEOUT: {e}")

confirm_elapsed = time.time() - confirm_start
balance_after   = w3.eth.get_balance(DEPLOYER)

print()
print(f"{'=' * 60}")
print(f"Confirmed: {confirmed}/{NUM_BATCHES}  |  Reverted: {reverted}  |  Failed/Timeout: {failed_count}")
print(f"Confirm wait: {confirm_elapsed:.1f}s")
print(f"Balance after: {w3.from_wei(balance_after, 'ether'):.6f} ETH")
print(f"Total spent:   {w3.from_wei(balance_before - balance_after, 'ether'):.6f} ETH")

# ── Nonce gap analysis ─────────────────────────────────────────────────────────
nonces = [r['nonce'] for r in results if r['tx_hash'] != 'FAILED']
gaps   = [nonces[i+1] - nonces[i] for i in range(len(nonces)-1)]
nonce_ok = all(g == 1 for g in gaps)
print(f"Nonce sequence: {'CONTIGUOUS (no gaps)' if nonce_ok else 'GAPS DETECTED: ' + str(gaps)}")

# ── Balance verification — 5 random recipients ─────────────────────────────────
import random
print()
print("Balance verification (5 random recipients):")
print("-" * 50)
sampled = []
for r in random.sample([x for x in results if x.get('confirmed') == 'SUCCESS'], min(5, confirmed)):
    # pick 1 random recipient from the batch
    idx  = random.randint(0, RECIPIENTS_PER_BATCH - 1)
    addr = r['recipient_addrs'][idx]
    bal  = w3.eth.get_balance(addr)
    expected_per = w3.to_wei(ETH_PER_BATCH, 'ether') * 9950 // 10000 // RECIPIENTS_PER_BATCH
    match = "✓ OK" if bal >= expected_per else f"✗ MISMATCH (got {bal}, expected ~{expected_per})"
    print(f"  Batch {r['batch']:2d} idx={idx} | {addr[:20]}... | {bal} wei | {match}")
    sampled.append({'batch': r['batch'], 'addr': addr, 'balance': bal, 'match': match})

# ── Volume scaling analysis ────────────────────────────────────────────────────
eth_price_usd     = 2300
total_eth_moved   = NUM_BATCHES * ETH_PER_BATCH * confirmed / NUM_BATCHES  # scaled by success rate
total_usd         = total_eth_moved * eth_price_usd
scale_to_5eth     = 5 / ETH_PER_BATCH          # multiplier to match 0.005 ETH target
scale_to_original = ORIGINAL_TARGET / ETH_PER_BATCH

# ── Write STRESS_S2_RESULTS.md ─────────────────────────────────────────────────
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STRESS_S2_RESULTS.md")

with open(output_path, "w") as f:
    f.write("# Stress Test S2 — 20 Sequential Batches (Nonce Management)\n\n")
    f.write(f"**Date:** 2026-04-04\n")
    f.write(f"**Network:** Base Sepolia (chain ID 84532)\n")
    f.write(f"**Contract:** `{CONTRACT}`\n")
    f.write(f"**Deployer:** `{DEPLOYER}`\n")
    f.write(f"**ETH/batch:** {ETH_PER_BATCH} ETH *(original target: {ORIGINAL_TARGET} ETH — reduced due to testnet budget)*\n\n")
    f.write("---\n\n")

    f.write("## Send Phase Results\n\n")
    f.write(f"| Batch | Nonce | Send Status | Gas Used | Block | Send Time | Confirm |\n")
    f.write(f"|-------|-------|-------------|----------|-------|-----------|--------|\n")
    for r in results:
        f.write(f"| {r['batch']} | {r['nonce']} | {r['status']} | {r.get('gas_used', '-')} | {r.get('block', '-')} | {r['send_time_ms']}ms | {r.get('confirmed', '…')} |\n")

    f.write(f"\n---\n\n")
    f.write("## Summary\n\n")
    f.write(f"| Metric | Value |\n")
    f.write(f"|--------|-------|\n")
    f.write(f"| Batches sent | {NUM_BATCHES} |\n")
    f.write(f"| Confirmed | {confirmed}/{NUM_BATCHES} |\n")
    f.write(f"| Reverted | {reverted} |\n")
    f.write(f"| Failed/Timeout | {failed_count} |\n")
    f.write(f"| Total send time | {total_send_time:.2f}s |\n")
    f.write(f"| Avg send latency | {total_send_time / NUM_BATCHES * 1000:.1f}ms/batch |\n")
    f.write(f"| Send throughput | {NUM_BATCHES / total_send_time:.1f} batches/s |\n")
    f.write(f"| Confirm wait | {confirm_elapsed:.1f}s |\n")
    f.write(f"| Nonce gaps | {'None' if nonce_ok else 'YES — see above'} |\n")
    f.write(f"| Balance before | {w3.from_wei(balance_before, 'ether'):.6f} ETH |\n")
    f.write(f"| Balance after | {w3.from_wei(balance_after, 'ether'):.6f} ETH |\n")
    f.write(f"| Total spent | {w3.from_wei(balance_before - balance_after, 'ether'):.6f} ETH |\n")
    f.write(f"| Recipients served | {confirmed * RECIPIENTS_PER_BATCH} |\n")

    f.write(f"\n---\n\n")
    f.write("## Balance Verification (5 random recipients)\n\n")
    f.write("| Batch | Index | Address | Balance (wei) | Match |\n")
    f.write("|-------|-------|---------|---------------|-------|\n")
    for s in sampled:
        f.write(f"| {s['batch']} | — | `{s['addr']}` | {s['balance']} | {s['match']} |\n")

    f.write(f"\n---\n\n")
    f.write("## Volume Scaling Analysis\n\n")
    f.write(f"*(ETH price assumed: ${eth_price_usd:,})*\n\n")
    f.write(f"| Scenario | ETH/batch | Total ETH (20 batches) | USD Value |\n")
    f.write(f"|----------|-----------|------------------------|----------|\n")
    f.write(f"| **This test** | {ETH_PER_BATCH} ETH | {NUM_BATCHES * ETH_PER_BATCH:.2f} ETH | ${NUM_BATCHES * ETH_PER_BATCH * eth_price_usd:,.0f} |\n")
    f.write(f"| Target (original) | {ORIGINAL_TARGET} ETH | {NUM_BATCHES * ORIGINAL_TARGET:.2f} ETH | ${NUM_BATCHES * ORIGINAL_TARGET * eth_price_usd:,.0f} |\n")
    f.write(f"| Prod (5 ETH/batch) | 5 ETH | 100 ETH | ${100 * eth_price_usd:,} |\n")
    f.write(f"| Scale to $1M | ~{1_000_000 / eth_price_usd / NUM_BATCHES:.1f} ETH/batch | ~{1_000_000 / eth_price_usd:.0f} ETH | $1,000,000 |\n\n")
    f.write(f"**Throughput extrapolation:** at {NUM_BATCHES / total_send_time:.1f} batches/s, this system can process "
            f"**{NUM_BATCHES / total_send_time * 3600:.0f} batches/hour**.\n\n")
    f.write(f"At prod scale (5 ETH/batch): **${NUM_BATCHES / total_send_time * 5 * eth_price_usd * 3600:,.0f}/hour** capacity.\n")

print(f"\nResults saved to: {output_path}")
print("Done.")
