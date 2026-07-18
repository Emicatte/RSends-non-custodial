"""First-class indexer stall alert.

The STALLED flag previously had no alert of its own — only the per-provider
circuit breaker's RPC_DOWN page (Telegram-gated) fired, as a side effect.
Pinned here:

  • hitting STALL_TICKS fires AlertType.INDEXER_STALLED exactly once per
    episode (the edge, not every failing tick);
  • the alert is visible WITHOUT Telegram configured — AlertService always
    logs CRITICAL before any external channel (a stalled indexer must be loud
    with zero optional config);
  • recovery fires AlertType.INDEXER_RECOVERED once;
  • the alert task never breaks the loop, and the existing CRITICAL log /
    gauge / health-degraded behavior is unchanged (see test_indexer_cursor).

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_indexer_stall_alert.py -v
"""

import asyncio
import logging

import pytest

import app.services.alert_service as alert_mod
import app.services.payment_indexer as idx
from app.services.alert_service import AlertType, init_alert_service
from app.services.payment_indexer import PaymentWatcher, STALL_TICKS

ROUTER = "0x" + "a" * 40
CHAIN = 84532


@pytest.fixture()
def bare_alert_service():
    """AlertService initialised with NO Telegram and NO webhook — the
    'nothing optional configured' posture the alert must survive."""
    old = alert_mod._alert_service
    svc = init_alert_service(
        telegram_token=None, telegram_chat_id=None, webhook_url=None
    )
    yield svc
    alert_mod._alert_service = old


async def _drain_tasks():
    # let fire-and-forget alert tasks run
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_stall_fires_indexer_stalled_alert_once(bare_alert_service, caplog):
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.WARNING, logger="rsend.alerts"):
        for n in range(1, STALL_TICKS + 3):
            w._note_failure(n, "boom: all providers unreachable")
        await _drain_tasks()

    stalled = [
        r for r in caplog.records
        if AlertType.INDEXER_STALLED.value in r.getMessage()
    ]
    # exactly one alert per stall episode, and it is CRITICAL in plain logs
    assert len(stalled) == 1
    assert stalled[0].levelno == logging.CRITICAL
    assert "84532" in stalled[0].getMessage()


@pytest.mark.asyncio
async def test_recovery_fires_indexer_recovered_alert(bare_alert_service, caplog):
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.INFO, logger="rsend.alerts"):
        w._note_recovery(STALL_TICKS + 1)
        await _drain_tasks()

    recovered = [
        r for r in caplog.records
        if AlertType.INDEXER_RECOVERED.value in r.getMessage()
    ]
    assert len(recovered) == 1


def test_note_failure_without_event_loop_is_safe(bare_alert_service, caplog):
    """Sync context (no running loop): the stall still logs CRITICAL + flips
    the gauge/health flag; the alert dispatch is skipped, never a crash."""
    w = PaymentWatcher(chain_id=CHAIN, router_address=ROUTER)

    with caplog.at_level(logging.ERROR, logger="payment_indexer"):
        for n in range(1, STALL_TICKS + 1):
            w._note_failure(n, "boom")

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1
    assert idx.indexer_status()[CHAIN]["stalled"] is True


def test_alert_types_exist_with_expected_severity():
    from app.services.alert_service import SEVERITY_MAP, AlertSeverity

    assert SEVERITY_MAP[AlertType.INDEXER_STALLED] is AlertSeverity.CRITICAL
    assert SEVERITY_MAP[AlertType.INDEXER_RECOVERED] is AlertSeverity.INFO
