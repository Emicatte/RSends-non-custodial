#!/usr/bin/env python3
"""
Print the token addresses that still need a final HUMAN EYEBALL before mainnet.

Reads the single source of truth (app/token_registry.json) and lists every token
whose `verified` flag is false — i.e. the address has NOT yet been confirmed
against an official/canonical source by a human. The deploy script
(packages/contracts/script/SetFeeConfig.s.sol) additionally hard-gates each enable
on the token's on-chain symbol()+decimals(), so a wrong address can never be
whitelisted — but a human must still confirm each address is the intended token.

Usage:  cd services/backend && python scripts/print_unverified_tokens.py
"""

import json
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / "app" / "token_registry.json"


def main() -> int:
    raw = json.loads(REGISTRY.read_text())
    print(f"Registry (single source of truth): {REGISTRY}\n")

    rows = []
    for chain_id, obj in raw.items():
        if not chain_id.isdigit():
            continue
        for sym, t in obj.get("tokens", {}).items():
            if t.get("native"):
                continue
            if not t.get("verified", False):
                rows.append((obj.get("name", chain_id), chain_id, sym,
                             t["address"], t.get("enabled", False)))

    if not rows:
        print("All non-native token addresses are marked verified. ✅")
        return 0

    print("ADDRESSES NEEDING A FINAL HUMAN EYEBALL (verified=false):")
    print(f"  {'chain':<14}{'id':<8}{'sym':<6}{'enabled':<9}address")
    for name, cid, sym, addr, enabled in rows:
        print(f"  {name:<14}{cid:<8}{sym:<6}{str(enabled):<9}{addr}")

    print(
        "\nACTION: confirm each address against an official source (issuer docs /"
        "\nblock explorer) before mainnet. The deploy script will REVERT if the"
        "\non-chain symbol()/decimals() don't match the registry, but address"
        "\nIDENTITY still needs human confirmation. Flip `verified` to true in"
        "\napp/token_registry.json once confirmed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
