"""
RPagos Backend — Test: signing-guard AML amount derivation + hybrid gate (C2).

Verifies that the signing guard:
  - derives the EUR value from the SIGNED amount (amount_in_wei) server-side
    and passes it to full_aml_check (not the client fiat field / not 0.0),
  - applies the HYBRID policy: block on sanctions, DAC8 KYC (>€15k monthly),
    or AML-data-unavailable (fail-closed); daily/velocity/structuring are
    ALERT-ONLY and do NOT block,
  - fails closed when the transfer can't be valued (unknown token / no price).

No DB/Redis: every dependency is mocked, so the endpoint is called directly.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_signing_guard_aml.py -v
"""

import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.api.signing_routes as sr
from app.api.signing_routes import SigningCheckRequest, signing_check

ETH = SimpleNamespace(decimals=18, coingecko_id="ethereum", symbol="ETH")
ONE_ETH = str(10**18)  # passes the guard's wei bounds [1e12, 1e23]


def _body(amount_in_wei=ONE_ETH, token_in="0x0000000000000000000000000000000000000000"):
    return SigningCheckRequest(
        wallet="0x" + "11" * 20,
        recipient="0x" + "22" * 20,
        token_in=token_in,
        amount_in_wei=amount_in_wei,
        nonce="0x" + "ab" * 32,
        deadline=int(time.time()) + 300,
        chain_id=8453,
        ip_address="1.2.3.4",
        contract_address="0x" + "33" * 20,
    )


def _aml(approved=True, risk="low", alerts=None, requires_kyc=False):
    return SimpleNamespace(
        approved=approved,
        risk_level=risk,
        alerts=alerts or [],
        requires_kyc=requires_kyc,
        requires_manual_review=False,
        details="",
    )


def _patches(aml_result, *, get_token_ret=ETH, eur=1785.0):
    """Patch every external dependency of signing_check. Returns (stack, full_aml_check_mock, get_eur_value_mock)."""
    fac = AsyncMock(return_value=aml_result)
    eur_mock = AsyncMock(return_value=eur)
    stack = ExitStack()
    e = stack.enter_context
    e(patch("app.services.aml_service.is_blacklisted", AsyncMock(return_value=(False, None))))
    e(patch("app.services.aml_service.full_aml_check", fac))
    e(patch("app.tokens.registry.get_token", MagicMock(return_value=get_token_ret)))
    e(patch("app.services.price_service.get_eur_value", eur_mock))
    e(patch("app.services.signing_rate_limit.check_signing_rate_limit", AsyncMock(return_value=(True, None))))
    e(patch("app.services.signing_rate_limit.check_nonce_uniqueness", AsyncMock(return_value=(True, None))))
    e(patch("app.security.trusted_proxy.get_real_client_ip", MagicMock(return_value="1.2.3.4")))
    e(patch.object(sr, "_record_signing_denied", AsyncMock()))
    return stack, fac, eur_mock


@pytest.mark.asyncio
async def test_amount_eur_derived_from_signed_wei():
    """The real EUR value (from amount_in_wei) reaches full_aml_check, not 0.0."""
    stack, fac, eur_mock = _patches(_aml())
    with stack:
        resp = await signing_check(_body(), MagicMock())
    assert resp.allowed is True
    eur_mock.assert_awaited_once_with("ethereum", 1.0)        # 1e18 wei / 10^18
    assert fac.await_args.kwargs["amount_eur"] == 1785.0       # NOT 0.0
    assert fac.await_args.kwargs["token_symbol"] == "ETH"


@pytest.mark.asyncio
async def test_dac8_kyc_blocks():
    """DAC8 monthly (>€15k, requires_kyc) BLOCKS the signature."""
    stack, _, _ = _patches(_aml(risk="high", alerts=["threshold_monthly"], requires_kyc=True))
    with stack:
        resp = await signing_check(_body(), MagicMock())
    assert resp.allowed is False
    assert resp.reason == "aml_kyc_required"


@pytest.mark.asyncio
async def test_daily_threshold_is_alert_only():
    """Daily/velocity/structuring high-risk (with alert) does NOT block — alert-only."""
    stack, _, _ = _patches(_aml(risk="high", alerts=["threshold_daily"], requires_kyc=False))
    with stack:
        resp = await signing_check(_body(), MagicMock())
    assert resp.allowed is True


@pytest.mark.asyncio
async def test_data_unavailable_fails_closed():
    """risk='high' with NO threshold alert == AML counters down → fail-closed block."""
    stack, _, _ = _patches(_aml(risk="high", alerts=[], requires_kyc=False))
    with stack:
        resp = await signing_check(_body(), MagicMock())
    assert resp.allowed is False
    assert resp.reason == "aml_data_unavailable"


@pytest.mark.asyncio
async def test_unvaluable_token_fails_closed():
    """Unknown token (cannot value) → fail-closed, full_aml_check never called."""
    stack, fac, _ = _patches(_aml(), get_token_ret=None)
    with stack:
        resp = await signing_check(
            _body(token_in="0x" + "ab" * 20), MagicMock()
        )
    assert resp.allowed is False
    assert resp.reason == "aml_amount_unavailable"
    fac.assert_not_awaited()
