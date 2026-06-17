"""
Stress Test S7: Mega Batch Reconciliation — 200 Wallet Payroll Simulation
==========================================================================

Simula un payroll aziendale: 200 dipendenti pagati in una singola TX.
Ogni wei DEVE arrivare al destinatario giusto. Se anche un solo wei
e' sbagliato, il sistema non e' production-ready.

Architettura:
  1. Anvil fork di Base Sepolia (stessa bytecode del contratto reale)
  2. 200 wallet deterministici generati via keccak
  3. Percentuali random (totale = 10000 bps esatti)
  4. distributeETH() con 0.1 ETH
  5. Reconciliation al wei per tutti i 200 recipient
  6. Verifica fee treasury
  7. Verifica eventi (200 SingleTransfer + 1 BatchDistributed)

Esecuzione:
  python3 stress_mega_batch_reconciliation.py
"""
import json
import os
import random
import signal
import subprocess
import sys
import time

try:
    from web3 import Web3
except ImportError:
    print("ERROR: web3 not installed. Run: pip3 install web3")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
FORK_RPC       = "https://base-sepolia.g.alchemy.com/v2/KsynbKs-OZ1c4BSw-2D4R"
ANVIL_RPC      = "http://127.0.0.1:8545"
CONTRACT       = "0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3"
# Anvil default account #0 — deterministic, pre-funded with 1000 ETH
DEPLOYER       = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PRIVATE_KEY    = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
TREASURY       = "0x744Ad424bd3BC24838cF8201D1611d7cC828F9b9"
CHAIN_ID       = 84532

NUM_RECIPIENTS = 200
TOTAL_ETH      = 0.1       # 0.1 ETH = 100000000000000000 wei
FEE_BPS        = 50        # 0.5%
BPS_DENOM      = 10_000

# Event topics (keccak256 of event signatures)
SINGLE_TRANSFER_TOPIC   = Web3.keccak(text="SingleTransfer(address,uint256,uint256)").hex()
BATCH_DISTRIBUTED_TOPIC = Web3.keccak(text="BatchDistributed(address,address,uint256,uint256,uint256)").hex()

