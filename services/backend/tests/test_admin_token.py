"""Admin token separation (audit finding #9).

The admin bearer (`X-Admin-Token`, gating /api/v1/audit, /admin/aml/*,
/health/config via the shared `require_admin` dependency) used to be validated
against `settings.hmac_secret` — the SAME secret that signs the inbound
frontend-callback HMAC and the audit tamper-evident chain — and compared with
`!=` (non-constant-time). One secret across two trust domains: an HMAC-secret
leak granted admin access.

Pinned here:
- admin auth uses a DEDICATED `admin_api_token` setting;
- the old `hmac_secret` value is REJECTED (the reuse is gone);
- unset/empty admin_api_token fails closed (with compare_digest, an empty
  header must never match an empty setting);
- the comparison is constant-time (`secrets.compare_digest`), and
  `require_admin` no longer references `hmac_secret`.

`hmac_secret` itself is untouched for its legitimate uses (inbound-callback
HMAC in hmac_service.py, audit chain in audit_service.py) — see
test_security.py / test_webhook_signing.py.
"""

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.audit_routes as audit_routes
from app.api.audit_routes import require_admin

ADMIN_TOKEN = "admin-token-0123456789abcdef0123456789abcdef"
HMAC_SECRET = "hmac-secret-fedcba9876543210fedcba9876543210"


@pytest.fixture
def _settings(monkeypatch):
    """Distinct admin_api_token vs hmac_secret, patched into the route module."""
    def _apply(admin_api_token: str):
        monkeypatch.setattr(
            audit_routes,
            "get_settings",
            lambda: SimpleNamespace(
                admin_api_token=admin_api_token,
                hmac_secret=HMAC_SECRET,
            ),
        )
    return _apply


@pytest.mark.asyncio
async def test_accepts_dedicated_admin_token(_settings):
    _settings(ADMIN_TOKEN)
    assert await require_admin(x_admin_token=ADMIN_TOKEN) == ADMIN_TOKEN


@pytest.mark.asyncio
async def test_rejects_hmac_secret_value(_settings):
    """The webhook/audit HMAC secret must no longer open the admin surface."""
    _settings(ADMIN_TOKEN)
    with pytest.raises(HTTPException) as exc:
        await require_admin(x_admin_token=HMAC_SECRET)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rejects_wrong_token(_settings):
    _settings(ADMIN_TOKEN)
    with pytest.raises(HTTPException) as exc:
        await require_admin(x_admin_token="nope")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unset_admin_token_fails_closed(_settings):
    """Empty setting must deny EVERYTHING — including an empty header, which
    compare_digest alone would happily match."""
    _settings("")
    for header in ("", ADMIN_TOKEN, HMAC_SECRET):
        with pytest.raises(HTTPException) as exc:
            await require_admin(x_admin_token=header)
        assert exc.value.status_code == 403, f"header={header!r}"


def test_require_admin_uses_constant_time_compare_not_hmac_secret():
    """Source guard, in the style of test_webhook_signing.py: the dependency
    compares with secrets.compare_digest and never touches hmac_secret."""
    src = inspect.getsource(require_admin)
    assert "compare_digest" in src
    assert "hmac_secret" not in src
