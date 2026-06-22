#!/usr/bin/env python3
"""
SCHEDULED / pre-deploy on-chain registry verification + parity (NOT per-PR CI).

For each chain that has a configured RSendsRouter address, this:
  (A) asserts each ENABLED token's on-chain symbol()/decimals() match the registry;
  (B) PARITY — reconstructs the on-chain enabled set from FeeConfigSet logs (latest
      state per token) and asserts it equals the registry's enabled set for the chain.

Mainnet RPC is too flaky to gate every PR, so this runs on a schedule /
workflow_dispatch (see .github/workflows/onchain-verify.yml) and before a deploy.
The deploy-script gate (SetFeeConfig.verifyAndSet) is the PRIMARY backstop; this is
an independent cross-check.

Config (env):
  RSENDS_ROUTER_ADDRESSES_JSON  {"<chainId>": "0xRouter", ...}  (which chains to check)
  INDEXER_RPC_URLS_JSON / ALCHEMY_API_KEY                        (RPC, via rpc_manager)

Exit 0 = all checked chains clean (or skipped: no router). Exit 1 = any mismatch.

Usage:  cd services/backend && python scripts/verify_onchain_registry.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import router_registry as rr  # noqa: E402
from app.services.router_registry import (  # noqa: E402
    CHAIN_IDS,
    FEE_POLICY,
    token_decimals_onchain,
    token_symbol_onchain,
)

# FeeConfigSet(address indexed token, uint256 baseFee, uint256 threshold, uint256 surcharge, bool enabled)
FEE_CONFIG_SET_TOPIC = "0x" + rr._keccak(
    b"FeeConfigSet(address,uint256,uint256,uint256,bool)"
).hex()


def _chain_name(cid: int) -> str:
    for name, c in CHAIN_IDS.items():
        if c == cid and name in FEE_POLICY:
            return name
    return str(cid)


async def _onchain_enabled_set(cid: int, router: str) -> set:
    """Latest on-chain enabled token set, reconstructed from FeeConfigSet logs."""
    from app.services.rpc_manager import get_rpc_manager

    rpc = get_rpc_manager(cid)
    logs = await rpc.call(
        "eth_getLogs",
        [{"fromBlock": "0x0", "toBlock": "latest", "address": router,
          "topics": [FEE_CONFIG_SET_TOPIC]}],
    ) or []
    # token (indexed) is topics[1]; enabled is the last 32-byte word of data.
    latest: dict[str, bool] = {}
    for lg in logs:
        token = "0x" + lg["topics"][1][-40:]
        data = lg["data"][2:]
        enabled = int(data[-64:], 16) == 1
        latest[token.lower()] = enabled  # later logs overwrite → latest state
    return {addr for addr, en in latest.items() if en and addr != "0x" + "0" * 40}


async def verify_chain(cid: int, router: str) -> list[str]:
    name = _chain_name(cid)
    problems: list[str] = []
    pols = FEE_POLICY.get(name, {})

    # (A) metadata of enabled tokens
    for sym, pol in pols.items():
        if pol["native"] or not pol["enabled"]:
            continue
        addr = pol["address"]
        try:
            dec = await token_decimals_onchain(cid, addr)
            symbol = await token_symbol_onchain(cid, addr)
        except Exception as exc:
            problems.append(f"{name}.{sym}: RPC error reading metadata ({exc})")
            continue
        if dec != pol["decimals"]:
            problems.append(f"{name}.{sym}: decimals on-chain={dec} registry={pol['decimals']}")
        if symbol != sym:
            problems.append(f"{name}.{sym}: symbol on-chain={symbol!r} registry={sym!r}")

    # (B) parity — on-chain enabled set == registry enabled set
    registry_enabled = {
        pol["address"] for sym, pol in pols.items() if pol["enabled"] and not pol["native"]
    }
    try:
        onchain_enabled = await _onchain_enabled_set(cid, router)
    except Exception as exc:
        problems.append(f"{name}: RPC error reading FeeConfigSet logs ({exc})")
        return problems

    only_registry = registry_enabled - onchain_enabled
    only_onchain = onchain_enabled - registry_enabled
    if only_registry:
        problems.append(f"{name}: enabled in registry but NOT on-chain: {sorted(only_registry)}")
    if only_onchain:
        problems.append(f"{name}: enabled on-chain but NOT in registry: {sorted(only_onchain)}")
    return problems


async def main() -> int:
    routers = getattr(rr.get_settings(), "rsends_router_addresses", {}) or {}
    if not routers:
        print("No RSENDS_ROUTER_ADDRESSES_JSON configured — nothing to verify (skip).")
        return 0

    all_problems: list[str] = []
    for cid_str, router in routers.items():
        cid = int(cid_str)
        name = _chain_name(cid)
        if name not in FEE_POLICY:
            print(f"chain {cid}: no registry entry — skipping")
            continue
        print(f"Verifying {name} (chain {cid}) router={router} ...")
        problems = await verify_chain(cid, router)
        if problems:
            all_problems.extend(problems)
        else:
            print(f"  OK — {name} on-chain matches registry (metadata + enabled parity)")

    if all_problems:
        print("\nON-CHAIN REGISTRY VERIFICATION FAILED:")
        for p in all_problems:
            print(f"  ✗ {p}")
        return 1
    print("\nAll configured chains verified clean. ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
