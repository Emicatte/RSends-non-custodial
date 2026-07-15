"""RPC error classification — permanent (deterministic request rejection) vs
transient (availability fault).

A circuit breaker exists to protect against AVAILABILITY faults (timeouts,
5xx, network). A deterministic request rejection — invalid params, getLogs
range too large — fails identically on every retry: counting it as a provider
failure opens the circuit on a healthy provider and produces a permanent
closed→open→half_open log storm (Alchemy free tier incident, 2026-07-14).

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_rpc_classification.py -v
"""

import pytest

from app.services.circuit_breaker import CBState, CircuitBreaker
from app.services.rpc_manager import (
    PermanentRPCError,
    RPCProvider,
    _is_permanent_rpc_error,
)


# ── Classifier ────────────────────────────────────────────────────


def test_alchemy_block_range_rejection_is_permanent():
    err = {
        "code": -32600,
        "message": (
            "Under the Free tier plan, you can make eth_getLogs requests "
            "with up to a 10 block range."
        ),
    }
    assert _is_permanent_rpc_error(err)


def test_invalid_params_code_is_permanent():
    assert _is_permanent_rpc_error({"code": -32602, "message": "invalid params"})


def test_availability_errors_are_transient():
    assert not _is_permanent_rpc_error({"code": -32000, "message": "header not found"})
    assert not _is_permanent_rpc_error({"code": -32603, "message": "internal error"})
    assert not _is_permanent_rpc_error({"message": "upstream timeout"})
    assert not _is_permanent_rpc_error({})


# ── Breaker behavior ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permanent_error_never_opens_the_breaker():
    cb = CircuitBreaker(
        name="test_perm_rpc",
        failure_threshold=3,
        excluded_exceptions=(PermanentRPCError,),
    )

    async def rejected():
        raise PermanentRPCError("getLogs range too large")

    for _ in range(10):
        with pytest.raises(PermanentRPCError):
            await cb.call(rejected)

    assert cb.state == CBState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_transient_error_still_opens_the_breaker():
    cb = CircuitBreaker(
        name="test_transient_rpc",
        failure_threshold=3,
        excluded_exceptions=(PermanentRPCError,),
    )

    async def timed_out():
        raise RuntimeError("upstream timeout")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(timed_out)

    assert cb.state == CBState.OPEN


def test_provider_breakers_exclude_permanent_errors():
    """The per-provider breakers built by RPCProvider must carry the
    exclusion — this is the wiring that stops the prod log storm."""
    p = RPCProvider(name="probe", url="https://example.invalid", chain_id=84532)
    assert PermanentRPCError in p.cb.excluded_exceptions


# ── Bare -32600 (code-level) + all-permanent propagation ─────────
# Alchemy's oversized-getLogs rejection arrives as -32600; the message
# pattern caught the known wording, but a bare -32600 with any other text
# was still fed to the breaker as transient. -32600 is deterministic by
# spec (Invalid Request) — classify by CODE, not wording.


def test_bare_32600_is_permanent_regardless_of_message():
    assert _is_permanent_rpc_error({"code": -32600, "message": "invalid request"})
    assert _is_permanent_rpc_error({"code": -32600, "message": ""})


@pytest.mark.asyncio
async def test_call_propagates_permanent_when_all_providers_reject(monkeypatch):
    """When EVERY provider rejects deterministically, RPCManager.call must
    raise PermanentRPCError (not a generic RuntimeError) so the indexer's
    stall detection can surface a config/range error instead of retrying."""
    from app.services import rpc_manager as rm

    async def _always_permanent(url, method, params, timeout=10):
        raise PermanentRPCError("RPC eth_getLogs rejected: range too large")

    monkeypatch.setattr(rm, "_raw_rpc_call", _always_permanent)
    mgr = rm.RPCManager(chain_id=84532)
    with pytest.raises(PermanentRPCError):
        await mgr.call("eth_getLogs", [{}])


@pytest.mark.asyncio
async def test_call_stays_runtimeerror_when_any_failure_is_transient(monkeypatch):
    """A mixed failure (any transient error in the rotation) keeps the
    generic RuntimeError — the situation MAY self-heal, retrying is right."""
    from app.services import rpc_manager as rm

    calls = {"n": 0}

    async def _mixed(url, method, params, timeout=10):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermanentRPCError("rejected: range too large")
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(rm, "_raw_rpc_call", _mixed)
    mgr = rm.RPCManager(chain_id=8453)  # multiple default providers
    with pytest.raises(RuntimeError) as exc:
        await mgr.call("eth_getLogs", [{}])
    assert not isinstance(exc.value, PermanentRPCError)
