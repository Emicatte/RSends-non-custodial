"""
RPagos Backend — Test: admin-token auth required on ledger + AML admin (H1+H2).

Proves that the previously-public endpoints now REQUIRE the X-Admin-Token gate:
  - all 5 ledger_routes GET handlers (H1),
  - all 4 /admin/aml/* handlers (H2),
reject requests without a valid admin token (no longer status 200 / data leak).
The oracle endpoint /api/v1/aml/check is intentionally NOT gated.

Reject path needs no DB: the route dependency (require_admin) runs before the
handler, so a missing X-Admin-Token short-circuits with 422 (missing header).

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_admin_auth_required.py -v
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.aml_routes import aml_router
from app.api.audit_routes import require_admin
from app.api.ledger_routes import ledger_router

app = FastAPI()
app.include_router(ledger_router)
app.include_router(aml_router)
client = TestClient(app)

# (method, path) for every endpoint that must now require the admin token.
PROTECTED = [
    ("GET", "/api/v1/ledger/export/csv"),
    ("GET", "/api/v1/ledger/export/json"),
    ("GET", "/api/v1/ledger/integrity"),
    ("GET", "/api/v1/ledger/balance/00000000-0000-0000-0000-000000000000"),
    ("GET", "/api/v1/ledger/accounts"),
    ("GET", "/admin/aml/alerts"),
    ("POST", "/admin/aml/alerts/1/review"),
    ("POST", "/admin/aml/sanctions/update"),
    ("GET", "/admin/aml/stats"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_endpoint_rejects_without_admin_token(method, path):
    """No X-Admin-Token ⇒ rejected (not 200) BEFORE any handler/DB access."""
    resp = client.request(method, path)
    assert resp.status_code != 200
    assert resp.status_code in (401, 403, 422)


def test_oracle_aml_check_is_not_admin_gated():
    """/api/v1/aml/check must NOT require the admin token (oracle calls it)."""
    # Missing admin token must NOT be the failure mode here. With no body it
    # 422s on the body (not on a missing X-Admin-Token), proving no admin gate.
    resp = client.post("/api/v1/aml/check")
    body = resp.text.lower()
    assert "x-admin-token" not in body


@pytest.mark.asyncio
async def test_require_admin_accepts_correct_token():
    settings = MagicMock(hmac_secret="s3cr3t-admin")
    with patch("app.api.audit_routes.get_settings", MagicMock(return_value=settings)):
        assert await require_admin(x_admin_token="s3cr3t-admin") == "s3cr3t-admin"


@pytest.mark.asyncio
async def test_require_admin_rejects_wrong_token():
    settings = MagicMock(hmac_secret="s3cr3t-admin")
    with patch("app.api.audit_routes.get_settings", MagicMock(return_value=settings)):
        with pytest.raises(HTTPException) as exc:
            await require_admin(x_admin_token="wrong")
    assert exc.value.status_code == 403
