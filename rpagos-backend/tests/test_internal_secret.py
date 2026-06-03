"""
RPagos Backend — Test: internal-secret gate on /api/internal/* (H3).

The signing-guard endpoints are exempt from API-key auth and reachable via the
public Next.js proxy. They now require X-Internal-Secret == INTERNAL_PROXY_SECRET,
so only the server-side oracle can reach them (closes audit-log poisoning).

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_internal_secret.py -v
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.api.signing_routes as sr
from app.api.signing_routes import require_internal_secret, signing_router


def _req(secret_header=None):
    headers = {} if secret_header is None else {"X-Internal-Secret": secret_header}
    return SimpleNamespace(headers=headers)


def _settings(secret="", debug=False):
    return SimpleNamespace(internal_proxy_secret=secret, debug=debug)


@pytest.mark.asyncio
async def test_no_secret_in_dev_allows():
    with patch.object(sr, "get_settings", MagicMock(return_value=_settings(secret="", debug=True))):
        assert await require_internal_secret(_req()) is None


@pytest.mark.asyncio
async def test_no_secret_in_prod_blocks_503():
    with patch.object(sr, "get_settings", MagicMock(return_value=_settings(secret="", debug=False))):
        with pytest.raises(HTTPException) as exc:
            await require_internal_secret(_req())
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_correct_secret_allows():
    with patch.object(sr, "get_settings", MagicMock(return_value=_settings(secret="s3cr3t", debug=False))):
        assert await require_internal_secret(_req("s3cr3t")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "wrong-token"])
async def test_missing_or_wrong_secret_blocks_403(header):
    with patch.object(sr, "get_settings", MagicMock(return_value=_settings(secret="s3cr3t", debug=False))):
        with pytest.raises(HTTPException) as exc:
            await require_internal_secret(_req(header))
    assert exc.value.status_code == 403


def test_signing_check_rejected_without_secret_via_http():
    """End-to-end: a valid /check POST with NO X-Internal-Secret ⇒ 403 before
    the handler (no DB/Redis touched)."""
    app = FastAPI()
    app.include_router(signing_router)
    client = TestClient(app)
    valid_body = {
        "wallet": "0x" + "11" * 20,
        "recipient": "0x" + "22" * 20,
        "amount_in_wei": "1000000000000000000",
        "nonce": "0x" + "ab" * 32,
        "deadline": 9999999999,
        "chain_id": 8453,
    }
    with patch.object(sr, "get_settings", MagicMock(return_value=_settings(secret="s3cr3t", debug=False))):
        resp = client.post("/api/internal/signing/check", json=valid_body)
    assert resp.status_code == 403
