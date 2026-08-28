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
    # NON-CUSTODIAL: no signer/KMS/deposit/oracle fields — RSends holds no keys.
    base = dict(
        debug=False,
        alchemy_api_key="alch-key",
        hmac_secret="x" * 32,
        admin_api_token="y" * 32,  # dedicated admin bearer — MUST differ from hmac_secret
        database_url="postgresql+asyncpg://u:p@db.internal/rpagos",
        telegram_bot_token="tg",
        redis_url="rediss://redis.internal:6379/0",
        celery_broker_url="rediss://redis.internal:6379/1",
        auth_jwt_secret="a" * 64,
        email_dev_mode=False,  # prod sends real email
        app_url="https://app.rsends.io",  # required for verification links in prod
        wallet_auth_allow_legacy=False,  # H4: legacy replayable bearer off in prod
        # NON-CUSTODIAL on-chain settlement config (non-empty → no warning).
        rsends_router_addresses={"8453": "0xRouter"},
        # Per-chain RPC provider coverage: 8453 is served by alchemy_api_key
        # above, so no extra provider is needed for the baseline to validate.
        rpc_extra_providers={},
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


@pytest.mark.parametrize(
    "bad_token",
    ["", "change-me-in-production-min-32-chars", "short", "x" * 32],
    ids=["empty", "placeholder", "too-short", "equals-hmac-secret"],
)
def test_bad_admin_api_token_blocks_in_prod(bad_token):
    """Audit #9: the admin bearer must be set, >=32 chars, and DISTINCT from
    the HMAC secret ('x'*32 in the stand-in) — prod startup blocks otherwise."""
    s = _prod_settings(admin_api_token=bad_token)
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


def test_prod_settings_pass_without_social_login_env():
    """Social login was removed from the product: ENVIRONMENT=production with
    NO social-login env vars at all must boot past validate_settings.

    The `_prod_settings` stand-in deliberately has no social-login attribute —
    if a provider check is ever reintroduced in validate_settings, reading the
    missing attribute makes this test fail loudly (AttributeError)."""
    s = _prod_settings()
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
        validate_settings(s)  # no raise


def test_debug_true_skips_strong_tier():
    """Dev/tests (DEBUG=true): non-TLS Redis + short JWT must NOT block startup."""
    s = _prod_settings(debug=True, redis_url="redis://localhost:6379/0", auth_jwt_secret="short")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


# ── Render-internal plaintext Redis (guard narrowing) ─────────
# Render Key Value exposes NO internal TLS endpoint; the internal hostname is a
# bare `red-<id>` label on the private network. Plaintext is accepted ONLY for
# that shape — plaintext toward any external/public host must still block.


def test_plaintext_render_internal_redis_passes_in_prod():
    """Plaintext redis:// to a bare Render-internal host must NOT block."""
    s = _prod_settings(
        redis_url="redis://red-d96eqdu7r5hc738ak230:6379/0",
        celery_broker_url="redis://red-d96eqdu7r5hc738ak230:6379/1",
    )
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


def test_plaintext_render_internal_with_password_passes_in_prod():
    """Render 'Internal Authentication' form (redis://:pw@red-…) must NOT block."""
    s = _prod_settings(
        redis_url="redis://:s3cret-pw@red-d96eqdu7r5hc738ak230:6379/0",
        celery_broker_url="redis://:s3cret-pw@red-d96eqdu7r5hc738ak230:6379/1",
    )
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


@pytest.mark.parametrize(
    "bad_url",
    [
        "redis://redis.example.com:6379/0",
        "redis://203.0.113.7:6379/0",
        "redis://red-x.evil.com:6379/0",
        "redis://localhost:6379/0",
        "redis://[2001:db8::1]:6379/0",
        "redis://:6379/0",
    ],
    ids=["fqdn", "public-ip", "red-prefixed-fqdn", "localhost", "ipv6", "no-host"],
)
def test_plaintext_external_redis_still_blocks_in_prod(bad_url):
    """Narrowing, not weakening: plaintext to anything non-internal still blocks."""
    s = _prod_settings(redis_url=bad_url)
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_plaintext_external_celery_broker_blocks_in_prod():
    """The broker URL gets the same treatment as REDIS_URL."""
    s = _prod_settings(celery_broker_url="redis://broker.example.com:6379/1")
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


# ── H4: wallet anti-replay ────────────────────────────────


def test_wallet_legacy_blocks_in_prod():
    """H4: legacy replayable wallet signatures are forbidden in prod."""
    s = _prod_settings(wallet_auth_allow_legacy=True)
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


# NON-CUSTODIAL: M1-A oracle-signer hardening tests removed — there is no oracle
# signer (transfers aren't oracle-gated; the payer calls RSendsRouter directly).


def test_dev_debug_allows_legacy_and_local():
    """Dev (DEBUG=true): the current insecure defaults must NOT block startup."""
    s = _prod_settings(
        debug=True,
        wallet_auth_allow_legacy=True,
    )
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)  # no raise


# ── Email delivery is mandatory under ENVIRONMENT=production ──────


def test_email_dev_mode_true_blocks_under_environment_production():
    """EMAIL_DEV_MODE=true silently skips every send (verification, welcome)
    while signup still returns 201 — a production configured that way looks
    alive but nobody can ever receive an email. Same fail-closed class as
    ADMIN_API_TOKEN: refuse to boot."""
    s = _prod_settings(email_dev_mode=True)
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_email_dev_mode_false_passes_under_environment_production():
    s = _prod_settings()  # email_dev_mode=False in the stand-in
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
        validate_settings(s)  # no raise


