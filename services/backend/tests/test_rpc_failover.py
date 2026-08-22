"""RPC multi-provider failover — does it actually work?

`RPC_PROVIDERS_JSON` and the failover it feeds were documented in a comment
(`app/config.py`) and never exercised end-to-end with the error shapes that
actually occur. This file drives the REAL `_raw_rpc_call` through an
`httpx.MockTransport`, so JSON parsing, HTTP status handling and the
permanent/transient classifier are all in the path — not stubbed away.

Incident of record (2026-08-22): `sepolia.base.org` returned
`-32011 no backend is currently healthy to serve traffic` for minutes while
Alchemy had been quota-exhausted (HTTP 429) for days. Nothing alerted, because
the quota rejection was classified as a PERMANENT request error and therefore
excluded from the provider's circuit breaker — the breaker never opened, so the
`RPC_DOWN` transition alert never fired.

No test here contacts a real endpoint.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_rpc_failover.py -v
"""

import asyncio
import logging
from pathlib import Path

import httpx
import pytest

import app.services.alert_service as alert_mod
from app.config import Settings
from app.services import rpc_manager as rm
from app.services.alert_service import init_alert_service
from app.services.circuit_breaker import CBState

# ── Real vendor error bodies (verbatim shapes observed in production) ──

BASE_SEPOLIA_NO_BACKEND = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": -32011,
        "message": "no backend is currently healthy to serve traffic",
    },
}
ALCHEMY_MONTHLY_QUOTA = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": 429,
        "message": (
            "Monthly capacity limit exceeded. Visit "
            "https://dashboard.alchemyapi.io/settings/billing to upgrade your "
            "scaling policy for continued service."
        ),
    },
}
ALCHEMY_CUPS_THROTTLE = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": 429,
        "message": (
            "Your app has exceeded its compute units per second capacity. If "
            "you have retries enabled, you can safely ignore this message."
        ),
    },
}

OK_BLOCK = {"jsonrpc": "2.0", "id": 1, "result": "0x64"}


# ── Harness ───────────────────────────────────────────────────────


def _mgr(monkeypatch, chain_id=84532, *, alchemy_key="k", providers_json=""):
    settings = Settings(
        alchemy_api_key=alchemy_key, rpc_providers_json=providers_json
    )
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    return rm.RPCManager(chain_id=chain_id)


def _names(mgr):
    return [p.name for p in mgr._providers]


def _serve(monkeypatch, handler):
    """Route rpc_manager's httpx traffic through a MockTransport.

    The real `_raw_rpc_call` runs: status codes, `.json()` parsing and the
    classifier are all exercised. `handler(request) -> httpx.Response`, or the
    handler may raise (e.g. `httpx.ConnectError`) to model a transport fault.
    """
    real_client_cls = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(rm.httpx, "AsyncClient", _factory)


async def _reset_breakers(mgr):
    """Circuit-breaker state is keyed by provider name and (when Redis is up)
    survives across tests. Force-close every breaker so each test starts from
    CLOSED — using the REAL breakers built by RPCProvider, not stand-ins."""
    for p in mgr._providers:
        await p.cb.force_close()
        p.consecutive_failures = 0
        p.lost = False


@pytest.fixture(autouse=True)
async def _leave_breakers_closed():
    """Provider breaker names (`rpc_<provider>_<chain>`) are stable across
    tests, and with a real Redis their state OUTLIVES the test that opened it.
    Leave every RPC breaker CLOSED so a test that deliberately opens one cannot
    leak `open` into an unrelated test's dependency-health assertions."""
    yield
    from app.services.circuit_breaker import get_all_circuit_breakers

    for name, cb in list(get_all_circuit_breakers().items()):
        if name.startswith("rpc_"):
            await cb.force_close()


@pytest.fixture()
def bare_alert_service():
    """AlertService with no Telegram/webhook: alerts still emit their
    guaranteed `rsend.alerts` log line, with fresh per-test cooldowns."""
    old = alert_mod._alert_service
    svc = init_alert_service(
        telegram_token=None, telegram_chat_id=None, webhook_url=None
    )
    yield svc
    alert_mod._alert_service = old


