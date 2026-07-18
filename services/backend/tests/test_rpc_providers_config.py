"""Config-driven RPC provider list (RPC_PROVIDERS_JSON).

Replaces the dead INDEXER_RPC_URLS_JSON (parsed into a property nothing read).
Contract:
  - env var UNSET → provider lists byte-identical to the historical hardcoded
    behavior (Alchemy priority -1 when the key is set, then the public
    fallbacks) — pinned here so the swap is provably a no-op today;
  - a JSON entry {chain_id: [{name, url[, priority]}]} slots extra providers
    between Alchemy and the publics (default priority 0, stable sort → config
    wins ties) — adding the mainnet second vendor is one env edit, zero code;
  - malformed JSON / malformed entries are ignored with a warning, never a
    boot failure.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_rpc_providers_config.py -v
"""

import pytest

from app.config import Settings
from app.services import rpc_manager as rm


def _mgr(monkeypatch, chain_id, *, alchemy_key="", providers_json=""):
    settings = Settings(
        alchemy_api_key=alchemy_key, rpc_providers_json=providers_json
    )
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    return rm.RPCManager(chain_id=chain_id)


def _names(mgr):
    return [p.name for p in mgr._providers]


# ── Default behavior pinned (env unset → identical to today) ──────


def test_default_list_base_mainnet_with_alchemy_key(monkeypatch):
    mgr = _mgr(monkeypatch, 8453, alchemy_key="k")
    assert _names(mgr) == ["alchemy", "base_primary", "base_llama", "base_1rpc"]


def test_default_list_base_sepolia_with_alchemy_key(monkeypatch):
    mgr = _mgr(monkeypatch, 84532, alchemy_key="k")
    assert _names(mgr) == ["alchemy", "base_sepolia"]


def test_default_list_without_alchemy_key(monkeypatch):
    assert _names(_mgr(monkeypatch, 8453)) == [
        "base_primary", "base_llama", "base_1rpc"
    ]
    assert _names(_mgr(monkeypatch, 84532)) == ["base_sepolia"]


# ── Config-driven extras ──────────────────────────────────────────


def test_config_provider_slots_between_alchemy_and_publics(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        84532,
        alchemy_key="k",
        providers_json='{"84532":[{"name":"vendor2","url":"https://sepolia.vendor2.io/v3/KEY"}]}',
    )
    assert _names(mgr) == ["alchemy", "vendor2", "base_sepolia"]
    vendor = mgr._providers[1]
    assert vendor.url == "https://sepolia.vendor2.io/v3/KEY"
    assert vendor.chain_id == 84532
    assert vendor.cb is not None  # gets its own circuit breaker like any provider


def test_config_provider_only_affects_its_chain(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        8453,
        alchemy_key="k",
        providers_json='{"84532":[{"name":"vendor2","url":"https://sepolia.vendor2.io"}]}',
    )
    assert _names(mgr) == ["alchemy", "base_primary", "base_llama", "base_1rpc"]


def test_config_provider_explicit_priority_respected(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        8453,
        alchemy_key="k",
        providers_json='{"8453":[{"name":"lastresort","url":"https://last.io","priority":99}]}',
    )
    assert _names(mgr) == [
        "alchemy", "base_primary", "base_llama", "base_1rpc", "lastresort"
    ]


@pytest.mark.asyncio
async def test_call_fails_over_to_config_provider(monkeypatch):
    """Per-call failover order includes the config provider: Alchemy fails
    transiently → vendor2 (config) answers before the public fallback."""
    mgr = _mgr(
        monkeypatch,
        84532,
        alchemy_key="k",
        providers_json='{"84532":[{"name":"vendor2","url":"https://sepolia.vendor2.io/v3/KEY"}]}',
    )
    tried = []

    async def _fake_raw(url, method, params, timeout=10):
        tried.append(url)
        if "alchemy" in url:
            raise RuntimeError("upstream timeout")
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _fake_raw)
    result = await mgr.call("eth_blockNumber", [])
    assert result == "0x64"
    assert tried[0].startswith("https://base-sepolia.g.alchemy.com")
    assert tried[1] == "https://sepolia.vendor2.io/v3/KEY"


# ── Malformed config never breaks boot ────────────────────────────


def test_malformed_json_falls_back_to_defaults(monkeypatch):
    mgr = _mgr(monkeypatch, 84532, alchemy_key="k", providers_json="{not json")
    assert _names(mgr) == ["alchemy", "base_sepolia"]


def test_malformed_entry_skipped_others_kept(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        84532,
        alchemy_key="k",
        providers_json=(
            '{"84532":[{"name":"nourl"},'
            '{"name":"good","url":"https://good.io"}],'
            '"oops":[{"name":"badchain","url":"https://x.io"}]}'
        ),
    )
    assert _names(mgr) == ["alchemy", "good", "base_sepolia"]


# ── The dead wiring is gone ───────────────────────────────────────


def test_indexer_rpc_urls_json_removed():
    s = Settings()
    assert "indexer_rpc_urls_json" not in type(s).model_fields
    assert not hasattr(type(s), "indexer_rpc_urls")
