#!/usr/bin/env python3
"""
Base Sepolia money-path smoke — on-chain half (MANUAL, NOT CI).

Submits one `payWithPermit` (USDC/EIP-2612) and, if a non-permit token is given,
one `approve`+`pay`, against a deployed RSendsRouter on Base Sepolia, then confirms
the `PaymentMade` events and merchant/feeCollector balance deltas.

SECRETS: everything sensitive comes from ENV only; the key is NEVER printed. Use a
throwaway burner with testnet funds only. See docs/e2e/base-sepolia-smoke.md.

ENV (required):
  SEPOLIA_RPC_URL      RPC URL for Base Sepolia (chain 84532)
  BURNER_PRIVATE_KEY   throwaway key, testnet funds only
  ROUTER_ADDRESS       deployed RSendsRouter
  USDC_ADDRESS         EIP-2612 USDC (6 dec)
ENV (optional):
  USDT_ADDRESS         non-permit ERC20 you control → also smokes approve+pay
  MERCHANT_ADDRESS     payee (default: 0x…dEaD); only needs to RECEIVE
  AMOUNT_USDC          decimal amount, default "1.0"

Run:  cd services/backend && python scripts/sepolia_smoke.py
"""

import os
import secrets
import sys
import time
from decimal import Decimal

try:
    from eth_abi import encode as abi_encode
    from eth_account import Account
    from web3 import Web3
except Exception:
    sys.exit("Missing deps — run: pip install -r requirements-e2e.txt")

CHAIN_ID = 84532
DEAD = "0x000000000000000000000000000000000000dEaD"
PERMIT_TYPEHASH_TEXT = (
    "Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
)

ERC20_ABI = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "decimals", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "uint8"}]},
    {"type": "function", "name": "nonces", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "DOMAIN_SEPARATOR", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "bytes32"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "v", "type": "uint256"}],
     "outputs": [{"type": "bool"}]},
]
ROUTER_ABI = [
    {"type": "function", "name": "quoteFee", "stateMutability": "view",
     "inputs": [{"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "outputs": [{"name": "fee", "type": "uint256"}]},
    {"type": "function", "name": "feeCollector", "stateMutability": "view",
     "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "pay", "stateMutability": "nonpayable",
     "inputs": [{"name": "invoiceId", "type": "bytes32"}, {"name": "merchant", "type": "address"},
                {"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"},
                {"name": "maxFee", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "payWithPermit", "stateMutability": "nonpayable",
     "inputs": [{"name": "invoiceId", "type": "bytes32"}, {"name": "merchant", "type": "address"},
                {"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"},
                {"name": "maxFee", "type": "uint256"}, {"name": "deadline", "type": "uint256"},
                {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"},
                {"name": "s", "type": "bytes32"}], "outputs": []},
]


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Refusing to run: required ENV {name} is not set (see docs/e2e/base-sepolia-smoke.md).")
    return val


def _send(w3, fn, acct):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    if rcpt.status != 1:
        sys.exit(f"tx reverted: {h.hex()}")
    return rcpt


def _sign_permit(w3, token, key, owner, spender, value, deadline):
    nonce = token.functions.nonces(owner).call()
    domain_sep = token.functions.DOMAIN_SEPARATOR().call()
    type_hash = w3.keccak(text=PERMIT_TYPEHASH_TEXT)
    struct_hash = w3.keccak(abi_encode(
        ["bytes32", "address", "address", "uint256", "uint256", "uint256"],
        [type_hash, owner, spender, value, nonce, deadline],
    ))
    digest = w3.keccak(b"\x19\x01" + bytes(domain_sep) + struct_hash)
    sig = Account.unsafe_sign_hash(digest, private_key=key)
    return sig.v, sig.r.to_bytes(32, "big"), sig.s.to_bytes(32, "big")


def main():
    rpc = _require("SEPOLIA_RPC_URL")
    key = _require("BURNER_PRIVATE_KEY")
    router_addr = Web3.to_checksum_address(_require("ROUTER_ADDRESS"))
    usdc_addr = Web3.to_checksum_address(_require("USDC_ADDRESS"))
    usdt_addr = os.environ.get("USDT_ADDRESS")
    merchant = Web3.to_checksum_address(os.environ.get("MERCHANT_ADDRESS", DEAD))
    amount_dec = Decimal(os.environ.get("AMOUNT_USDC", "1.0"))

    w3 = Web3(Web3.HTTPProvider(rpc))
    if w3.eth.chain_id != CHAIN_ID:
        sys.exit(f"Connected chain {w3.eth.chain_id} != Base Sepolia ({CHAIN_ID}).")
    acct = Account.from_key(key)
    print(f"payer={acct.address} merchant={merchant} router={router_addr}")  # no key printed

    router = w3.eth.contract(address=router_addr, abi=ROUTER_ABI)
    fee_collector = router.functions.feeCollector().call()

    def smoke(token_addr, *, permit):
        token = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
        dec = token.functions.decimals().call()
        amount = int(amount_dec * (10 ** dec))
        fee = router.functions.quoteFee(token.address, amount).call()
        invoice = "0x" + secrets.token_hex(32)
        m0 = token.functions.balanceOf(merchant).call()
        f0 = token.functions.balanceOf(fee_collector).call()

        if permit:
            deadline = int(time.time()) + 3600
            v, r, s = _sign_permit(w3, token, key, acct.address, router.address, amount + fee, deadline)
            rcpt = _send(w3, router.functions.payWithPermit(
                Web3.to_bytes(hexstr=invoice), merchant, token.address, amount, fee, deadline, v, r, s,
            ), acct)
            branch = "payWithPermit"
        else:
            _send(w3, token.functions.approve(router.address, amount + fee), acct)
            rcpt = _send(w3, router.functions.pay(
                Web3.to_bytes(hexstr=invoice), merchant, token.address, amount, fee,
            ), acct)
            branch = "approve+pay"

        m1 = token.functions.balanceOf(merchant).call()
        f1 = token.functions.balanceOf(fee_collector).call()
        assert m1 - m0 == amount, f"{branch}: merchant delta {m1-m0} != {amount}"
        assert f1 - f0 == fee, f"{branch}: feeCollector delta {f1-f0} != {fee}"
        print(f"  OK {branch}: tx={rcpt.transactionHash.hex()} amount={amount} fee={fee} invoice={invoice}")

    print("USDC permit smoke:")
    smoke(usdc_addr, permit=True)
    if usdt_addr:
        print("USDT approve+pay smoke:")
        smoke(usdt_addr, permit=False)

    print("\nOn-chain smoke PASSED. Now confirm the backend marks the invoice paid")
    print("and delivers a signed payment.completed webhook (step 6 in the doc).")


if __name__ == "__main__":
    main()
