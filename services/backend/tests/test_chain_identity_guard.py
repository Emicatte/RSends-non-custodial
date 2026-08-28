"""F1 — chain identity is PROVEN, not declared.

Today nothing in `services/backend/app` ever calls `eth_chainId`. A watcher's
`chain_id` is a key of `RSENDS_ROUTER_ADDRESSES_JSON` and is trusted end to end:
it selects the RPC endpoint, keys the cursor, classifies test-vs-live and is
folded into the on-chain invoice id. A provider that serves a *different* chain
is indistinguishable from a correct one — provider health is `eth_blockNumber`
plus relative lag between the providers of the same declared id, so a whole
provider set on the wrong network agrees with itself and is marked healthy.

Contract pinned here:

  - `assert_chain_identity(chain_id)` asks EVERY configured provider for that
    chain `eth_chainId` and raises `ChainIdentityError` unless every one of them
    answers exactly `chain_id`. Not the first healthy one — failover would
    otherwise silently adopt a wrong-chain node.
  - Every failure mode is the same failure: mismatch, transport error, timeout,
    malformed result, and "no providers configured" all raise. There is no
    degrade, no disable-and-continue, no default chain.
  - A success is cached per `(provider_url, chain_id)` for the process lifetime
    (the genesis of a chain does not move). A failure is NEVER cached in a way
    that lets a later call through.
  - `PaymentWatcher.start()` runs it BEFORE the loop is scheduled and therefore
    before any cursor is read or written.
  - `verify_chain_identity_for_boot(chain_ids)` is the boot-guard wrapper and
    raises `SystemExit`, matching `verify_enabled_tokens_onchain`.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_chain_identity_guard.py -v
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.services import rpc_manager as rm
from app.services.payment_indexer import PaymentWatcher

# 8453 == 0x2105 (Base mainnet) · 84532 == 0x14a34 (Base Sepolia)
BASE_MAINNET = 8453
BASE_SEPOLIA = 84532
HEX_BASE_MAINNET = "0x2105"
HEX_BASE_SEPOLIA = "0x14a34"

ROUTER = "0x" + "a" * 40


@pytest.fixture(autouse=True)
def _isolate_rpc_registry(monkeypatch):
    """Fresh manager registry + empty identity cache for every test.

    Both are process-global by design (the cache is the point of F1), so they
    have to be reset or one test's proof leaks into the next one's assertion.
    """
    monkeypatch.setattr(rm, "_managers", {})
    # raising=False so the RED phase fails inside each test, on the assertion
    # that names the missing behaviour — not as one opaque setup error.
    monkeypatch.setattr(rm, "_CHAIN_ID_VERIFIED", set(), raising=False)
    # No Alchemy key and no RPC_PROVIDERS_JSON → the provider list for 8453 is
    # exactly the three public defaults, in a known order.
    monkeypatch.setattr(
        rm, "get_settings",
        lambda: Settings(alchemy_api_key="", rpc_providers_json=""),
    )


def _provider_urls(chain_id: int) -> list[str]:
    return [p.url for p in rm.get_rpc_manager(chain_id)._providers]


def _answer(mapping, *, default=None):
    """Build a fake `_raw_rpc_call` that answers eth_chainId per provider URL.

    A mapping value may be a string (the hex result), an Exception instance
    (raised), or None (returned verbatim — the malformed-response case).
    """
    calls = []

    async def _fake(url, method, params, timeout=rm.REQUEST_TIMEOUT):
        calls.append((url, method))
        assert method == "eth_chainId", f"unexpected probe method {method!r}"
        value = mapping.get(url, default)
        if isinstance(value, Exception):
            raise value
        return value

    _fake.calls = calls
    return _fake


# ═══════════════════════════════════════════════════════════════
#  ACCEPTANCE 1 — watcher for 8453 against a node serving 84532
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_watcher_start_refuses_when_node_serves_another_chain(monkeypatch):
    """Declared 8453, node answers 84532 → startup refuses.

    This is the whole point of F1: today this watcher starts, indexes Base
    Sepolia blocks under the mainnet cursor key, and stamps every settlement
    `environment="live"`.
    """
    monkeypatch.setattr(
        rm, "_raw_rpc_call", _answer({}, default=HEX_BASE_SEPOLIA)
    )
    monkeypatch.setattr(PaymentWatcher, "_loop", lambda self: asyncio.sleep(0))

    w = PaymentWatcher(chain_id=BASE_MAINNET, router_address=ROUTER)
    with pytest.raises(rm.ChainIdentityError) as exc:
        await w.start()

    assert "8453" in str(exc.value) and "84532" in str(exc.value)
    # BEFORE the loop is scheduled → no task, and therefore no cursor read.
    assert w._task is None
    assert w._running is False


# ═══════════════════════════════════════════════════════════════
#  ACCEPTANCE 2 — the SECOND provider is the wrong chain
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_wrong_chain_on_a_non_first_provider_still_refuses(monkeypatch):
    """Provider #1 is correct, provider #2 serves another chain → refuse.

    Checking only the first healthy provider would let failover adopt the wrong
    node the moment provider #1 blips — silently, because nothing downstream
    re-checks. Every configured provider must be proven.
    """
    urls = _provider_urls(BASE_MAINNET)
    assert len(urls) >= 2, f"need >=2 providers for this test, got {urls}"

    fake = _answer(
        {urls[0]: HEX_BASE_MAINNET, urls[1]: HEX_BASE_SEPOLIA},
        default=HEX_BASE_MAINNET,
    )
    monkeypatch.setattr(rm, "_raw_rpc_call", fake)

    with pytest.raises(rm.ChainIdentityError) as exc:
        await rm.assert_chain_identity(BASE_MAINNET)

    assert urls[1] in str(exc.value)
    # It genuinely probed past the first provider.
    assert urls[1] in [u for u, _ in fake.calls]


@pytest.mark.asyncio
async def test_all_providers_are_probed_when_all_are_correct(monkeypatch):
    urls = _provider_urls(BASE_MAINNET)
    fake = _answer({}, default=HEX_BASE_MAINNET)
    monkeypatch.setattr(rm, "_raw_rpc_call", fake)

    await rm.assert_chain_identity(BASE_MAINNET)

    assert sorted({u for u, _ in fake.calls}) == sorted(urls)


# ═══════════════════════════════════════════════════════════════
#  Every failure mode is the SAME failure
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "value, label",
    [
        (httpx.ConnectError("refused"), "transport-error"),
        (httpx.ReadTimeout("timed out"), "timeout"),
        (RuntimeError("RPC eth_chainId got a non-JSON response (HTTP 429)"), "vendor-html"),
        (None, "null-result"),
        ("", "empty-string-result"),
        ("not-hex", "malformed-result"),
        ({"unexpected": "shape"}, "non-string-result"),
    ],
)
@pytest.mark.asyncio
async def test_unprovable_chain_is_a_failure_not_a_degradation(
    monkeypatch, value, label
):
    """An unproven chain is not a safe chain.

    This deliberately inverts the `check_webhook_egress` convention, where a DNS
    failure is *not* forbidden (an unreachable host cannot reach anything
    internal). Here the opposite holds, and `_verify_one_token`'s
    unreachable→WARNING→continue is the precedent NOT to copy.
    """
    monkeypatch.setattr(rm, "_raw_rpc_call", _answer({}, default=value))

    with pytest.raises(rm.ChainIdentityError):
        await rm.assert_chain_identity(BASE_MAINNET)


@pytest.mark.asyncio
async def test_chain_with_no_configured_providers_refuses(monkeypatch):
    """Zero providers → the chain cannot be proven → fail closed.

    `RPCManager` builds an empty provider list for any chain outside the Alchemy
    table and `_DEFAULT_PROVIDERS`; today that surfaces only later, as a generic
    "all RPC providers failed" at first use.
    """
    monkeypatch.setattr(rm, "_raw_rpc_call", _answer({}, default=HEX_BASE_MAINNET))

    unrouted = 999_999
    assert _provider_urls(unrouted) == []
    with pytest.raises(rm.ChainIdentityError):
        await rm.assert_chain_identity(unrouted)


# ═══════════════════════════════════════════════════════════════
#  Caching: successes stick, failures never do
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_success_is_cached_per_provider_url_and_chain(monkeypatch):
    fake = _answer({}, default=HEX_BASE_MAINNET)
    monkeypatch.setattr(rm, "_raw_rpc_call", fake)

    await rm.assert_chain_identity(BASE_MAINNET)
    first_round = len(fake.calls)
    await rm.assert_chain_identity(BASE_MAINNET)

    assert len(fake.calls) == first_round, "second call must hit the cache"
    assert all(
        (u, BASE_MAINNET) in rm._CHAIN_ID_VERIFIED for u in _provider_urls(BASE_MAINNET)
    )


@pytest.mark.asyncio
async def test_failure_is_never_cached_as_a_pass(monkeypatch):
    """A failed probe must not leave anything behind that a later call reads as
    proof. Re-asking must re-probe and must fail again."""
    monkeypatch.setattr(
        rm, "_raw_rpc_call", _answer({}, default=httpx.ConnectError("down"))
    )
    with pytest.raises(rm.ChainIdentityError):
        await rm.assert_chain_identity(BASE_MAINNET)

    assert rm._CHAIN_ID_VERIFIED == set()

    with pytest.raises(rm.ChainIdentityError):
        await rm.assert_chain_identity(BASE_MAINNET)


@pytest.mark.asyncio
async def test_cache_is_keyed_by_chain_not_only_by_url(monkeypatch):
    """Proving a URL for one chain must not vouch for it on another."""
    monkeypatch.setattr(rm, "_raw_rpc_call", _answer({}, default=HEX_BASE_MAINNET))
    await rm.assert_chain_identity(BASE_MAINNET)

    shared_url = _provider_urls(BASE_MAINNET)[0]
    assert (shared_url, BASE_SEPOLIA) not in rm._CHAIN_ID_VERIFIED


# ═══════════════════════════════════════════════════════════════
#  Boot site — SystemExit, matching verify_enabled_tokens_onchain
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_boot_guard_raises_SystemExit_on_mismatch(monkeypatch):
    monkeypatch.setattr(rm, "_raw_rpc_call", _answer({}, default=HEX_BASE_SEPOLIA))

    with pytest.raises(SystemExit):
        await rm.verify_chain_identity_for_boot([BASE_MAINNET])


@pytest.mark.asyncio
async def test_boot_guard_is_a_noop_for_no_chains(monkeypatch):
    """No configured chains → nothing to prove (mirrors the indexer's own
    no-router no-op). It must not invent a default chain to check."""
    fake = _answer({}, default=HEX_BASE_MAINNET)
    monkeypatch.setattr(rm, "_raw_rpc_call", fake)

    await rm.verify_chain_identity_for_boot([])

    assert fake.calls == []


@pytest.mark.asyncio
async def test_boot_guard_passes_when_every_chain_checks_out(monkeypatch):
    monkeypatch.setattr(
        rm, "_raw_rpc_call",
        _answer(
            {u: HEX_BASE_SEPOLIA for u in _provider_urls(BASE_SEPOLIA)},
            default=HEX_BASE_MAINNET,
        ),
    )
    await rm.verify_chain_identity_for_boot([BASE_MAINNET, BASE_SEPOLIA])


def test_no_configuration_surface_can_disable_chain_identity():
    """A4 — there must be no way to turn this off from config.

    Precedent: `security/auth.py:131-138` returns a checksummed address and
    RETURNS before ever reaching the regex gate at `:142`, because someone
    wanted a debug bypass. The bypass is prod-safe only by accident of another
    check. A guard with an off switch is a guard that will be off.

    Tests stub this by patching the module-level function at the test boundary
    (see `test_depth_finality.py`), which leaves no production-reachable path.
    """
    import inspect

    from app import config as config_mod

    # Signature: the chain id and a transport timeout. Nothing else, and no
    # boolean whose default could turn the guard off.
    params = inspect.signature(rm.assert_chain_identity).parameters
    assert list(params) == ["chain_id", "timeout"], list(params)
    for p in params.values():
        assert not isinstance(p.default, bool), f"{p.name} is a boolean switch"

    boot_params = inspect.signature(rm.verify_chain_identity_for_boot).parameters
    assert list(boot_params) == ["chain_ids"], list(boot_params)

    # The guard reads no configuration at all — not settings, not the env.
    src = (
        inspect.getsource(rm.assert_chain_identity)
        + inspect.getsource(rm.verify_chain_identity_for_boot)
    )
    for forbidden in ("get_settings", "os.environ", "getenv", "settings."):
        assert forbidden not in src, f"the guard reads configuration: {forbidden!r}"

    # And config.py has not grown a knob for it.
    config_src = inspect.getsource(config_mod).lower()
    for token in ("chain_identity", "chain_id_check", "skip_chain", "verify_chain"):
        assert token not in config_src, f"config.py grew a {token!r} surface"


def test_watcher_start_has_no_skip_parameter():
    """The call site must not be bypassable either."""
    import inspect

    params = inspect.signature(PaymentWatcher.start).parameters
    assert list(params) == ["self"], list(params)


def test_main_boot_sequence_calls_the_chain_identity_guard():
    """The guard has to be WIRED, not merely defined.

    `main.py` already refuses to start on a token-metadata mismatch
    (`verify_enabled_tokens_onchain`); the chain-identity guard sits alongside
    it. A guard nobody calls is the `isTronFeeRouterAvailable()` failure mode.
    """
    import inspect

    import app.main as main_mod

    src = inspect.getsource(main_mod)
    assert "verify_chain_identity_for_boot" in src, (
        "main.py must invoke the chain-identity boot guard alongside "
        "verify_enabled_tokens_onchain"
    )
