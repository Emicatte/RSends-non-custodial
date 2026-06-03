"""
RPagos Backend — Configurazione Production-Ready.
"""

import logging
import os
import re
import sys

from pydantic_settings import BaseSettings
from functools import lru_cache

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://rpagos:password@localhost:5432/rpagos"

    # ── Redis Cache ───────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Sicurezza ─────────────────────────────────────────
    hmac_secret: str = "MUST_BE_SET_VIA_ENV_32_CHARS_MIN"

    # Shared secret for Next.js → backend internal endpoints (/api/internal/*).
    # MUST match INTERNAL_PROXY_SECRET on the Next.js side (H3).
    internal_proxy_secret: str = ""

    # H4 transition flag: accept the legacy replayable wallet-signature bearer
    # (RSends:{address}:{timestamp}) IN ADDITION to the new session-HMAC scheme.
    # Set to false once both backend and frontend are deployed, to fully close
    # the replay window.
    wallet_auth_allow_legacy: bool = True

    # M8 — deny-by-default for unauthenticated GET requests. When True, a GET to
    # a non-exempt path with no valid API key is rejected (401) unless the path
    # is in GET_PUBLIC_PREFIXES (genuinely public, or self-authenticating via its
    # own route dependency). Set False to restore the legacy "GET = public read"
    # fallback (kill-switch).
    api_get_deny_by_default: bool = True

    # ── Alchemy ───────────────────────────────────────────
    alchemy_api_key: str = ""
    alchemy_webhook_secret: str = ""
    alchemy_auth_token: str = ""

    # ── Deposit Address Generation ────────────────────────
    deposit_master_seed: str = ""         # [DEPRECATED] Legacy seed — usato solo per backward compat
    deposit_master_key: str = ""          # Master private key per derivazione deposit addresses (0x-prefixed 64-char hex)
                                          # CRITICO: backup sicuro, se persa i fondi non sono recuperabili

    # ── Sweeper / Key Management ────────────────────────
    sweep_private_key: str = ""
    signer_mode: str = "local"          # "local" (env key) | "kms" (AWS KMS) | "vault" (HashiCorp Vault)
    kms_key_id: str = ""                # AWS KMS key ID (ECC_SECG_P256K1)
    aws_region: str = "eu-west-1"       # AWS region for KMS

    # ── Oracle signer (M1) — signs EIP-712 oracle approvals with a DEDICATED
    # key, separate from the sweep hot wallet. In prod use "kms" so the oracle
    # key never lives in the web tier (the Next oracle delegates digest signing
    # to /api/internal/oracle/sign-digest). "local" (dev/testnet) uses
    # ORACLE_SIGNER_PRIVATE_KEY. NB: the resulting signer address must be the
    # on-chain oracleSigner (set it via the contract before switching).
    oracle_signer_mode: str = "local"       # "local" | "kms"
    oracle_kms_key_id: str = ""             # dedicated KMS key for the oracle (mode=kms)
    oracle_signer_private_key: str = ""     # dev/testnet only (mode=local)
    # Multisig (M1 slice B) — comma-separated lists for an M-of-N oracle (V5/V6
    # threshold). Fall back to the single-key vars above when unset (N=1).
    oracle_kms_key_ids: str = ""            # comma-separated KMS key ids (mode=kms)
    oracle_signer_private_keys: str = ""    # comma-separated keys (mode=local, dev)
    vault_addr: str = ""                # HashiCorp Vault server URL
    vault_token: str = ""               # Vault authentication token
    vault_key_name: str = "rsend-signer"  # Vault Transit key name

    # ── Server ────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Dev/Debug Flags (must remain False/unset in production) ──
    rsend_dev_auth_bypass: bool = False

    # ── CORS Origins (prod) ───────────────────────────────
    cors_origins: str = "https://fee-router-dapp.vercel.app,https://rpagos.io"

    # ── Anomaly Detection ─────────────────────────────────
    anomaly_z_score_threshold: float = 3.0
    anomaly_min_sample_size: int = 10

    # ── Telegram Bot ──────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Alert Notifications (separate from sweep notifications) ──
    telegram_alert_chat_id: str = ""   # dedicated chat/group for critical alerts

    # ── Notification Rate Limit ───────────────────────────
    notification_rate_limit: int = 30          # max messages per minute per chat
    notification_rate_window: int = 60         # sliding window in seconds

    # ── Reconciliation ────────────────────────────────────
    # Percentage threshold for reconciliation mismatch alert (e.g. 1.0 = 1%)
    reconciliation_threshold_pct: float = 1.0
    # JSON map of chain_id → treasury address, e.g. {"8453":"0xABC...","1":"0xDEF..."}
    treasury_addresses_json: str = ""

    # ── Celery ────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Monitoring ────────────────────────────────────────
    sentry_dsn: str = ""

    # ── OpenTelemetry ─────────────────────────────────────
    otel_endpoint: str = ""            # OTLP gRPC endpoint (e.g. "http://localhost:4317")
    otel_service_name: str = "rsend-backend"

    # ── Alert Webhook (Discord/Slack) ─────────────────────
    alert_webhook_url: str = ""        # Discord or Slack incoming webhook URL

    # ── Platform Fee ─────────────────────────────────────
    platform_fee_bps: int = 100              # 100 basis points = 1.0%
    platform_treasury_address: str = ""       # RSends treasury wallet
    platform_fee_enabled: bool = True

    # ── End-user Auth (Google OAuth + Session JWT) ───────
    google_oauth_client_id: str = ""          # Google OAuth 2.0 client ID (web) — `aud` claim of ID tokens
    auth_jwt_secret: str = ""                 # HS256 secret for access tokens; >=64 chars required in prod

    # ── Email (Resend) ───────────────────────────────────
    resend_api_key: str = ""                  # Resend API key (re_...) — required when email_dev_mode is False
    email_from: str = "security@rsends.io"    # From header; falls back to "onboarding@resend.dev" if unset
    email_dev_mode: bool = True               # If True: log and skip send. Safer default; prod must set False.
    frontend_url: str = "http://localhost:3000"  # Used for email CTAs (e.g. settings links)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_HEX_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class StartupValidationError(SystemExit):
    """Raised when required configuration is missing or invalid."""
    pass


