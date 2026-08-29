"""F2 — the boot registry guard's is-not-None hole.

`_verify_one_token` (router_registry.py) reads on-chain `symbol()`/`decimals()`
for every enabled non-native token and `SystemExit`s on a mismatch. But
`_eth_call` returned `None` when the node answered `"0x"`, and BOTH mismatch
branches were guarded by `is not None`:

    if onchain_decimals is not None and onchain_decimals != pol["decimals"]:
    if onchain_symbol   is not None and onchain_symbol   != sym:

So an address with **no contract code on that chain** — the exact
cross-chain-address failure this guard exists to catch — produced empty results,
matched nothing, and was logged as `verified`.

Three properties are pinned here:

  A3 · STRUCTURAL SEPARATION. Transport failure and "the node answered `0x`" are
       distinct outcomes at the transport layer: the first RAISES, the second
       returns the `EMPTY_RESULT` sentinel. Never a shared `None`, and never
       inferred from a retry count or from the value.

  A2 · CONSENSUS BEFORE PANIC. A degraded or rate-limited provider can answer
       `{"result": "0x"}` instead of an error. An empty answer is confirmed
       across EVERY configured provider before it is believed: unanimous →
       registry mismatch → SystemExit; disagreement → provider fault → loud
       WARNING and continue. One bad vendor must not boot-loop Render.

  ·    UNREACHABLE IS UNCHANGED. An RPC outage still retries, then WARNs and
       continues. The two cases are told apart, not merged.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_registry_guard_empty_data.py -v
"""

import logging
from types import SimpleNamespace

import pytest

from app.services import router_registry as rr
from app.services.router_registry import EMPTY_RESULT

CHAIN = 84532
SYM = "USDC"
ADDR = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
POL = {"address": ADDR, "decimals": 6, "native": False, "enabled": True}

DECIMALS_6 = "0x" + "0" * 63 + "6"

# Captured at import, before the autouse fixture below collapses it to 0, so the
# production value can still be asserted on.
REAL_RECHECK_DELAY = rr._EMPTY_RECHECK_DELAY


def _patch_reads(monkeypatch, *, decimals, symbol):
    """Stub the two on-chain reads. An Exception value is raised, not returned."""
    async def _decimals(chain_id, addr):
        if isinstance(decimals, Exception):
            raise decimals
        return decimals

    async def _symbol(chain_id, addr):
        if isinstance(symbol, Exception):
            raise symbol
        return symbol

    monkeypatch.setattr(rr, "token_decimals_outcome", _decimals)
    monkeypatch.setattr(rr, "token_symbol_outcome", _symbol)


@pytest.fixture(autouse=True)
def _no_recheck_delay(monkeypatch):
    """Collapse the single-provider re-check wait so the suite does not sleep.

    Patched as a module constant at the test boundary — the same discipline as
    the chain-identity guard: `_EMPTY_RECHECK_DELAY` is not a setting, not an
    env var and not a parameter, so there is no production-reachable way to
    shorten or skip the second round.
    """
    monkeypatch.setattr(rr, "_EMPTY_RECHECK_DELAY", 0)


def _patch_providers(monkeypatch, answers):
    """Make `_chain_answers_empty_unanimously` see `answers` — a list of (name, result).

    Pass a list of rounds (a list of lists) to answer differently on the second
    poll; a single round is repeated for every call.
    """
    rounds = list(answers)
    per_round = rounds and isinstance(rounds[0], list)
    calls = {"n": 0}

    class _FakeManager:
        async def poll_providers(self, method, params, **kw):
            assert method == "eth_call"
            i = calls["n"]
            calls["n"] += 1
            if per_round:
                return list(rounds[min(i, len(rounds) - 1)])
            return list(rounds)

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", lambda cid: _FakeManager()
    )
    return calls


def _unanimously_empty(monkeypatch):
    _patch_providers(monkeypatch, [("a", "0x"), ("b", "0x")])


async def _verify(chain_id, sym, pol, *, retries=1, backoff=0):
    """Run ONE token through the level that now owns the empty verdict.

    `_verify_one_token` reports "came back empty"; `_verify_chain_tokens`
    decides what that means, once per chain. Tests asserting on the DECISION
    therefore drive the chain level with a one-token registry — same scenario,
    same assertion, one level up. Tests asserting on per-token facts (a real
    mismatch, an unreachable RPC, a match) still call `_verify_one_token`.
    """
    return await rr._verify_chain_tokens(chain_id, {sym: pol}, retries, backoff)


# ═══════════════════════════════════════════════════════════════
#  A3 — transport failure and "0x" are structurally distinct
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_empty_answer_returns_the_sentinel_not_none(monkeypatch):
    class _Rpc:
        async def call(self, method, params):
            return "0x"

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: _Rpc())

    out = await rr._eth_call_outcome(CHAIN, ADDR, "0xdeadbeef")
    assert out is EMPTY_RESULT
    assert out is not None


