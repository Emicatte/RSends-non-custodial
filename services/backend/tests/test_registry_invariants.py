"""
RPC-FREE token-registry invariants — fast guards that run on EVERY PR.

These never touch the network. They make the dangerous states impossible to ship:
  1. every (non-native) address is a valid EIP-55 checksum;
  2. enabled  ⇒  verified  (a token can NEVER ship enabled with verified=false);
  3. schema  — required fields present; permitType ∈ {eip2612,none};
     assetType ∈ {native,bridged}; issuer ∈ {Circle,Tether,Maker} for non-native;
     permitType == eip2612 ⇒ permitVersion present.

On-chain checks (symbol/decimals/name parity) live in the SCHEDULED job
(scripts/verify_onchain_registry.py), NOT here — mainnet RPC is too flaky for per-PR CI.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_registry_invariants.py -q
"""

import json

import pytest
from eth_utils import to_checksum_address

from app.services import router_registry as rr

PERMIT_TYPES = {"eip2612", "none"}
ASSET_TYPES = {"native", "bridged"}
ISSUERS = {"Circle", "Tether", "Maker"}
ZERO = "0x" + "0" * 40

REQUIRED_FIELDS = {
    "address", "decimals", "native", "permitType", "assetType",
    "flatFee", "threshold", "aboveFee", "enabled", "verified",
}


def _raw():
    return json.loads(rr._registry_path().read_text())


def _tokens():
    """Yield (chain_id, name, symbol, token_dict, address_format) for every token.

    `addressFormat` is declared per chain and defaults to "evm", so an existing
    chain needs no edit and a new non-EVM chain must say so explicitly rather
    than being inferred from the shape of its address strings.
    """
    for chain_id, obj in _raw().items():
        if chain_id.startswith("_"):
            continue  # file metadata, not a chain
        fmt = obj.get("addressFormat", "evm")
        for sym, t in obj["tokens"].items():
            yield chain_id, obj.get("name", chain_id), sym, t, fmt


# ── 1. Address validity, per address family ─────────────────────────────────
def test_every_address_is_eip55_checksum():
    """EVM chains: EIP-55, unchanged. This is the assertion that must not weaken."""
    for cid, name, sym, t, fmt in _tokens():
        if fmt != "evm":
            continue  # asserted by test_every_non_evm_address_is_valid below
        addr = t["address"]
        if addr == ZERO:
            continue  # native sentinel
        assert addr == to_checksum_address(addr), (
            f"{name}.{sym} address is not EIP-55 checksummed: {addr} "
            f"(expected {to_checksum_address(addr)})"
        )


def test_every_non_evm_address_is_valid():
    """Non-EVM chains get a POSITIVE check, not an exemption — a base58check
    address is verified by its checksum, the same strength EIP-55 gives EVM."""
    from app.security.input_validator import is_tron_address

    validators = {"base58check": is_tron_address}
    for cid, name, sym, t, fmt in _tokens():
        if fmt == "evm":
            continue
        check = validators.get(fmt)
        assert check is not None, (
            f"{name}.{sym} declares addressFormat={fmt!r} with no validator — "
            f"add one rather than leaving the address unchecked"
        )
        assert check(t["address"]), (
            f"{name}.{sym} address fails {fmt} validation: {t['address']}"
        )


def test_every_chain_declares_a_known_address_format():
    """A typo'd or missing family must not silently fall through to 'unchecked'."""
    known = {"evm", "base58check"}
    for chain_id, obj in _raw().items():
        if chain_id.startswith("_"):
            continue  # file metadata, not a chain
        fmt = obj.get("addressFormat", "evm")
        assert fmt in known, f"chain {chain_id}: unknown addressFormat {fmt!r}"


# ── 2. enabled ⇒ verified (the dangerous state is impossible) ────────────────
def test_enabled_implies_verified():
    for cid, name, sym, t, _fmt in _tokens():
        if t["enabled"]:
            assert t["verified"], (
                f"{name}.{sym} ships enabled=true with verified=false — forbidden. "
                f"A token must be human-verified before it can be enabled."
            )


# ── 3. schema ────────────────────────────────────────────────────────────────
def test_required_fields_present():
    for cid, name, sym, t, _fmt in _tokens():
        missing = REQUIRED_FIELDS - set(t.keys())
        assert not missing, f"{name}.{sym} missing required fields: {sorted(missing)}"


def test_field_enums_and_types():
    for cid, name, sym, t, _fmt in _tokens():
        assert t["permitType"] in PERMIT_TYPES, f"{name}.{sym} bad permitType {t['permitType']!r}"
        assert t["assetType"] in ASSET_TYPES, f"{name}.{sym} bad assetType {t['assetType']!r}"
        assert isinstance(t["native"], bool)
        assert isinstance(t["enabled"], bool)
        assert isinstance(t["verified"], bool)
        assert isinstance(t["decimals"], int) and t["decimals"] >= 0
        for fee_field in ("flatFee", "threshold", "aboveFee"):
            assert isinstance(t[fee_field], int) and t[fee_field] >= 0

        if t["native"]:
            # native gas coin has no stablecoin issuer
            assert t["permitType"] == "none", f"{name}.{sym} native must be permitType none"
        else:
            assert t.get("issuer") in ISSUERS, f"{name}.{sym} bad/missing issuer {t.get('issuer')!r}"

        if t["permitType"] == "eip2612":
            assert t.get("permitVersion"), (
                f"{name}.{sym} permitType=eip2612 requires a permitVersion (EIP-712 domain version)"
            )


def test_symbols_array_matches_tokens():
    for chain_id, obj in _raw().items():
        if chain_id.startswith("_"):
            continue  # file metadata, not a chain
        assert set(obj["symbols"]) == set(obj["tokens"].keys()), (
            f"chain {chain_id}: symbols[] != tokens keys"
        )


# ── DAI is deliberately permit-less (non-standard permit → approve+pay) ───────
def test_dai_permit_type_is_none():
    for cid, name, sym, t, _fmt in _tokens():
        if sym == "DAI":
            assert t["permitType"] == "none", f"{name}.DAI must be permitType none (non-standard permit)"
