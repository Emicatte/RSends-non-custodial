"""
RPagos Backend — Test: wallet session-HMAC auth + legacy fallback (H4).

Verifies authenticate_request:
  - accepts a valid SINGLE-USE session-HMAC credential (MAC computed exactly as
    the JS client does), and the verified address is returned,
  - rejects a wrong MAC, a reused nonce (replay), a missing/mismatched session,
    and a stale timestamp,
  - falls back to the legacy bearer signature only while WALLET_AUTH_ALLOW_LEGACY
    is true.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_wallet_session_auth.py -v
"""

import hashlib
import hmac as _hmac
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

import app.security.auth as auth_mod
from app.security.auth import AuthError, authenticate_request

SECRET = "deadbeef" * 8  # 64-char hex string (matches client TextEncoder bytes)
ADDR = "0x" + "11" * 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mac(secret: str, nonce: str, ts: str) -> str:
    return _hmac.new(secret.encode(), f"{nonce}:{ts}".encode(), hashlib.sha256).hexdigest()


def _settings(debug=False, allow_legacy=True):
    return SimpleNamespace(debug=debug, wallet_auth_allow_legacy=allow_legacy)


def _session_req(headers: dict):
    return SimpleNamespace(headers=headers)


def _patch_session(secret=SECRET, address=ADDR, nonce_unique=True):
    """Patch the session lookup + nonce dedup used by the session-HMAC path."""
    ctx = []
    ctx.append(patch.object(auth_mod, "get_settings", MagicMock(return_value=_settings())))
    ctx.append(
        patch(
            "app.services.wallet_session.get_wallet_session",
            AsyncMock(return_value=None if secret is None else {"address": address.lower(), "secret": secret}),
        )
    )
    ctx.append(
        patch(
            "app.services.signing_rate_limit.check_nonce_uniqueness",
            AsyncMock(return_value=(nonce_unique, None if nonce_unique else "nonce_already_used")),
        )
    )
    return ctx


def _enter(ctxs):
    for c in ctxs:
        c.start()


def _exit(ctxs):
    for c in ctxs:
        c.stop()


@pytest.mark.asyncio
async def test_valid_session_hmac_accepted():
    nonce, ts = "n-1", _now()
    headers = {
        "X-Wallet-Address": ADDR,
        "X-Wallet-Session": "sess-1",
        "X-Wallet-Nonce": nonce,
        "X-Timestamp": ts,
        "X-Wallet-MAC": _mac(SECRET, nonce, ts),
    }
    ctxs = _patch_session()
    _enter(ctxs)
    try:
        verified = await authenticate_request(_session_req(headers))
    finally:
        _exit(ctxs)
    assert verified.lower() == ADDR.lower()


@pytest.mark.asyncio
async def test_wrong_mac_rejected():
    nonce, ts = "n-2", _now()
    headers = {
        "X-Wallet-Address": ADDR, "X-Wallet-Session": "sess-1",
        "X-Wallet-Nonce": nonce, "X-Timestamp": ts,
        "X-Wallet-MAC": "00" * 32,  # wrong
    }
    ctxs = _patch_session()
    _enter(ctxs)
    try:
        with pytest.raises(AuthError):
            await authenticate_request(_session_req(headers))
    finally:
        _exit(ctxs)


@pytest.mark.asyncio
async def test_reused_nonce_rejected():
    nonce, ts = "n-3", _now()
    headers = {
        "X-Wallet-Address": ADDR, "X-Wallet-Session": "sess-1",
        "X-Wallet-Nonce": nonce, "X-Timestamp": ts,
        "X-Wallet-MAC": _mac(SECRET, nonce, ts),
    }
    ctxs = _patch_session(nonce_unique=False)  # replay
    _enter(ctxs)
    try:
        with pytest.raises(AuthError):
            await authenticate_request(_session_req(headers))
    finally:
        _exit(ctxs)


@pytest.mark.asyncio
async def test_missing_session_rejected():
    nonce, ts = "n-4", _now()
    headers = {
        "X-Wallet-Address": ADDR, "X-Wallet-Session": "sess-x",
        "X-Wallet-Nonce": nonce, "X-Timestamp": ts,
        "X-Wallet-MAC": _mac(SECRET, nonce, ts),
    }
    ctxs = _patch_session(secret=None)  # session not found
    _enter(ctxs)
    try:
        with pytest.raises(AuthError):
            await authenticate_request(_session_req(headers))
    finally:
        _exit(ctxs)


@pytest.mark.asyncio
async def test_stale_timestamp_rejected():
    nonce = "n-5"
    ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    headers = {
        "X-Wallet-Address": ADDR, "X-Wallet-Session": "sess-1",
        "X-Wallet-Nonce": nonce, "X-Timestamp": ts,
        "X-Wallet-MAC": _mac(SECRET, nonce, ts),
    }
    ctxs = _patch_session()
    _enter(ctxs)
    try:
        with pytest.raises(AuthError):
            await authenticate_request(_session_req(headers))
    finally:
        _exit(ctxs)


@pytest.mark.asyncio
async def test_legacy_signature_accepted_when_enabled():
    acct = Account.create()
    ts = _now()
    sig = acct.sign_message(encode_defunct(text=f"RSends:{acct.address}:{ts}")).signature.hex()
    headers = {"X-Wallet-Address": acct.address, "X-Wallet-Signature": sig, "X-Timestamp": ts}
    with patch.object(auth_mod, "get_settings", MagicMock(return_value=_settings(allow_legacy=True))):
        verified = await authenticate_request(_session_req(headers))
    assert verified.lower() == acct.address.lower()


@pytest.mark.asyncio
async def test_legacy_signature_rejected_when_disabled():
    acct = Account.create()
    ts = _now()
    sig = acct.sign_message(encode_defunct(text=f"RSends:{acct.address}:{ts}")).signature.hex()
    headers = {"X-Wallet-Address": acct.address, "X-Wallet-Signature": sig, "X-Timestamp": ts}
    with patch.object(auth_mod, "get_settings", MagicMock(return_value=_settings(allow_legacy=False))):
        with pytest.raises(AuthError):
            await authenticate_request(_session_req(headers))