@pytest.mark.asyncio
async def test_transport_failure_raises_and_never_returns_the_sentinel(monkeypatch):
    class _Rpc:
        async def call(self, method, params):
            raise RuntimeError("All RPC providers failed")

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: _Rpc())

    with pytest.raises(RuntimeError):
        await rr._eth_call_outcome(CHAIN, ADDR, "0xdeadbeef")


@pytest.mark.asyncio
async def test_outcome_helpers_preserve_the_distinction(monkeypatch):
    """`decimals()` empty must survive as the sentinel all the way to the caller
    — not be flattened into a value the caller has to second-guess."""
    class _Rpc:
        def __init__(self, ret):
            self.ret = ret

        async def call(self, method, params):
            return self.ret

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", lambda cid: _Rpc("0x")
    )
    assert await rr.token_decimals_outcome(CHAIN, ADDR) is EMPTY_RESULT

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", lambda cid: _Rpc(DECIMALS_6)
    )
    assert await rr.token_decimals_outcome(CHAIN, ADDR) == 6


@pytest.mark.asyncio
async def test_legacy_helpers_keep_their_Optional_contract(monkeypatch):
    """`token_decimals_onchain`/`token_symbol_onchain` are the interface
    `scripts/verify_onchain_registry.py` uses. Their shape must not move."""
    class _Rpc:
        async def call(self, method, params):
            return "0x"

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: _Rpc())

    assert await rr.token_decimals_onchain(CHAIN, ADDR) is None
    assert await rr.token_symbol_onchain(CHAIN, ADDR) is None