# ══════════════════════════════════════════════════════════════════
#  1 — the outage of record: -32011 on the first provider
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_minus_32011_fails_over_to_second_provider(monkeypatch):
    """The exact Base Sepolia fleet outage: the public endpoint answers
    `-32011 no backend is currently healthy`, the second provider serves."""
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    # Drop Alchemy so provider 1 IS the -32011 one, keeping the test focused.
    mgr._providers = [p for p in mgr._providers if p.name != "alchemy"]
    assert _names(mgr) == ["quicknode", "base_sepolia"]
    # Reorder so the failing public endpoint is tried first.
    mgr._providers.reverse()

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "sepolia.base.org" in str(request.url):
            return httpx.Response(200, json=BASE_SEPOLIA_NO_BACKEND)
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    assert await mgr.call("eth_blockNumber", []) == "0x64"
    assert seen == ["https://sepolia.base.org", "https://vendor2.example/rpc"]


# ══════════════════════════════════════════════════════════════════
#  2 — Alchemy 429 quota exhaustion (the failure that was already live)
# ══════════════════════════════════════════════════════════════════


def test_quota_and_rate_limit_errors_are_transient():
    """A quota / rate-limit rejection is an AVAILABILITY fault, not a property
    of the request: the same call succeeds on another provider now and on this
    provider after the window resets. It must NOT be classified permanent —
    permanent errors are excluded from the circuit breaker, so a quota-dead
    provider would never be marked down and never alert (incident 2026-08-22).
    """
    assert not rm._is_permanent_rpc_error(ALCHEMY_MONTHLY_QUOTA["error"])
    assert not rm._is_permanent_rpc_error(ALCHEMY_CUPS_THROTTLE["error"])
    assert not rm._is_permanent_rpc_error(
        {"code": -32005, "message": "daily request count exceeded, request rate limited"}
    )
    assert not rm._is_permanent_rpc_error({"code": -32029, "message": "rate limit exceeded"})
    assert not rm._is_permanent_rpc_error(
        {"code": -32097, "message": "Request quota exceeded for this endpoint"}
    )


def test_genuine_request_rejections_stay_permanent():
    """Guard rail for the fix above: the getLogs range rejection and the bare
    JSON-RPC deterministic codes must NOT be swept into 'transient'."""
    assert rm._is_permanent_rpc_error({
        "code": -32600,
        "message": (
            "Under the Free tier plan, you can make eth_getLogs requests with "
            "up to a 10 block range."
        ),
    })
    assert rm._is_permanent_rpc_error({"code": -32602, "message": "invalid params"})
    assert rm._is_permanent_rpc_error({"code": -32600, "message": ""})


@pytest.mark.asyncio
async def test_quota_exhausted_provider_fails_over(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "alchemy" in str(request.url):
            return httpx.Response(429, json=ALCHEMY_MONTHLY_QUOTA)
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    assert await mgr.call("eth_blockNumber", []) == "0x64"
    assert "alchemy" in seen[0]
    assert seen[1] == "https://vendor2.example/rpc"


@pytest.mark.asyncio
async def test_quota_exhausted_provider_opens_its_breaker(monkeypatch):
    """The point of the classification: a quota-dead provider must be marked
    down. Once the breaker opens, `call()` stops paying a wasted round-trip on
    every single call, and the breaker's own RPC_DOWN alert can fire."""
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    alchemy = mgr._providers[0]
    assert alchemy.name == "alchemy"
    # The real wiring, pinned: 3 consecutive availability faults open it.
    assert alchemy.cb.failure_threshold == 3

    def handler(request: httpx.Request) -> httpx.Response:
        if "alchemy" in str(request.url):
            return httpx.Response(429, json=ALCHEMY_MONTHLY_QUOTA)
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    for _ in range(3):
        assert await mgr.call("eth_blockNumber", []) == "0x64"

    assert await alchemy.cb.get_state() is CBState.OPEN


# ══════════════════════════════════════════════════════════════════
#  3 — transport faults (a different code path from an error response)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        httpx.ConnectTimeout("timed out"),
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectError("connection refused"),
    ],
    ids=["connect_timeout", "read_timeout", "connect_error"],
)
async def test_transport_faults_fail_over(monkeypatch, fault):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)

    def handler(request: httpx.Request) -> httpx.Response:
        if "alchemy" in str(request.url):
            raise fault
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)
    assert await mgr.call("eth_blockNumber", []) == "0x64"