# ABI minimo
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
    },
    {
        "inputs": [{"name": "grossAmount", "type": "uint256"}],
        "name": "calcSplit",
        "outputs": [
            {"name": "net", "type": "uint256"},
            {"name": "fee", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "treasury",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "feeBps",
        "outputs": [{"name": "", "type": "uint16"}],
        "stateMutability": "view",
        "type": "function"
    },
]

# ── Anvil lifecycle ───────────────────────────────────────────────────────────
anvil_proc = None

def start_anvil():
    """Fork Base Sepolia in Anvil. Fund deployer with 10 ETH."""
    global anvil_proc
    print("Starting Anvil fork of Base Sepolia...", flush=True)
    anvil_proc = subprocess.Popen(
        [
            "anvil",
            "--fork-url", FORK_RPC,
            "--port", "8545",
            "--accounts", "1",
            "--balance", "1000",       # 1000 ETH per default account
            "--chain-id", str(CHAIN_ID),
            "--silent",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for Anvil to be ready
    w3_check = Web3(Web3.HTTPProvider(ANVIL_RPC))
    for attempt in range(30):
        try:
            if w3_check.is_connected():
                # Fund deployer via Anvil cheatcode (set balance)
                w3_check.provider.make_request(
                    "anvil_setBalance",
                    [DEPLOYER, hex(10 * 10**18)]  # 10 ETH
                )
                print(f"  Anvil ready (fork block: {w3_check.eth.block_number})", flush=True)
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("Anvil failed to start within 15 seconds")


def stop_anvil():
    """Terminate Anvil."""
    global anvil_proc
    if anvil_proc:
        anvil_proc.terminate()
        anvil_proc.wait(timeout=5)
        anvil_proc = None
        print("Anvil stopped.", flush=True)


def cleanup_handler(signum, frame):
    stop_anvil()
    sys.exit(1)


signal.signal(signal.SIGINT, cleanup_handler)
signal.signal(signal.SIGTERM, cleanup_handler)


# ── Helper functions ──────────────────────────────────────────────────────────

def generate_recipients(n):
    """Generate n deterministic wallet addresses via keccak256."""
    return [
        Web3.to_checksum_address(
            "0x" + Web3.keccak(text=f"s7_payroll_recipient_{i}")[-20:].hex()
        )
        for i in range(n)
    ]


def generate_random_bps(n):
    """
    Generate n random basis-point allocations that sum to exactly 10000.
    Strategy: assign random weights, normalize to BPS, fix remainder on last.
    """
    weights = [random.randint(1, 100) for _ in range(n)]
    total_w = sum(weights)

    bps = []
    for i in range(n - 1):
        bps.append(max(1, round(weights[i] / total_w * BPS_DENOM)))
    bps.append(BPS_DENOM - sum(bps))

    # Ensure all positive and sum is exact
    assert sum(bps) == BPS_DENOM, f"BPS sum mismatch: {sum(bps)} != {BPS_DENOM}"
    assert all(b > 0 for b in bps), f"Zero or negative BPS found: min={min(bps)}"

    return bps


def compute_amounts(bps_list, total_wei):
    """
    Compute exact wei amounts from BPS allocations.
    Last recipient gets the remainder to ensure zero dust.
    """
    fee_wei          = total_wei * FEE_BPS // BPS_DENOM
    distributable_wei = total_wei - fee_wei

    amounts = []
    running_sum = 0
    for i, bps in enumerate(bps_list):
        if i < len(bps_list) - 1:
            amt = distributable_wei * bps // BPS_DENOM
            amounts.append(amt)
            running_sum += amt
        else:
            # Last recipient gets remainder — zero dust guarantee
            amounts.append(distributable_wei - running_sum)

    assert sum(amounts) == distributable_wei, (
        f"Amount sum mismatch: {sum(amounts)} != {distributable_wei}"
    )
    return amounts, fee_wei, distributable_wei


# ── MAIN TEST ─────────────────────────────────────────────────────────────────

def main():
    total_start = time.perf_counter()

    print("=" * 70, flush=True)
    print("STRESS TEST S7: Mega Batch Reconciliation — 200 Wallet Payroll", flush=True)
    print("=" * 70, flush=True)
    print(f"Contract:    {CONTRACT}", flush=True)
    print(f"Deployer:    {DEPLOYER}", flush=True)
    print(f"Treasury:    {TREASURY} (config)", flush=True)
    print(f"Recipients:  {NUM_RECIPIENTS}", flush=True)
    print(f"Total ETH:   {TOTAL_ETH}", flush=True)
    print(f"Fee:         {FEE_BPS} bps ({FEE_BPS / 100}%)", flush=True)
    print(flush=True)

    # ── PHASE 0: Start Anvil fork ─────────────────────────────────────────────
    start_anvil()
    w3 = Web3(Web3.HTTPProvider(ANVIL_RPC))
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT), abi=ABI
    )

    deployer_bal = w3.eth.get_balance(DEPLOYER)
    print(f"Deployer balance: {w3.from_wei(deployer_bal, 'ether'):.4f} ETH", flush=True)

    # Read treasury and fee from on-chain state (may differ from hardcoded defaults)
    on_chain_treasury = contract.functions.treasury().call()
    on_chain_fee_bps  = contract.functions.feeBps().call()
    TREASURY_ADDR     = on_chain_treasury
    print(f"Treasury (on-chain): {TREASURY_ADDR}", flush=True)
    print(f"Fee BPS (on-chain):  {on_chain_fee_bps}", flush=True)
    if on_chain_fee_bps != FEE_BPS:
        print(f"  WARNING: on-chain fee ({on_chain_fee_bps}) != expected ({FEE_BPS}), using on-chain value", flush=True)

    # ── PHASE 1: SETUP ────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 1: SETUP — Generate 200 wallets + random BPS allocations", flush=True)
    print(f"{'─' * 70}", flush=True)

    recipients = generate_recipients(NUM_RECIPIENTS)
    bps_list   = generate_random_bps(NUM_RECIPIENTS)

    total_wei = int(TOTAL_ETH * 10**18)  # 100000000000000000 wei

    print(f"  Generated {len(recipients)} recipient wallets", flush=True)
    print(f"  BPS allocations: sum={sum(bps_list)}, min={min(bps_list)}, max={max(bps_list)}", flush=True)

    # ── PHASE 2: PRE-TX CALCULATION ───────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 2: PRE-TX CALCULATION — All math in wei integers", flush=True)
    print(f"{'─' * 70}", flush=True)

    amounts, fee_wei, distributable_wei = compute_amounts(bps_list, total_wei)

    print(f"  total_wei        = {total_wei}", flush=True)
    print(f"  fee_wei          = {fee_wei}  ({fee_wei / 10**18:.10f} ETH)", flush=True)
    print(f"  distributable_wei = {distributable_wei}", flush=True)
    print(f"  sum(amounts)     = {sum(amounts)}", flush=True)
    print(f"  ASSERTION:       sum == distributable? {sum(amounts) == distributable_wei}", flush=True)
    print(f"  min amount       = {min(amounts)} wei ({min(amounts) / 10**18:.18f} ETH)", flush=True)
    print(f"  max amount       = {max(amounts)} wei ({max(amounts) / 10**18:.18f} ETH)", flush=True)
    print(f"  BPS range        = [{min(bps_list)}, {max(bps_list)}]  sum={sum(bps_list)}", flush=True)

    # Verify against on-chain calcSplit
    on_chain_net, on_chain_fee = contract.functions.calcSplit(total_wei).call()
    print(f"  calcSplit(on-chain): net={on_chain_net}, fee={on_chain_fee}", flush=True)
    print(f"  calcSplit match?     fee={on_chain_fee == fee_wei}, net={on_chain_net == distributable_wei}", flush=True)
    assert on_chain_fee == fee_wei, f"Fee mismatch: on-chain {on_chain_fee} != computed {fee_wei}"
    assert on_chain_net == distributable_wei, f"Net mismatch: on-chain {on_chain_net} != computed {distributable_wei}"

    # Save allocation to JSON
    allocation = []
    for i in range(NUM_RECIPIENTS):
        allocation.append({
            "index": i,
            "address": recipients[i],
            "percent_bps": bps_list[i],
            "expected_amount_wei": amounts[i],
        })

    alloc_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "s7_payroll_allocation.json"
    )
    with open(alloc_path, "w") as f:
        json.dump(allocation, f, indent=2)
    print(f"\n  Allocation saved: {alloc_path}", flush=True)

    # ── PHASE 3: EXECUTE ON-CHAIN ─────────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 3: EXECUTE ON-CHAIN — distributeETH(200 recipients)", flush=True)
    print(f"{'─' * 70}", flush=True)

    treasury_before = w3.eth.get_balance(TREASURY_ADDR)
    deployer_before = w3.eth.get_balance(DEPLOYER)
    nonce           = w3.eth.get_transaction_count(DEPLOYER)
    gas_price       = w3.eth.gas_price

    print(f"  Treasury before: {treasury_before} wei", flush=True)
    print(f"  Deployer before: {deployer_before} wei", flush=True)
    print(f"  Nonce:           {nonce}", flush=True)
    print(f"  Gas price:       {w3.from_wei(gas_price, 'gwei'):.4f} gwei", flush=True)

    # Build and sign TX
    t_build = time.perf_counter()
    tx = contract.functions.distributeETH(recipients, amounts).build_transaction({
        "from":     DEPLOYER,
        "value":    total_wei,
        "nonce":    nonce,
        "gas":      8_000_000,    # generous limit for 200 recipients
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    })
    signed = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    raw    = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
    build_ms = int((time.perf_counter() - t_build) * 1000)
    print(f"  TX built + signed in {build_ms}ms", flush=True)

    # Send
    t_send = time.perf_counter()
    tx_hash = w3.eth.send_raw_transaction(raw)
    tx_hash_hex = tx_hash.hex()
    print(f"  TX sent: {tx_hash_hex}", flush=True)

    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    confirm_ms = int((time.perf_counter() - t_send) * 1000)

    if receipt.status != 1:
        print(f"\n  CRITICAL: TX REVERTED! Receipt: {dict(receipt)}", flush=True)
        stop_anvil()
        sys.exit(1)

    print(f"  TX confirmed in {confirm_ms}ms", flush=True)
    print(f"  Block:    {receipt.blockNumber}", flush=True)
    print(f"  Gas used: {receipt.gasUsed:,}", flush=True)
    print(f"  Gas/recipient: {receipt.gasUsed // NUM_RECIPIENTS:,}", flush=True)

    # ── PHASE 4: RECONCILIATION AL WEI ────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 4: RECONCILIATION AL WEI — 200/200 recipients", flush=True)
    print(f"{'─' * 70}", flush=True)

    t_recon = time.perf_counter()
    recon_failures = []
    recon_ok = 0

    for i in range(NUM_RECIPIENTS):
        actual = w3.eth.get_balance(recipients[i])
        expected = amounts[i]
        if actual != expected:
            delta = actual - expected
            recon_failures.append({
                "index":    i,
                "address":  recipients[i],
                "expected": expected,
                "actual":   actual,
                "delta":    delta,
            })
            print(f"  CRITICAL FAILURE [{i:3d}] {recipients[i][:16]}... "
                  f"expected={expected} actual={actual} delta={delta}", flush=True)
        else:
            recon_ok += 1
        if (i + 1) % 50 == 0:
            print(f"  Verified {i + 1}/{NUM_RECIPIENTS}...", flush=True)

    recon_ms = int((time.perf_counter() - t_recon) * 1000)
    recon_pass = len(recon_failures) == 0

    print(f"\n  Reconciliation: {recon_ok}/{NUM_RECIPIENTS} OK, "
          f"{len(recon_failures)} failures  ({recon_ms}ms)", flush=True)
    if recon_pass:
        print("  RESULT: PASS — Every wei accounted for", flush=True)
    else:
        print("  RESULT: FAIL — Wei mismatch detected!", flush=True)
        for rf in recon_failures[:10]:
            print(f"    [{rf['index']}] {rf['address']}: "
                  f"delta={rf['delta']} wei", flush=True)

    # ── PHASE 5: FEE VERIFICATION ─────────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 5: FEE VERIFICATION — Treasury balance delta", flush=True)
    print(f"{'─' * 70}", flush=True)

    treasury_after = w3.eth.get_balance(TREASURY_ADDR)
    fee_received   = treasury_after - treasury_before
    fee_match      = fee_received == fee_wei

    print(f"  Treasury before: {treasury_before} wei", flush=True)
    print(f"  Treasury after:  {treasury_after} wei", flush=True)
    print(f"  Fee received:    {fee_received} wei", flush=True)
    print(f"  Fee expected:    {fee_wei} wei", flush=True)
    print(f"  Match:           {'PASS' if fee_match else 'CRITICAL FAILURE'}", flush=True)
    if not fee_match:
        print(f"  Delta: {fee_received - fee_wei} wei", flush=True)

    # ── PHASE 6: EVENT VERIFICATION ───────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 6: EVENT VERIFICATION — SingleTransfer + BatchDistributed", flush=True)
    print(f"{'─' * 70}", flush=True)

    single_transfers = []
    batch_events     = []

    for log in receipt.logs:
        if not log["topics"]:
            continue
        topic0 = log["topics"][0].hex()

        if topic0 == SINGLE_TRANSFER_TOPIC:
            to_addr = Web3.to_checksum_address("0x" + log["topics"][1].hex()[-40:])
            raw_data = log["data"].hex() if isinstance(log["data"], bytes) else log["data"]
            raw_data = raw_data[2:] if raw_data.startswith("0x") else raw_data
            amount = int(raw_data[:64], 16)
            index  = int(raw_data[64:128], 16)
            single_transfers.append({
                "to":     to_addr,
                "amount": amount,
                "index":  index,
            })

        elif topic0 == BATCH_DISTRIBUTED_TOPIC:
            raw_data = log["data"].hex() if isinstance(log["data"], bytes) else log["data"]
            raw_data = raw_data[2:] if raw_data.startswith("0x") else raw_data
            total_amount    = int(raw_data[:64], 16)
            recipient_count = int(raw_data[64:128], 16)
            fee_emitted     = int(raw_data[128:192], 16)
            batch_events.append({
                "totalAmount":    total_amount,
                "recipientCount": recipient_count,
                "fee":            fee_emitted,
            })

    # Verify counts
    st_count_ok    = len(single_transfers) == NUM_RECIPIENTS
    batch_count_ok = len(batch_events) == 1

    print(f"  SingleTransfer events:    {len(single_transfers)} (expected {NUM_RECIPIENTS}) "
          f"{'PASS' if st_count_ok else 'FAIL'}", flush=True)
    print(f"  BatchDistributed events:  {len(batch_events)} (expected 1) "
          f"{'PASS' if batch_count_ok else 'FAIL'}", flush=True)

    # Verify SingleTransfer amounts match expected
    event_mismatches = []
    expected_map = {r.lower(): amounts[i] for i, r in enumerate(recipients)}

    for st in single_transfers:
        expected_amt = expected_map.get(st["to"].lower())
        if expected_amt is None:
            event_mismatches.append({"to": st["to"], "error": "unknown recipient"})
        elif st["amount"] != expected_amt:
            event_mismatches.append({
                "to":       st["to"],
                "index":    st["index"],
                "expected": expected_amt,
                "emitted":  st["amount"],
                "delta":    st["amount"] - expected_amt,
            })

    events_pass = st_count_ok and batch_count_ok and len(event_mismatches) == 0

    print(f"  Event amount mismatches:  {len(event_mismatches)} "
          f"{'PASS' if len(event_mismatches) == 0 else 'FAIL'}", flush=True)

    # Verify BatchDistributed fields
    if batch_events:
        be = batch_events[0]
        print(f"  BatchDistributed.totalAmount:    {be['totalAmount']} "
              f"(expected {total_wei}) {'PASS' if be['totalAmount'] == total_wei else 'FAIL'}", flush=True)
        print(f"  BatchDistributed.recipientCount: {be['recipientCount']} "
              f"(expected {NUM_RECIPIENTS}) {'PASS' if be['recipientCount'] == NUM_RECIPIENTS else 'FAIL'}", flush=True)
        print(f"  BatchDistributed.fee:            {be['fee']} "
              f"(expected {fee_wei}) {'PASS' if be['fee'] == fee_wei else 'FAIL'}", flush=True)

    if event_mismatches:
        for m in event_mismatches[:5]:
            print(f"    MISMATCH: {m}", flush=True)

    # ── PHASE 7: CONSERVATION OF VALUE ────────────────────────────────────────
    print(f"\n{'─' * 70}", flush=True)
    print("PHASE 7: CONSERVATION OF VALUE — total_in == fee + sum(distributions)", flush=True)
    print(f"{'─' * 70}", flush=True)

    total_distributed_actual = sum(
        w3.eth.get_balance(r) for r in recipients
    )
    conservation_ok = (fee_received + total_distributed_actual) == total_wei

    print(f"  Total sent to contract:  {total_wei} wei", flush=True)
    print(f"  Fee to treasury:         {fee_received} wei", flush=True)
    print(f"  Total to recipients:     {total_distributed_actual} wei", flush=True)
    print(f"  Fee + recipients:        {fee_received + total_distributed_actual} wei", flush=True)
    print(f"  Conservation:            {'PASS' if conservation_ok else 'CRITICAL FAILURE'}", flush=True)
    if not conservation_ok:
        missing = total_wei - (fee_received + total_distributed_actual)
        print(f"  MISSING WEI: {missing}", flush=True)

    # ── FINAL REPORT ──────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start

    print(f"\n{'=' * 70}", flush=True)
    print("FINAL REPORT", flush=True)
    print(f"{'=' * 70}", flush=True)

    all_pass = recon_pass and fee_match and events_pass and conservation_ok

    checks = [
        ("Wei reconciliation (200/200)",    recon_pass),
        ("Fee verification",                fee_match),
        ("Event count (200 ST + 1 BD)",     st_count_ok and batch_count_ok),
        ("Event amount verification",       len(event_mismatches) == 0),
        ("Conservation of value",           conservation_ok),
    ]

    for label, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}", flush=True)

    print(flush=True)
    print(f"  TX hash:        {tx_hash_hex}", flush=True)
    print(f"  Block:          {receipt.blockNumber}", flush=True)
    print(f"  Gas used:       {receipt.gasUsed:,}", flush=True)
    print(f"  Gas/recipient:  {receipt.gasUsed // NUM_RECIPIENTS:,}", flush=True)
    print(f"  Total time:     {total_elapsed:.1f}s", flush=True)
    print(f"  Build+sign:     {build_ms}ms", flush=True)
    print(f"  Confirm:        {confirm_ms}ms", flush=True)
    print(f"  Reconciliation: {recon_ms}ms", flush=True)
    print(flush=True)

    verdict = "PRODUCTION-READY" if all_pass else "NOT PRODUCTION-READY"
    print(f"  VERDICT: {verdict}", flush=True)
    print(f"{'=' * 70}", flush=True)

    # ── Write STRESS_S7_MEGA_BATCH.md ─────────────────────────────────────────
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "STRESS_S7_MEGA_BATCH.md"
    )

    with open(out_path, "w") as f:
        def w(s=""): f.write(s + "\n")

        w("# Stress Test S7 — Mega Batch Reconciliation (200 Wallet Payroll)")
        w()
        w(f"**Date:** {today}")
        w(f"**Network:** Base Sepolia fork (Anvil, chain ID {CHAIN_ID})")
        w(f"**Contract:** `{CONTRACT}`")
        w(f"**Deployer:** `{DEPLOYER}`")
        w(f"**Treasury:** `{TREASURY_ADDR}`")
        w(f"**Total distributed:** {TOTAL_ETH} ETH ({total_wei} wei)")
        w(f"**Fee:** {FEE_BPS} bps ({FEE_BPS/100}%)")
        w(f"**Recipients:** {NUM_RECIPIENTS}")
        w()
        w("---")
        w()
        w("## Verdict")
        w()
        w(f"**{verdict}**")
        w()
        w("| Check | Result |")
        w("|-------|--------|")
        for label, passed in checks:
            w(f"| {label} | {'PASS' if passed else 'FAIL'} |")
        w()
        w("---")
        w()
        w("## Transaction Details")
        w()
        w("| Metric | Value |")
        w("|--------|-------|")
        w(f"| TX hash | `{tx_hash_hex}` |")
        w(f"| Block | {receipt.blockNumber} |")
        w(f"| Gas used | {receipt.gasUsed:,} |")
        w(f"| Gas per recipient | {receipt.gasUsed // NUM_RECIPIENTS:,} |")
        w(f"| Gas price | {w3.from_wei(gas_price, 'gwei'):.4f} gwei |")
        w(f"| Gas cost | {w3.from_wei(receipt.gasUsed * gas_price, 'ether'):.8f} ETH |")
        w(f"| Build+sign time | {build_ms}ms |")
        w(f"| Confirm time | {confirm_ms}ms |")
        w(f"| Reconciliation time | {recon_ms}ms |")
        w(f"| Total test time | {total_elapsed:.1f}s |")
        w()
        w("---")
        w()
        w("## Fee Verification")
        w()
        w("| Metric | Value |")
        w("|--------|-------|")
        w(f"| Fee expected | {fee_wei} wei |")
        w(f"| Fee received (treasury delta) | {fee_received} wei |")
        w(f"| Match | {'PASS' if fee_match else 'FAIL'} |")
        w()
        w("---")
        w()
        w("## Conservation of Value")
        w()
        w("| Component | Wei |")
        w("|-----------|-----|")
        w(f"| Total sent (msg.value) | {total_wei} |")
        w(f"| Fee to treasury | {fee_received} |")
        w(f"| Total to recipients | {total_distributed_actual} |")
        w(f"| Fee + recipients | {fee_received + total_distributed_actual} |")
        w(f"| Missing wei | {total_wei - (fee_received + total_distributed_actual)} |")
        w()
        w("---")
        w()
        w("## Event Verification")
        w()
        w("| Metric | Expected | Actual | Result |")
        w("|--------|----------|--------|--------|")
        w(f"| SingleTransfer events | {NUM_RECIPIENTS} | {len(single_transfers)} | {'PASS' if st_count_ok else 'FAIL'} |")
        w(f"| BatchDistributed events | 1 | {len(batch_events)} | {'PASS' if batch_count_ok else 'FAIL'} |")
        w(f"| Event amount mismatches | 0 | {len(event_mismatches)} | {'PASS' if len(event_mismatches) == 0 else 'FAIL'} |")
        if batch_events:
            be = batch_events[0]
            w(f"| BD.totalAmount | {total_wei} | {be['totalAmount']} | {'PASS' if be['totalAmount'] == total_wei else 'FAIL'} |")
            w(f"| BD.recipientCount | {NUM_RECIPIENTS} | {be['recipientCount']} | {'PASS' if be['recipientCount'] == NUM_RECIPIENTS else 'FAIL'} |")
            w(f"| BD.fee | {fee_wei} | {be['fee']} | {'PASS' if be['fee'] == fee_wei else 'FAIL'} |")
        w()
        w("---")
        w()
        w("## Reconciliation Detail (200 recipients)")
        w()
        w(f"**Verified: {recon_ok}/{NUM_RECIPIENTS}** | Failures: {len(recon_failures)}")
        w()
        if recon_failures:
            w("### Failures:")
            w()
            w("| Index | Address | Expected | Actual | Delta |")
            w("|-------|---------|----------|--------|-------|")
            for rf in recon_failures:
                w(f"| {rf['index']} | `{rf['address']}` | {rf['expected']} | {rf['actual']} | {rf['delta']} |")
            w()
        w("### Distribution Statistics")
        w()
        w("| Metric | Value |")
        w("|--------|-------|")
        w(f"| Min allocation | {min(bps_list)} bps ({min(amounts)} wei) |")
        w(f"| Max allocation | {max(bps_list)} bps ({max(amounts)} wei) |")
        w(f"| Median allocation | {sorted(bps_list)[NUM_RECIPIENTS//2]} bps |")
        w(f"| Distributable | {distributable_wei} wei ({distributable_wei/10**18:.18f} ETH) |")
        w()
        w("---")
        w()
        w("## Production Scaling Analysis")
        w()
        eth_price = 2500
        gas_cost_eth = receipt.gasUsed * gas_price / 10**18
        gas_cost_usd = gas_cost_eth * eth_price
        w(f"*(ETH price assumed: ${eth_price:,})*")
        w()
        w("| Scenario | Amount | Gas Cost | Total Cost |")
        w("|----------|--------|----------|------------|")
        w(f"| This test (200 recipients) | {TOTAL_ETH} ETH (${TOTAL_ETH * eth_price:,.0f}) | {gas_cost_eth:.8f} ETH (${gas_cost_usd:.4f}) | ${TOTAL_ETH * eth_price + gas_cost_usd:,.2f} |")
        scale_10 = 10.0
        w(f"| 200 recipients @ 10 ETH | {scale_10} ETH (${scale_10 * eth_price:,.0f}) | ~{gas_cost_eth:.8f} ETH | ${scale_10 * eth_price + gas_cost_usd:,.2f} |")
        scale_100 = 100.0
        w(f"| 200 recipients @ 100 ETH | {scale_100} ETH (${scale_100 * eth_price:,.0f}) | ~{gas_cost_eth:.8f} ETH | ${scale_100 * eth_price + gas_cost_usd:,.2f} |")
        w(f"| 200 recipients @ $1M payroll | ~{1_000_000/eth_price:.2f} ETH | ~{gas_cost_eth:.8f} ETH | ~$1,000,000 |")
        w()
        w(f"**Gas cost per recipient:** {receipt.gasUsed // NUM_RECIPIENTS:,} gas = ~${gas_cost_usd / NUM_RECIPIENTS:.6f}/recipient")
        w()
        w("---")
        w()
        w("## Methodology")
        w()
        w("1. **Anvil Fork**: Base Sepolia forked locally — identical contract bytecode, deterministic execution")
        w("2. **Wallet Generation**: 200 deterministic addresses via `keccak256(\"s7_payroll_recipient_{i}\")`")
        w("3. **BPS Allocation**: Random basis-point percentages summing to exactly 10,000 (100%)")
        w("4. **Amount Calculation**: Integer arithmetic only — last recipient gets `distributable - sum(others)` (zero dust)")
        w("5. **Reconciliation**: `eth_getBalance` for all 200 addresses, compared to expected amounts")
        w("6. **Fee Verification**: Treasury balance delta compared to `total * 50 / 10000`")
        w("7. **Event Parsing**: Raw log decoding of SingleTransfer and BatchDistributed topics")
        w("8. **Conservation**: `fee + sum(balances) == msg.value` — total value conservation check")

    print(f"\nReport saved to: {os.path.abspath(out_path)}", flush=True)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    stop_anvil()

    return 0 if all_pass else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        stop_anvil()
        exit_code = 1
    sys.exit(exit_code)