# ═══════════════════════════════════════════════════════════════
#  The hole itself: successful call, empty data, providers agree
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unanimous_empty_for_an_enabled_token_is_a_mismatch(monkeypatch):
    """Every provider says `0x` → no code at the address → panic.

    This is what a Base *mainnet* USDC address filed under Base Sepolia looks
    like from the node's point of view.
    """
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    _unanimously_empty(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        await _verify(CHAIN, SYM, POL)

    assert ADDR in str(exc.value)


@pytest.mark.asyncio
async def test_empty_data_is_not_logged_as_verified(monkeypatch, caplog):
    """Before the fix this token was announced `verified`. It must not be."""
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    _unanimously_empty(monkeypatch)

    with caplog.at_level(logging.INFO, logger="app.services.router_registry"):
        with pytest.raises(SystemExit):
            await _verify(CHAIN, SYM, POL)

    assert not any("verified" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]


# ═══════════════════════════════════════════════════════════════
#  A2 — one degraded provider must not boot-loop the service
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_provider_disagreement_warns_and_does_NOT_exit(monkeypatch, caplog):
    """One provider answers `0x`, another returns real data → provider fault.

    Render restarts a crashed process, so turning a single rate-limited vendor
    into a SystemExit is a boot loop, not a safety property.
    """
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    _patch_providers(monkeypatch, [("degraded", "0x"), ("healthy", DECIMALS_6)])

    with caplog.at_level(logging.WARNING, logger="app.services.router_registry"):
        await _verify(CHAIN, SYM, POL)

    assert any("PROVIDER FAULT" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]


@pytest.mark.asyncio
async def test_no_provider_answers_the_confirmation_does_not_exit(monkeypatch, caplog):
    """If the confirmation round itself cannot reach anyone, that is transport —
    the unreachable branch, not a registry verdict."""
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    _patch_providers(monkeypatch, [("a", RuntimeError("down")), ("b", RuntimeError("down"))])

    with caplog.at_level(logging.WARNING, logger="app.services.router_registry"):
        await _verify(CHAIN, SYM, POL)

    assert any("PROVIDER FAULT" in r.message for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers, expected",
    [
        ([("a", "0x"), ("b", "0x")], True),
        ([("a", "0x"), ("b", None)], True),
        ([("a", "0x"), ("b", DECIMALS_6)], False),
        ([("a", DECIMALS_6)], False),
        ([("a", RuntimeError("x"))], None),
        ([("a", RuntimeError("x")), ("b", "0x")], True),
    ],
    ids=["all-empty", "empty-and-null", "one-has-data", "single-has-data",
         "all-errored", "one-errored-rest-empty"],
)
async def test_chain_answers_empty_unanimously_verdicts(monkeypatch, answers, expected):
    """`_chain_answers_empty_unanimously` in isolation. Providers that error are not votes —
    they neither confirm nor refute; only answers count."""
    _patch_providers(monkeypatch, answers)
    assert await rr._chain_answers_empty_unanimously(CHAIN, probe_token=ADDR) is expected


# ── Single-provider chains: time separation replaces provider separation ──

@pytest.mark.asyncio
async def test_single_provider_empty_on_both_attempts_exits(monkeypatch):
    """One provider, empty twice → an address with no code does not heal.

    Base Sepolia ships exactly one default provider, so "every provider agrees"
    is one vendor and proves nothing on its own. The second round, taken after a
    delay, is what makes the verdict mean something.
    """
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    calls = _patch_providers(monkeypatch, [[("solo", "0x")], [("solo", "0x")]])

    with pytest.raises(SystemExit) as exc:
        await _verify(CHAIN, SYM, POL)

    assert ADDR in str(exc.value)
    assert calls["n"] == 2, "the second round must actually be taken"


@pytest.mark.asyncio
async def test_single_provider_empty_then_data_warns_and_continues(monkeypatch, caplog):
    """One provider, empty then real data → it was rate-limited, not wrong.

    This is the boot loop the amendment exists to prevent: without the second
    round, one throttled vendor answering `0x` is enough to SystemExit, and
    Render restarts the process straight back into it.
    """
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    calls = _patch_providers(
        monkeypatch, [[("solo", "0x")], [("solo", DECIMALS_6)]]
    )

    with caplog.at_level(logging.WARNING, logger="app.services.router_registry"):
        await _verify(CHAIN, SYM, POL)

    assert calls["n"] == 2
    assert any("PROVIDER FAULT" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]


@pytest.mark.asyncio
async def test_two_answers_do_not_trigger_a_second_round(monkeypatch):
    """Provider separation available → no need to spend time on top of it."""
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    calls = _patch_providers(monkeypatch, [("a", "0x"), ("b", "0x")])

    with pytest.raises(SystemExit):
        await _verify(CHAIN, SYM, POL)

    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_non_empty_first_round_is_never_re_polled(monkeypatch):
    """Only a True verdict can end in SystemExit, so only True is re-checked.
    A second round on False/None would delay a boot that already continues."""
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    calls = _patch_providers(monkeypatch, [("solo", DECIMALS_6)])

    await _verify(CHAIN, SYM, POL)

    assert calls["n"] == 1


def test_recheck_delay_is_a_real_wait_and_has_no_config_surface():
    """The delay must be non-zero in production, and unreachable from config."""
    import inspect

    from app import config as config_mod

    assert REAL_RECHECK_DELAY > 0, "the second round must be separated in TIME"

    src = (
        inspect.getsource(rr._chain_answers_empty_unanimously)
        + inspect.getsource(rr._poll_empty_once)
        + inspect.getsource(rr._resolve_empty_chain)
        + inspect.getsource(rr._verify_chain_tokens)
    )
    for forbidden in ("get_settings", "os.environ", "getenv", "settings."):
        assert forbidden not in src, f"confirmation reads configuration: {forbidden!r}"

    params = inspect.signature(rr._chain_answers_empty_unanimously).parameters
    assert list(params) == ["chain_id", "probe_token"], list(params)
    # The chain is the subject; the token is a keyword-only instrument.
    assert params["probe_token"].kind is inspect.Parameter.KEYWORD_ONLY

    config_src = inspect.getsource(config_mod).lower()
    for token in ("recheck_delay", "empty_recheck", "registry_guard"):
        assert token not in config_src, f"config.py grew a {token!r} surface"


def _five_empty_tokens(monkeypatch):
    """A chain whose whole enabled registry comes back empty."""
    syms = {
        s: {"address": "0x" + f"{i:02x}" * 20, "decimals": 6,
            "native": False, "enabled": True}
        for i, s in enumerate(["USDC", "USDT", "DAI", "EURC", "WBTC"], start=1)
    }
    monkeypatch.setattr(rr, "FEE_POLICY", {"base": syms})
    monkeypatch.setattr(
        rr, "get_settings",
        lambda: SimpleNamespace(
            rsends_router_addresses={"8453": "0x" + "ab" * 20},
            rsends_router_v2_addresses={},
        ),
    )
    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)


@pytest.mark.asyncio
async def test_cross_check_runs_once_per_chain_not_once_per_token(monkeypatch):
    """THE HOIST. Whether the provider set is answering coherently is a property
    of the CHAIN, not of a token — a degraded provider returns empty for every
    token in the registry, so asking per token multiplied one 3s wait by the
    registry size (measured: 5 tokens = 15.05s of pure sleep).

    Two providers that disagree → PROVIDER FAULT, no exit, loop completes. The
    counter is on the poll itself, so this measures invocations, not timing.
    """
    _five_empty_tokens(monkeypatch)
    calls = _patch_providers(monkeypatch, [("a", "0x"), ("b", DECIMALS_6)])

    await rr.verify_enabled_tokens_onchain(retries=1, backoff=0)

    assert calls["n"] == 1, (
        f"cross-check ran {calls['n']} times for one chain — it must run once"
    )