def validate_settings(settings: Settings) -> None:
    """Validate critical env vars at startup.

    Errors are fatal — the process exits with a clear message.
    Warnings are logged but non-fatal.

    Rules:
    - SWEEP_PRIVATE_KEY: always required (unless SIGNER_MODE=kms)
    - ALCHEMY_API_KEY: always required (RPC calls fail without it)
    - HMAC_SECRET: must be >= 32 chars in production
    - DATABASE_URL: must not be the placeholder default in production
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Production posture. The documented deploy sets DEBUG=false but NOT
    # ENVIRONMENT, so derive `is_prod` from not-DEBUG (the strong-tier checks
    # below previously gated ONLY on ENVIRONMENT=prod and never ran in prod — H6).
    env = os.getenv("ENVIRONMENT", "").lower()
    is_prod = (not settings.debug) or env.startswith("prod")

    # ── SWEEP_PRIVATE_KEY ─────────────────────────────────
    if settings.signer_mode == "local":
        if not settings.sweep_private_key:
            errors.append(
                "SWEEP_PRIVATE_KEY is empty. "
                "The sweeper cannot sign transactions without it. "
                "Set it in .env or switch SIGNER_MODE=kms."
            )
        elif not _HEX_KEY_RE.match(settings.sweep_private_key):
            errors.append(
                "SWEEP_PRIVATE_KEY is malformed. "
                "Expected 0x-prefixed 64-char hex string (32 bytes). "
                f"Got: {settings.sweep_private_key[:6]}...({len(settings.sweep_private_key)} chars)"
            )
    elif settings.signer_mode == "kms":
        if not settings.kms_key_id:
            errors.append(
                "SIGNER_MODE=kms but KMS_KEY_ID is empty. "
                "Set the AWS KMS key ID for transaction signing."
            )
    elif settings.signer_mode == "vault":
        if not settings.vault_addr:
            errors.append(
                "SIGNER_MODE=vault but VAULT_ADDR is empty. "
                "Set the HashiCorp Vault server URL."
            )
        if not settings.vault_token:
            errors.append(
                "SIGNER_MODE=vault but VAULT_TOKEN is empty. "
                "Set the Vault authentication token."
            )

    # ── ALCHEMY_API_KEY ───────────────────────────────────
    if not settings.alchemy_api_key:
        errors.append(
            "ALCHEMY_API_KEY is empty. "
            "RPC calls (gas estimation, tx broadcast, receipt polling) will all fail. "
            "Get a key at https://dashboard.alchemy.com/"
        )

    # ── HMAC_SECRET (prod only) ───────────────────────────
    if is_prod:
        if settings.hmac_secret in ("change-me-in-production", "MUST_BE_SET_VIA_ENV_32_CHARS_MIN"):
            errors.append(
                "HMAC_SECRET is still the default placeholder. "
                "Webhook signatures are NOT secure. Set a unique secret >= 32 chars."
            )
        elif len(settings.hmac_secret) < 32:
            errors.append(
                f"HMAC_SECRET is too short ({len(settings.hmac_secret)} chars). "
                "Must be >= 32 characters in production."
            )

    # ── DATABASE_URL (prod only) ──────────────────────────
    if is_prod and "localhost" in settings.database_url and "sqlite" not in settings.database_url:
        warnings.append(
            "DATABASE_URL points to localhost in production mode. "
            "This is likely incorrect — verify your connection string."
        )

    # ── DEPOSIT_MASTER_KEY ────────────────────────────────
    if not settings.deposit_master_key:
        warnings.append(
            "DEPOSIT_MASTER_KEY is empty. "
            "Deposit address generation will fail. "
            "Set a 0x-prefixed 64-char hex private key in .env."
        )
    elif not _HEX_KEY_RE.match(settings.deposit_master_key):
        errors.append(
            "DEPOSIT_MASTER_KEY is malformed. "
            "Expected 0x-prefixed 64-char hex string (32 bytes). "
            f"Got: {settings.deposit_master_key[:6]}...({len(settings.deposit_master_key)} chars)"
        )

    # ── ALCHEMY_WEBHOOK_SECRET ────────────────────────────
    if not settings.alchemy_webhook_secret:
        warnings.append(
            "ALCHEMY_WEBHOOK_SECRET is empty. "
            "Falling back to block polling (slower, higher RPC usage). "
            "Set it in Alchemy Dashboard > Webhooks for real-time TX detection."
        )

    # ── Telegram (informational) ──────────────────────────
    if not settings.telegram_bot_token:
        warnings.append(
            "TELEGRAM_BOT_TOKEN is empty. Sweep notifications are disabled."
        )

    # ── Production hardening (F-BE-09, F-BE-13, F-BE-01) ──
    # Gated on the unified is_prod (not-DEBUG or ENVIRONMENT=prod) so these
    # actually run on the documented deploy path (DEBUG=false), not only when
    # ENVIRONMENT=production (which is never set) — H6.
    if is_prod:
        if settings.redis_url.startswith("redis://") and not settings.redis_url.startswith("rediss://"):
            errors.append("Redis URL must use TLS (rediss://) in production")
        if settings.celery_broker_url.startswith("redis://") and not settings.celery_broker_url.startswith("rediss://"):
            errors.append("Celery broker URL must use TLS (rediss://) in production")

        if "rpagos:password@" in settings.database_url:
            errors.append("Default placeholder database credentials detected in production")

        if settings.debug:
            errors.append("DEBUG=true is forbidden when ENVIRONMENT=production")

        # ── User-auth hardening ──
        if not settings.google_oauth_client_id:
            errors.append(
                "GOOGLE_OAUTH_CLIENT_ID is empty in production. "
                "End-user Google login cannot verify ID tokens without it."
            )
        if len(settings.auth_jwt_secret) < 64:
            errors.append(
                f"AUTH_JWT_SECRET is too short ({len(settings.auth_jwt_secret)} chars). "
                "Must be >= 64 characters (hex-encoded 32 random bytes) in production."
            )

        # ── Internal endpoint secret (H3) ──
        if not settings.internal_proxy_secret:
            errors.append(
                "INTERNAL_PROXY_SECRET is empty in production. "
                "The /api/internal/* endpoints require it (X-Internal-Secret); "
                "set the SAME value on the Next.js side (INTERNAL_PROXY_SECRET)."
            )

    # ── Print results ─────────────────────────────────────
    for w in warnings:
        logger.warning("[CONFIG] %s", w)

    if errors:
        logger.critical("=" * 60)
        logger.critical("  STARTUP BLOCKED — Missing/invalid configuration")
        logger.critical("=" * 60)
        for i, e in enumerate(errors, 1):
            logger.critical("  %d. %s", i, e)
        logger.critical("")
        logger.critical("  Fix these in .env and restart. See .env.example for docs.")
        logger.critical("=" * 60)
        raise StartupValidationError(1)


def validate_dev_flags(settings: Settings) -> None:
    """Lifespan-level assertion: refuse startup when dev/debug flags are
    enabled outside of ENVIRONMENT=development.

    Defense-in-depth over validate_settings(): raises RuntimeError (not
    SystemExit) so frameworks can surface it as a startup crash, and
    explicitly covers RSEND_DEV_AUTH_BYPASS which validate_settings()
    does not check.
    """
    env = os.getenv("ENVIRONMENT", "").lower()

    if settings.rsend_dev_auth_bypass and env != "development":
        raise RuntimeError(
            "RSEND_DEV_AUTH_BYPASS is truthy but ENVIRONMENT="
            f"{env or '<unset>'!r} (must be 'development'). "
            "Refusing to start — this flag disables API authentication."
        )

    if settings.debug and env.startswith("prod"):
        raise RuntimeError(
            "DEBUG=True but ENVIRONMENT starts with 'prod'. "
            "Refusing to start — DEBUG must be False in production."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
