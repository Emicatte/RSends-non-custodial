"""
RPagos Backend — Test: production-hardening gate (H6).

The strong-tier config checks (TLS Redis/Celery, weak-DB-creds, OAuth client id,
AUTH_JWT_SECRET >= 64) were gated on ENVIRONMENT=production, which the documented
deploy never sets (it only sets DEBUG=false) — so they never ran in prod.

After the fix, `is_prod` is derived from `not DEBUG` (or ENVIRONMENT=prod), so the
strong-tier runs on the real deploy path (DEBUG=false) and fail-fasts on insecure
config. DEBUG=true (dev/tests) still skips them.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_config_hardening.py -v
"""

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import StartupValidationError, validate_settings


def _prod_settings(**over):
    """A fully-valid production Settings stand-in; override one field to break it."""
    base = dict(
        debug=False,
        signer_mode="kms",
        kms_key_id="kms-key-id",
        sweep_private_key="",
        vault_addr="",
        vault_token="",
        alchemy_api_key="alch-key",
        hmac_secret="x" * 32,
        database_url="postgresql+asyncpg://u:p@db.internal/rpagos",
        deposit_master_key="",  # empty ⇒ warning only, not an error
        alchemy_webhook_secret="whsec",
        telegram_bot_token="tg",
        redis_url="rediss://redis.internal:6379/0",
        celery_broker_url="rediss://redis.internal:6379/1",
        google_oauth_client_id="gid",
        auth_jwt_secret="a" * 64,
        internal_proxy_secret="ips",  # required in prod since H3
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("env_val", ["", "development", "dev", "staging"])
def test_strong_tier_runs_when_debug_false_without_ENVIRONMENT_prod(env_val):
    """H6 core: DEBUG=false + ENVIRONMENT not 'prod' + non-TLS Redis ⇒ BLOCK
    (previously this combination silently skipped the strong-tier)."""
    s = _prod_settings(redis_url="redis://redis.internal:6379/0")
    with patch.dict(os.environ, {"ENVIRONMENT": env_val}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_short_jwt_secret_blocks_in_prod():
    s = _prod_settings(auth_jwt_secret="too-short")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_weak_db_credentials_block_in_prod():
    s = _prod_settings(database_url="postgresql+asyncpg://rpagos:password@db/rpagos")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_valid_prod_settings_pass():
    """A fully-valid prod config must NOT raise."""
    s = _prod_settings()
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


def test_debug_true_skips_strong_tier():
    """Dev/tests (DEBUG=true): non-TLS Redis + short JWT must NOT block startup."""
    s = _prod_settings(debug=True, redis_url="redis://localhost:6379/0", auth_jwt_secret="short")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise
