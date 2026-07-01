"""
Token policy/registry tests — fee encoding + the create-intent enable gate.

Asserts the shared registry (app/token_registry.json, the SINGLE source of truth
also consumed by packages/contracts/script/SetFeeConfig.s.sol) encodes the decided
FLAT pricing — 0.60 below the threshold, 3.00 at/above, NEVER proportional — for
both 6- and 18-decimal tokens, and that the enable gate rejects unknown/disabled
tokens.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_token_registry.py -q
"""

import json

import pytest

from app.services import router_registry as rr
from app.services.router_registry import (
    FEE_POLICY,
    UnsupportedTokenError,
    assert_token_enabled,
    fee_policy_for,
    token_is_enabled,
)


def _stablecoins():
    """Yield (chain, symbol, policy) for every non-native token in the registry."""
    for chain, syms in FEE_POLICY.items():
        for sym, pol in syms.items():
            if not pol["native"]:
                yield chain, sym, pol


def _quote(pol, amount: int) -> int:
    """Mirror RSendsRouter.quoteFee: flat below threshold, +surcharge at/above."""
    fee = pol["flatFee"]
    if pol["threshold"] != 0 and amount >= pol["threshold"]:
        fee += pol["aboveFee"] - pol["flatFee"]
    return fee


# ── Fee encoding: exactly 0.60 / 3.00, in minimal units, for 6- and 18-dec ──
def test_fee_config_encodes_decided_flat_pricing_for_all_tokens():
    seen_decimals = set()
    for chain, sym, pol in _stablecoins():
        dec = pol["decimals"]
        seen_decimals.add(dec)
        # 0.60 below, 3.00 at/above, 1000 threshold — all in token minimal units.
        assert pol["flatFee"] == 60 * 10 ** (dec - 2), f"{chain}.{sym} flatFee"
        assert pol["aboveFee"] == 300 * 10 ** (dec - 2), f"{chain}.{sym} aboveFee"
        assert pol["threshold"] == 1000 * 10 ** dec, f"{chain}.{sym} threshold"
        # surcharge the script will pass on-chain = aboveFee - flatFee (= 2.40).
        assert pol["aboveFee"] - pol["flatFee"] == 240 * 10 ** (dec - 2), f"{chain}.{sym} surcharge"

    # Coverage: both a 6-decimal (USDC/USDT/EURC) and an 18-decimal (DAI) token.
    assert 6 in seen_decimals and 18 in seen_decimals


def test_fee_is_flat_never_proportional():
    for chain, sym, pol in _stablecoins():
        thr = pol["threshold"]
        # Below threshold → flat flatFee.
        assert _quote(pol, thr - 1) == pol["flatFee"]
        # At and far above threshold → identical aboveFee (NOT scaled by amount).
        assert _quote(pol, thr) == pol["aboveFee"]
        assert _quote(pol, thr * 5_000) == pol["aboveFee"]
        assert _quote(pol, thr * 1_000_000) == pol["aboveFee"]
        # And it is genuinely NOT a percentage: fee/amount must differ across amounts.
        r1 = _quote(pol, thr) / thr
        r2 = _quote(pol, thr * 5_000) / (thr * 5_000)
        assert r1 != r2, f"{chain}.{sym} looks proportional"


# ── Enable gate: reject unknown / disabled tokens ──
def test_enable_gate_accepts_enabled_token():
    assert token_is_enabled("base", "USDC") is True
    assert_token_enabled("base", "USDC")  # no raise
    # chain alias resolves
    assert token_is_enabled("eth", "USDC") is True


def test_enable_gate_rejects_disabled_token():
    # Base DAI ships disabled (address needs human verification before mainnet).
    assert token_is_enabled("base", "DAI") is False
    with pytest.raises(UnsupportedTokenError):
        assert_token_enabled("base", "DAI")


def test_enable_gate_rejects_unknown_token_or_chain():
    assert token_is_enabled("base", "cbBTC") is False       # not in registry
    assert token_is_enabled("base", "DOGE") is False
    assert token_is_enabled("solana", "USDC") is False      # chain not in registry
    with pytest.raises(UnsupportedTokenError):
        assert_token_enabled("base", "cbBTC")
    assert fee_policy_for("base", "cbBTC") is None


# ── Single source of truth: backend values match the JSON file verbatim ──
def test_backend_matches_json_file():
    raw = json.loads(rr._registry_path().read_text())
    for chain_id_str, chain_obj in raw.items():
        if not chain_id_str.isdigit():
            continue
        name = chain_obj["name"].lower()
        for sym, t in chain_obj["tokens"].items():
            pol = FEE_POLICY[name][sym.upper()]
            assert pol["address"] == t["address"].lower()
            assert pol["decimals"] == t["decimals"]
            assert pol["flatFee"] == t["flatFee"]
            assert pol["threshold"] == t["threshold"]
            assert pol["aboveFee"] == t["aboveFee"]
            assert pol["enabled"] == t["enabled"]
