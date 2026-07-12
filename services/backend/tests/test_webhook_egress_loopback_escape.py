"""E2E loopback escape for the webhook SSRF egress guard.

The Anvil money-path E2E points a merchant webhook at a plain-http loopback
receiver (`http://127.0.0.1:<port>/webhook`); since the Phase E hardening,
delivery-time `check_webhook_egress` blocks it (`scheme_not_https`) and the E2E
has failed on every merge. Escape hatch, mirroring RSEND_DEV_AUTH_BYPASS:

- `RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS=1` lets ONLY loopback targets
  (127.0.0.0/8, ::1, localhost) through, any scheme. Everything else keeps the
  full guard: private/link-local ranges still blocked, non-loopback http still
  `scheme_not_https`.
- `validate_dev_flags` refuses startup when the flag is set outside
  ENVIRONMENT=development/test — it can never be live in prod posture.
"""

import pytest

from app.config import get_settings, validate_dev_flags
from app.services.webhook_service import check_webhook_egress

FLAG = "RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS"


# ── default posture (flag unset) unchanged ─────────────────────────────────


@pytest.mark.asyncio
async def test_loopback_blocked_by_default(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    assert await check_webhook_egress("http://127.0.0.1:60597/webhook") == "scheme_not_https"
    assert await check_webhook_egress("https://127.0.0.1/webhook") == "private_or_reserved_ip"


# ── flag set: loopback-only escape ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_allows_loopback_any_scheme(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    assert await check_webhook_egress("http://127.0.0.1:60597/webhook") is None
    assert await check_webhook_egress("http://localhost:8080/webhook") is None
    assert await check_webhook_egress("https://[::1]:8443/webhook") is None


@pytest.mark.asyncio
async def test_flag_does_not_widen_beyond_loopback(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    # Non-loopback http: still scheme-blocked.
    assert await check_webhook_egress("http://example.com/webhook") == "scheme_not_https"
    # Private/link-local/IPv4-mapped: still IP-blocked.
    assert await check_webhook_egress("https://10.0.0.5/webhook") == "private_or_reserved_ip"
    assert await check_webhook_egress("https://169.254.169.254/webhook") == "private_or_reserved_ip"
    assert await check_webhook_egress("https://[::ffff:10.0.0.5]/webhook") == "private_or_reserved_ip"


# ── startup refusal outside development/test ───────────────────────────────


def test_flag_refused_in_prod_posture(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match=FLAG):
        validate_dev_flags(get_settings())


@pytest.mark.parametrize("env", ["development", "test"])
def test_flag_allowed_in_dev_and_test(monkeypatch, env):
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("ENVIRONMENT", env)
    validate_dev_flags(get_settings())  # must not raise
