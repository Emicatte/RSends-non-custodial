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
        email_dev_mode=False,  # prod sends real email
        app_url="https://app.rsends.io",  # required for verification links in prod
        wallet_auth_allow_legacy=False,  # H4: legacy replayable bearer off in prod
        oracle_signer_mode="kms",  # M1-A: oracle key in HSM, not web tier
        oracle_kms_key_id="oracle-kms-key-id",
        oracle_kms_key_ids="",
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


# ── H4: wallet anti-replay ────────────────────────────────


def test_wallet_legacy_blocks_in_prod():
    """H4: legacy replayable wallet signatures are forbidden in prod."""
    s = _prod_settings(wallet_auth_allow_legacy=True)
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


# ── M1-A: oracle signer must stay out of the web tier ─────


def test_oracle_local_blocks_in_prod():
    """M1-A: oracle_signer_mode=local keeps the key in the web tier — blocked in prod."""
    s = _prod_settings(oracle_signer_mode="local")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_oracle_remote_blocks_in_prod():
    """M1-A: 'remote' falls through key_manager.py to LOCAL signing — blocked in prod."""
    s = _prod_settings(oracle_signer_mode="remote")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_oracle_kms_without_key_blocks():
    """M1-A: kms mode without any key id is invalid (dev or prod)."""
    s = _prod_settings(oracle_signer_mode="kms", oracle_kms_key_id="", oracle_kms_key_ids="")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_oracle_kms_with_only_key_ids_passes():
    """M1-A: kms mode is satisfied by the multisig CSV alone (OR with the single id)."""
    s = _prod_settings(oracle_signer_mode="kms", oracle_kms_key_id="", oracle_kms_key_ids="k1,k2")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


def test_dev_debug_allows_legacy_and_local():
    """Dev (DEBUG=true): the current insecure defaults must NOT block startup."""
    s = _prod_settings(
        debug=True,
        wallet_auth_allow_legacy=True,
        oracle_signer_mode="local",
    )
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise
