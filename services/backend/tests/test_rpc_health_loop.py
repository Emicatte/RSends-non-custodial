"""Proactive RPC health layer (start_all_managers) — first activation.

The health loop existed since the manager was written but start_all_managers()
was never called, so provider.healthy was never written and call() always
tried every provider. Now that main.py starts it, pin the behavior:

  • start()/stop() lifecycle is clean — no leaked asyncio tasks, idempotent;
  • start_health_checks(chain_ids) instantiates managers into the lazy
    registry BEFORE starting (calling start_all_managers() on an empty
    registry was a silent no-op — the footgun that kept this layer inert);
  • a provider whose probe fails is marked unhealthy and call() skips it
    while a healthy provider exists (per-call failover still works);
  • a provider lagging > MAX_BLOCK_LAG is marked unhealthy, gauges update;
  • ALL probes failing → one CRITICAL + AlertType.RPC_DOWN via alert_service,
    all providers truthfully unhealthy, and NO breaker force-open (the old
    force-open branch was unreachable dead code; call() already tries every
    provider as a last resort, so fail-fast would only delay recovery).

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_rpc_health_loop.py -v
"""

import asyncio
import logging

import pytest

import app.services.alert_service as alert_mod
from app.config import Settings
from app.services import rpc_manager as rm
from app.services.alert_service import init_alert_service
from app.services.circuit_breaker import CBState


def _mgr(monkeypatch, chain_id=84532, alchemy_key="k"):
    settings = Settings(alchemy_api_key=alchemy_key, rpc_providers_json="")
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    return rm.RPCManager(chain_id=chain_id)


@pytest.fixture()
def bare_alert_service():
    old = alert_mod._alert_service
    svc = init_alert_service(
        telegram_token=None, telegram_chat_id=None, webhook_url=None
    )
    yield svc
    alert_mod._alert_service = old


# ── Lifecycle ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_stop_no_leaked_tasks(monkeypatch):
    async def _ok(url, method, params, timeout=10):
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _ok)
    mgr = _mgr(monkeypatch)

    await mgr.start()
    task = mgr._health_task
    assert task is not None and not task.done()

    await mgr.stop()
    assert task.done()
    assert task not in asyncio.all_tasks()


@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch):
    async def _ok(url, method, params, timeout=10):
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _ok)
    mgr = _mgr(monkeypatch)
    await mgr.start()
    first = mgr._health_task
    await mgr.start()
    assert mgr._health_task is first
    await mgr.stop()


@pytest.mark.asyncio
async def test_start_health_checks_populates_registry_and_starts(monkeypatch):
    """The lazy-registry footgun pin: start_health_checks must instantiate
    managers for the given chains (the registry is empty at lifespan time —
    the indexer only calls get_rpc_manager inside its first tick) and then
    start every registered manager."""
    async def _ok(url, method, params, timeout=10):
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _ok)
    settings = Settings(alchemy_api_key="k", rpc_providers_json="")
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    monkeypatch.setattr(rm, "_managers", {})

    await rm.start_health_checks([84532])
    assert 84532 in rm._managers
    mgr = rm._managers[84532]
    assert mgr._running and mgr._health_task is not None

    await rm.stop_all_managers()
    assert not mgr._running


# ── Health-state routing ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_failure_marks_unhealthy_and_call_skips(monkeypatch):
    mgr = _mgr(monkeypatch)  # alchemy + base_sepolia

    async def _alchemy_down(url, method, params, timeout=10):
        if "alchemy" in url:
            raise RuntimeError("probe timeout")
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _alchemy_down)
    await mgr._check_all_providers()

    by_name = {p.name: p for p in mgr._providers}
    assert by_name["alchemy"].healthy is False
    assert by_name["base_sepolia"].healthy is True

    tried = []

    async def _record(url, method, params, timeout=10):
        tried.append(url)
        return "0x64"

    monkeypatch.setattr(rm, "_raw_rpc_call", _record)
    assert await mgr.call("eth_blockNumber", []) == "0x64"
    assert tried == ["https://sepolia.base.org"]  # alchemy skipped


@pytest.mark.asyncio
async def test_lagging_provider_marked_unhealthy_and_gauges_set(monkeypatch):
    mgr = _mgr(monkeypatch)

    async def _lagging_public(url, method, params, timeout=10):
        return "0x100" if "alchemy" in url else "0x10"  # lag 240 > MAX_BLOCK_LAG

    monkeypatch.setattr(rm, "_raw_rpc_call", _lagging_public)
    await mgr._check_all_providers()

    by_name = {p.name: p for p in mgr._providers}
    assert by_name["alchemy"].healthy is True
    assert by_name["base_sepolia"].healthy is False
    assert rm.RPC_HEALTHY.labels(
        chain_id=84532, provider="alchemy"
    )._value.get() == 1
    assert rm.RPC_HEALTHY.labels(
        chain_id=84532, provider="base_sepolia"
    )._value.get() == 0
    assert rm.RPC_BLOCK_HEIGHT.labels(
        chain_id=84532, provider="alchemy"
    )._value.get() == 0x100


# ── All probes down: loud, truthful, NO breaker force-open ───────


@pytest.mark.asyncio
async def test_all_probes_failing_is_critical_alert_without_force_open(
    monkeypatch, bare_alert_service, caplog
):
    mgr = _mgr(monkeypatch)

    async def _all_down(url, method, params, timeout=10):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(rm, "_raw_rpc_call", _all_down)
    with caplog.at_level(logging.WARNING):
        await mgr._check_all_providers()
        for _ in range(3):
            await asyncio.sleep(0)  # drain the fire-and-forget alert task

    assert all(p.healthy is False for p in mgr._providers)
    # breakers untouched: probes bypass them and the force-open is gone
    assert all(p.cb.state is CBState.CLOSED for p in mgr._providers)

    criticals = [
        r for r in caplog.records
        if r.levelno == logging.CRITICAL and "rpc_manager" in r.name
    ]
    assert len(criticals) == 1 and "84532" in criticals[0].getMessage()

    alert_lines = [
        r for r in caplog.records
        if r.name == "rsend.alerts" and "rpc_down" in r.getMessage()
    ]
    assert len(alert_lines) == 1  # visible without Telegram configured
