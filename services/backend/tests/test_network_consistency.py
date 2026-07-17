"""Network-consistency fixes — the system runs on Base Sepolia (84532), so
health checks and the standalone test-webhook payload must reflect the ACTIVE
chain (derived from the same router config the indexer uses), never a hardcoded
mainnet literal.

Covers ITEM 2 (health RPC probe) and ITEM 4 (test-webhook payload) from the
network-consistency discovery map, plus the shared router_registry helpers.
ITEM 3 is a static docs-string swap (no test); ITEM 1 (intent.network
normalization) is covered by test_intent_network_normalization.py.
"""
import json
from types import SimpleNamespace

import pytest

from app.api import health_routes
from app.services import router_registry, webhook_service
from app.models.merchant_models import MerchantWebhook


def _settings_with_routers(routers: dict) -> SimpleNamespace:
    return SimpleNamespace(rsends_router_addresses=routers)


class _FakeRPC:
    def __init__(self, chain_id: int):
        self.chain_id = chain_id

    async def call(self, method, params):
        return "0x10"  # block 16


# ───────────────────────── shared helper (router_registry) ──────────────────

def test_primary_chain_id_reads_router_config(monkeypatch):
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({"84532": "0xRouter"}),
    )
    assert router_registry.primary_chain_id() == 84532


def test_primary_chain_id_falls_back_to_base_sepolia(monkeypatch):
    """With no routers configured (local/dev), the active chain defaults to the
    testnet we actually run on — never mainnet."""
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({}),
    )
    assert router_registry.primary_chain_id() == 84532


def test_chain_name_and_network_name_for_id():
    assert router_registry.chain_name_for_id(84532) == "base_sepolia"
    assert router_registry.chain_name_for_id(8453) == "base"
    assert router_registry.network_name_for_chain_id(84532) == "BASE_SEPOLIA"
    assert router_registry.network_name_for_chain_id(8453) == "BASE_MAINNET"
    assert router_registry.network_name_for_chain_id(999999) is None


# ─────────────────────────── ITEM 2: health probe ───────────────────────────

@pytest.mark.asyncio
async def test_check_rpc_targets_configured_active_chain(monkeypatch):
    """The deep-health RPC probe hits the chain the indexer is configured for
    (Base Sepolia today), not a hardcoded 8453 mainnet."""
    captured = {}

    def _fake_get_rpc_manager(chain_id):
        captured["chain_id"] = chain_id
        return _FakeRPC(chain_id)

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", _fake_get_rpc_manager
    )
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({"84532": "0xRouter"}),
    )

    result = await health_routes._check_rpc()

    assert captured["chain_id"] == 84532
    assert result["status"] == "ok"
    assert result["chain_id"] == 84532


@pytest.mark.asyncio
async def test_check_rpc_is_derived_not_hardcoded(monkeypatch):
    """A different router config probes a different chain — proves derivation."""
    captured = {}

    def _fake_get_rpc_manager(chain_id):
        captured["chain_id"] = chain_id
        return _FakeRPC(chain_id)

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", _fake_get_rpc_manager
    )
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({"8453": "0xRouter"}),
    )

    await health_routes._check_rpc()

    assert captured["chain_id"] == 8453


# ─────────────────────────── ITEM 4: test payload ───────────────────────────

def test_test_event_payload_reflects_active_chain(monkeypatch):
    """The test-webhook payload carries the real chain (name + id), matching the
    production settlement webhook shape — not a hardcoded BASE_MAINNET string."""
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({"84532": "0xRouter"}),
    )
    wh = MerchantWebhook(
        merchant_id="0xowner", environment="test",
        url="https://merchant.example/hook", secret="s",
        events=[], is_active=True,
    )

    payload = webhook_service._build_test_event_payload(wh)

    assert payload["chain"] == "base_sepolia"
    assert payload["chain_id"] == 84532
    # Consistent with the production _build_merchant_payload: no legacy `network`
    # key, and certainly no mainnet literal.
    assert "network" not in payload
    assert "BASE_MAINNET" not in json.dumps(payload)


def test_test_event_payload_tracks_config_change(monkeypatch):
    """If the system were pointed at Base mainnet, the test payload would follow
    — the value is derived, not fixed."""
    monkeypatch.setattr(
        router_registry, "get_settings",
        lambda: _settings_with_routers({"8453": "0xRouter"}),
    )
    wh = MerchantWebhook(
        merchant_id="0xowner", environment="live",
        url="https://merchant.example/hook", secret="s",
        events=[], is_active=True,
    )

    payload = webhook_service._build_test_event_payload(wh)

    assert payload["chain"] == "base"
    assert payload["chain_id"] == 8453