@pytest.mark.asyncio
async def test_unanimous_empty_still_exits_on_the_first_empty_token(monkeypatch):
    """The hoist must not soften the verdict: one cross-check, still SystemExit,
    still naming the first token that came back empty."""
    _five_empty_tokens(monkeypatch)
    calls = _patch_providers(monkeypatch, [("a", "0x"), ("b", "0x")])

    with pytest.raises(SystemExit) as exc:
        await rr.verify_enabled_tokens_onchain(retries=1, backoff=0)

    assert calls["n"] == 1
    assert "0x" + "01" * 20 in str(exc.value), str(exc.value)


@pytest.mark.asyncio
async def test_confirmation_polls_every_provider_not_the_healthy_subset(monkeypatch):
    """The provider excluded for being unhealthy is exactly the one whose answer
    would change the verdict — so the confirmation must not pass a subset."""
    seen = {}

    class _FakeManager:
        async def poll_providers(self, method, params, **kw):
            seen.update(kw)
            return [("a", "0x")]

    monkeypatch.setattr(
        "app.services.rpc_manager.get_rpc_manager", lambda cid: _FakeManager()
    )
    await rr._chain_answers_empty_unanimously(CHAIN, probe_token=ADDR)

    assert "providers" not in seen, "must not restrict the poll to a subset"


# ═══════════════════════════════════════════════════════════════
#  Unchanged: an unreachable node still degrades
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rpc_unreachable_still_warns_and_continues(monkeypatch, caplog):
    """An RPC outage must NOT become a crash-loop. Deliberately preserved."""
    _patch_reads(
        monkeypatch,
        decimals=RuntimeError("All RPC providers failed"),
        symbol=RuntimeError("All RPC providers failed"),
    )

    with caplog.at_level(logging.WARNING, logger="app.services.router_registry"):
        await rr._verify_one_token(CHAIN, SYM, POL, retries=2, backoff=0)

    assert any("could not verify" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]


@pytest.mark.asyncio
async def test_unreachable_and_empty_are_distinguishable(monkeypatch):
    """The point of F2 in one test: same token, same guard, two outcomes.

    Before the fix both paths ended in "continue" — one via the WARNING, one via
    the silent `verified`.
    """
    _patch_reads(monkeypatch, decimals=RuntimeError("down"), symbol=RuntimeError("down"))
    await rr._verify_one_token(CHAIN, SYM, POL, retries=1, backoff=0)  # tolerated

    _patch_reads(monkeypatch, decimals=EMPTY_RESULT, symbol=EMPTY_RESULT)
    _unanimously_empty(monkeypatch)
    with pytest.raises(SystemExit):
        await _verify(CHAIN, SYM, POL)


# ═══════════════════════════════════════════════════════════════
#  Guard the guard: real mismatches and real matches unchanged
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_real_decimals_mismatch_still_panics(monkeypatch):
    _patch_reads(monkeypatch, decimals=18, symbol=SYM)
    with pytest.raises(SystemExit):
        await rr._verify_one_token(CHAIN, SYM, POL, retries=1, backoff=0)


@pytest.mark.asyncio
async def test_real_symbol_mismatch_still_panics(monkeypatch):
    _patch_reads(monkeypatch, decimals=6, symbol="DAI")
    with pytest.raises(SystemExit):
        await rr._verify_one_token(CHAIN, SYM, POL, retries=1, backoff=0)


@pytest.mark.asyncio
async def test_matching_token_still_passes(monkeypatch):
    _patch_reads(monkeypatch, decimals=6, symbol=SYM)
    await rr._verify_one_token(CHAIN, SYM, POL, retries=1, backoff=0)


@pytest.mark.asyncio
async def test_live_contract_with_undecodable_symbol_is_still_tolerated(monkeypatch):
    """Narrow carve-out, stated on purpose: `decimals()` answering proves there
    IS code at the address. A `symbol()` that decodes to nothing is a legacy
    bytes32/odd-token quirk, not a wrong-chain signal. The wrong-chain signal is
    `decimals()` coming back empty, which is handled above.
    """
    _patch_reads(monkeypatch, decimals=6, symbol=None)
    await rr._verify_one_token(CHAIN, SYM, POL, retries=1, backoff=0)


@pytest.mark.asyncio
async def test_empty_symbol_with_live_decimals_does_not_trigger_consensus(monkeypatch):
    """`symbol()` empty while `decimals()` answered must not even reach the
    confirmation round — there is code at the address, so it is not the
    wrong-chain case."""
    _patch_reads(monkeypatch, decimals=6, symbol=EMPTY_RESULT)

    def _boom(*a, **k):
        raise AssertionError("consensus confirmation must not run here")

    monkeypatch.setattr(rr, "_chain_answers_empty_unanimously", _boom)
    await _verify(CHAIN, SYM, POL)