# ══════════════════════════════════════════════════════════════════
#  4 — every provider down: the error must name chain and method
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_all_providers_failing_names_chain_and_method(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BASE_SEPOLIA_NO_BACKEND)

    _serve(monkeypatch, handler)

    with pytest.raises(RuntimeError) as exc:
        await mgr.call("eth_getLogs", [{}])
    msg = str(exc.value)
    assert "All RPC providers failed" in msg
    assert "eth_getLogs" in msg
    assert "84532" in msg


# ══════════════════════════════════════════════════════════════════
#  5 — ordering: the higher-priority provider serves, the rest idle
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_healthy_primary_serves_alone(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    assert _names(mgr) == ["alchemy", "quicknode", "base_sepolia"]

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    assert await mgr.call("eth_blockNumber", []) == "0x64"
    assert len(seen) == 1 and "alchemy" in seen[0]


# ══════════════════════════════════════════════════════════════════
#  6 — a downed provider is retried, never excluded for the process life
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_open_breaker_is_retried_after_recovery_timeout(monkeypatch):
    """A provider whose breaker opened is skipped only for `recovery_timeout`,
    then probed again (HALF_OPEN) and restored on success. A vendor quota that
    resets monthly must not exclude the provider for the process lifetime."""
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    alchemy = mgr._providers[0]
    assert alchemy.cb.recovery_timeout == 15.0  # real wiring
    alchemy.cb.recovery_timeout = 0.05          # keep the test fast

    down = {"flag": True}
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "alchemy" in str(request.url) and down["flag"]:
            return httpx.Response(503, text="service unavailable")
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    for _ in range(3):
        await mgr.call("eth_blockNumber", [])
    assert await alchemy.cb.get_state() is CBState.OPEN

    # While OPEN: alchemy is skipped entirely (fail-fast, no round-trip).
    seen.clear()
    await mgr.call("eth_blockNumber", [])
    assert not any("alchemy" in u for u in seen)

    # After the recovery window: probed again and restored.
    down["flag"] = False
    await asyncio.sleep(0.06)
    seen.clear()
    assert await mgr.call("eth_blockNumber", []) == "0x64"
    assert any("alchemy" in u for u in seen), "provider was never retried"
    assert await alchemy.cb.get_state() is CBState.CLOSED


@pytest.mark.asyncio
async def test_failed_probe_is_not_resurrected_by_a_stale_block(monkeypatch):
    """A provider whose health probe FAILED this cycle must stay unhealthy.

    `_check_provider` leaves `last_block` at its previous value on failure; if
    that stale height is still within MAX_BLOCK_LAG of the tip, the lag check
    flips the provider back to healthy and `call()` routes to a provider that
    is known to be down right now."""
    mgr = _mgr(monkeypatch)
    alchemy, public = mgr._providers

    async def _both_ok(url, method, params, timeout=10):
        return "0x100"

    monkeypatch.setattr(rm, "_raw_rpc_call", _both_ok)
    await mgr._check_all_providers()
    assert alchemy.healthy and public.healthy
    assert alchemy.last_block == 0x100

    # Next cycle: alchemy's probe fails, the public provider advances by 1 —
    # so alchemy's STALE height is still within MAX_BLOCK_LAG of the tip.
    async def _alchemy_probe_down(url, method, params, timeout=10):
        if "alchemy" in url:
            raise RuntimeError("probe timeout")
        return "0x101"

    monkeypatch.setattr(rm, "_raw_rpc_call", _alchemy_probe_down)
    await mgr._check_all_providers()

    assert public.healthy is True
    assert alchemy.healthy is False, (
        "a provider whose probe failed this cycle was resurrected by its "
        "stale last_block"
    )
    assert rm.RPC_HEALTHY.labels(chain_id=84532, provider="alchemy")._value.get() == 0


# ══════════════════════════════════════════════════════════════════
#  7/8 — RPC_PROVIDERS_JSON parsing
# ══════════════════════════════════════════════════════════════════


def test_malformed_providers_json_warns_and_boots(caplog):
    """Claimed in the config comment: malformed input is ignored with a
    warning, never a boot failure. Pin BOTH halves."""
    s = Settings(rpc_providers_json="{not json")
    with caplog.at_level(logging.WARNING):
        assert s.rpc_extra_providers == {}
    assert any(
        "RPC_PROVIDERS_JSON" in r.getMessage() or "JSON" in r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING
    ), "malformed RPC_PROVIDERS_JSON was swallowed without a warning"


def test_malformed_entry_warns_and_keeps_the_good_ones(caplog):
    s = Settings(rpc_providers_json=(
        '{"84532":[{"name":"nourl"},{"name":"good","url":"https://good.example"}]}'
    ))
    with caplog.at_level(logging.WARNING):
        parsed = s.rpc_extra_providers
    assert parsed == {84532: [
        {"name": "good", "url": "https://good.example", "priority": 0}
    ]}
    assert any(
        "RPC_PROVIDERS_JSON" in r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING
    )


def test_wellformed_json_produces_the_expected_ordered_list(monkeypatch):
    """The QuickNode runbook value: omitted `priority` (→ 0) slots the vendor
    between Alchemy (-1) and the public fallback (0, appended later)."""
    mgr = _mgr(
        monkeypatch,
        providers_json=(
            '{"84532":[{"name":"quicknode",'
            '"url":"https://sub.base-sepolia.quiknode.example/token/"}]}'
        ),
    )
    assert _names(mgr) == ["alchemy", "quicknode", "base_sepolia"]
    assert [p.priority for p in mgr._providers] == [-1, 0, 0]
    assert mgr._providers[1].url == "https://sub.base-sepolia.quiknode.example/token/"


def test_wellformed_json_mainnet_ordered_list(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        chain_id=8453,
        providers_json=(
            '{"8453":[{"name":"quicknode",'
            '"url":"https://sub.base-mainnet.quiknode.example/token/"}]}'
        ),
    )
    assert _names(mgr) == [
        "alchemy", "quicknode", "base_primary", "base_llama", "base_1rpc"
    ]


# ══════════════════════════════════════════════════════════════════
#  9 — nothing bypasses the failover
# ══════════════════════════════════════════════════════════════════


def test_no_backend_module_bypasses_the_rpc_manager():
    """Every JSON-RPC request in the backend must go through RPCManager, so
    every method inherits failover. The two in-module exceptions are named and
    deliberate:
      • `_check_provider` (health probe) calls `_raw_rpc_call` directly so
        probes never feed the circuit breakers;
      • `send_raw_transaction` is primary-only by design and has zero callers
        (non-custodial — pinned by test_no_custodial_surface.py).
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in sorted(app_dir.rglob("*.py")):
        if path.name == "rpc_manager.py":
            continue
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(app_dir.parent)
        if '"jsonrpc"' in src or "'jsonrpc'" in src:
            offenders.append(f"{rel}: builds a raw JSON-RPC payload")
        if "_raw_rpc_call" in src:
            offenders.append(f"{rel}: imports the un-failed-over transport")
        if "from web3" in src or "import web3" in src:
            offenders.append(f"{rel}: talks to a node through web3.py")
    assert not offenders, "RPC calls bypassing the failover:\n" + "\n".join(offenders)


# ══════════════════════════════════════════════════════════════════
#  10 — the boot-time redundancy signal
# ══════════════════════════════════════════════════════════════════


def test_single_provider_chain_warns_at_boot(monkeypatch, caplog):
    """Nobody knew there was no redundancy. Say so on every boot."""
    settings = Settings(alchemy_api_key="", rpc_providers_json="")
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    monkeypatch.setattr(rm, "_managers", {})

    with caplog.at_level(logging.INFO):
        rm.log_provider_inventory([84532])

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "84532" in warnings[0].getMessage()
    assert "redundancy" in warnings[0].getMessage().lower()

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("base_sepolia" in m for m in infos), "inventory not logged"


def test_two_provider_chain_logs_inventory_without_warning(monkeypatch, caplog):
    settings = Settings(
        alchemy_api_key="k",
        rpc_providers_json=(
            '{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}'
        ),
    )
    monkeypatch.setattr(rm, "get_settings", lambda: settings)
    monkeypatch.setattr(rm, "_managers", {})

    with caplog.at_level(logging.INFO):
        rm.log_provider_inventory([84532])

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    inventory = [
        r.getMessage() for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any(
        "alchemy" in m and "quicknode" in m and "base_sepolia" in m
        for m in inventory
    )


# ══════════════════════════════════════════════════════════════════
#  11 — losing a provider is never silent
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lost_provider_is_reported_once_and_alerts(
    monkeypatch, bare_alert_service, caplog
):
    """A quota reset days later turned into an outage because the loss of a
    provider was never announced. Losing one must produce an ERROR plus an
    RPC_DOWN alert — exactly once, not once per call."""
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)

    def handler(request: httpx.Request) -> httpx.Response:
        if "alchemy" in str(request.url):
            return httpx.Response(429, json=ALCHEMY_MONTHLY_QUOTA)
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    with caplog.at_level(logging.INFO):
        for _ in range(6):
            assert await mgr.call("eth_blockNumber", []) == "0x64"
        for _ in range(5):
            await asyncio.sleep(0)  # drain the fire-and-forget alert task

    errors = [
        r for r in caplog.records
        if r.levelno == logging.ERROR and "rpc_manager" in r.name
    ]
    assert len(errors) == 1, f"expected exactly one 'provider lost' ERROR, got {len(errors)}"
    assert "alchemy" in errors[0].getMessage()
    assert "84532" in errors[0].getMessage()

    alerts = [
        r for r in caplog.records
        if r.name == "rsend.alerts" and "rpc_down" in r.getMessage()
    ]
    assert len(alerts) == 1, "provider loss did not reach the alerting channel"


@pytest.mark.asyncio
async def test_recovered_provider_clears_the_latch(
    monkeypatch, bare_alert_service, caplog
):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)
    alchemy = mgr._providers[0]
    alchemy.cb.recovery_timeout = 0.05

    down = {"flag": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if "alchemy" in str(request.url) and down["flag"]:
            return httpx.Response(429, json=ALCHEMY_MONTHLY_QUOTA)
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)

    for _ in range(4):
        await mgr.call("eth_blockNumber", [])
    assert alchemy.lost is True

    down["flag"] = False
    await asyncio.sleep(0.06)
    with caplog.at_level(logging.INFO):
        assert await mgr.call("eth_blockNumber", []) == "0x64"

    assert alchemy.lost is False
    assert alchemy.consecutive_failures == 0
    assert any(
        "recovered" in r.getMessage().lower() and "alchemy" in r.getMessage()
        for r in caplog.records
    ), "recovery of a lost provider was not announced"


# ══════════════════════════════════════════════════════════════════
#  12 — HTTP-level failures must be legible, not an opaque parse error
# ══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_http_429_with_non_json_body_is_a_clear_transient_error(monkeypatch):
    """A vendor edge (Cloudflare et al.) answers 429 with HTML. `resp.json()`
    then raises a JSONDecodeError that names neither the status nor the
    provider. Failover must still work AND the error must say what happened."""
    mgr = _mgr(monkeypatch, alchemy_key="")
    await _reset_breakers(mgr)
    assert _names(mgr) == ["base_sepolia"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="<html><body>429 Too Many Requests</body></html>")

    _serve(monkeypatch, handler)

    with pytest.raises(RuntimeError) as exc:
        await mgr.call("eth_blockNumber", [])
    msg = str(exc.value)
    assert not isinstance(exc.value, rm.PermanentRPCError)
    assert "429" in msg


@pytest.mark.asyncio
async def test_http_5xx_html_body_fails_over(monkeypatch):
    mgr = _mgr(
        monkeypatch,
        providers_json='{"84532":[{"name":"quicknode","url":"https://vendor2.example/rpc"}]}',
    )
    await _reset_breakers(mgr)

    def handler(request: httpx.Request) -> httpx.Response:
        if "alchemy" in str(request.url):
            return httpx.Response(502, text="<html>502 Bad Gateway</html>")
        return httpx.Response(200, json=OK_BLOCK)

    _serve(monkeypatch, handler)
    assert await mgr.call("eth_blockNumber", []) == "0x64"