def test_email_dev_mode_true_still_allowed_outside_production_env():
    """DEBUG=false alone (staging posture without ENVIRONMENT=production) keeps
    the old behavior: dev-mode email is allowed, only a warning path."""
    s = _prod_settings(email_dev_mode=True)
    with patch.dict(os.environ, {"ENVIRONMENT": "staging"}, clear=False):
        validate_settings(s)  # no raise


# ═══════════════════════════════════════════════════════════════
#  RPC provider coverage is per-chain and vendor-neutral
#  (incident 2026-08-28: a mandatory ALCHEMY_API_KEY made a
#   dual-provider deployment behave as single-provider)
# ═══════════════════════════════════════════════════════════════

def test_empty_alchemy_key_passes_when_json_covers_every_chain():
    """No Alchemy at all is a legitimate deployment.

    The key was an unconditional startup error, so a merchant could not remove
    a quota-exhausted vendor even with another provider configured and healthy.
    """
    s = _prod_settings(
        alchemy_api_key="",
        rsends_router_addresses={"8453": "0xRouter"},
        rpc_extra_providers={8453: [{"name": "ankr", "url": "https://x", "priority": 0}]},
    )
    validate_settings(s)  # no raise


def _blocking_errors(caplog, settings) -> str:
    """Run validate_settings expecting a block; return the logged error text."""
    import logging

    with caplog.at_level(logging.CRITICAL, logger="app.config"):
        with pytest.raises(StartupValidationError):
            validate_settings(settings)
    return "\n".join(r.getMessage() for r in caplog.records)


def test_chain_without_a_configured_provider_fails_naming_the_chain(caplog):
    """Fail closed, and say WHICH CHAIN lacks a provider — not which vendor.

    The old message named Alchemy and a signup URL, which is why the fix for it
    was "put the dead key back" rather than "configure a provider".
    """
    s = _prod_settings(
        alchemy_api_key="",
        rsends_router_addresses={"8453": "0xRouter"},
        rpc_extra_providers={},
    )
    text = _blocking_errors(caplog, s)

    assert "8453" in text, f"the blocking error does not name the chain: {text}"
    assert "dashboard.alchemy.com" not in text, (
        "the error still sends the operator to one vendor's signup page"
    )


def test_public_defaults_do_not_satisfy_provider_coverage(caplog):
    """`_DEFAULT_PROVIDERS` has three entries for 8453 — none of them counts.

    They are best-effort, rate-limited public endpoints; sole reliance on them
    for a chain that keys the cursor, the environment stamp and the invoice id
    is not a configured deployment.
    """
    from app.services import rpc_manager as rm

    assert len(rm._DEFAULT_PROVIDERS[8453]) >= 3
    s = _prod_settings(
        alchemy_api_key="",
        rsends_router_addresses={"8453": "0xRouter"},
        rpc_extra_providers={},
    )
    assert "8453" in _blocking_errors(caplog, s)


def test_coverage_is_checked_per_chain_not_globally(caplog):
    """One covered chain must not vouch for an uncovered sibling."""
    s = _prod_settings(
        alchemy_api_key="",
        rsends_router_addresses={"8453": "0xRouter", "42161": "0xRouter2"},
        rpc_extra_providers={8453: [{"name": "ankr", "url": "https://x", "priority": 0}]},
    )
    text = _blocking_errors(caplog, s)

    # The uncovered-chains clause must name 42161 and ONLY 42161. (8453 still
    # appears later in the message, as one of the chains an Alchemy key serves.)
    assert "configured for chain(s) 42161." in text, (
        f"expected exactly the uncovered chain to be listed; got: {text}"
    )


def test_alchemy_key_alone_still_covers_the_chains_it_serves():
    """The supported path is unchanged: a key covers the chains it has URLs for."""
    s = _prod_settings(
        alchemy_api_key="alch-key",
        rsends_router_addresses={"8453": "0xRouter"},
        rpc_extra_providers={},
    )
    validate_settings(s)  # no raise


def test_alchemy_key_does_not_cover_a_chain_it_has_no_url_for():
    """A key is not blanket coverage — Alchemy serves only the chains in the
    URL table, so a router on any other chain still needs a provider."""
    from app import config as config_mod

    unsupported = 137  # Polygon — deliberately absent from the URL table
    assert unsupported not in config_mod.ALCHEMY_RPC_URL_TEMPLATES
    s = _prod_settings(
        alchemy_api_key="alch-key",
        rsends_router_addresses={str(unsupported): "0xRouter"},
        rpc_extra_providers={},
    )
    with pytest.raises(StartupValidationError):
        validate_settings(s)


def test_alchemy_chain_table_has_one_source_of_truth():
    """The validator and the RPC manager must read the SAME table.

    Two gates over one concept that drift apart is exactly issue #87. The
    manager builds its Alchemy provider from the config constant; nothing may
    re-declare the chain set locally.
    """
    import inspect

    from app import config as config_mod
    from app.services import rpc_manager as rm

    assert set(config_mod.ALCHEMY_RPC_URL_TEMPLATES) == {8453, 84532, 1, 42161}
    src = inspect.getsource(rm.RPCManager.__init__)
    assert "ALCHEMY_RPC_URL_TEMPLATES" in src, (
        "RPCManager re-declares the Alchemy chain set instead of reading the "
        "shared constant — the two will drift"
    )
