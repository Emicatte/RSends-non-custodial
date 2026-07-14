"""
RPagos Backend — Configurazione Production-Ready.
"""

import logging
import os
import re
import sys
from urllib.parse import urlsplit

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

    # Dedicated admin bearer (X-Admin-Token) for /api/v1/audit, /admin/aml/*,
    # /health/config. Deliberately SEPARATE from hmac_secret (audit finding #9:
    # one secret must not span two trust domains). Empty ⇒ admin surface is
    # fully denied (fail-closed in require_admin).
    admin_api_token: str = ""

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

    # ══════════════════════════════════════════════════════
    #  NON-CUSTODIAL on-chain settlement
    #  No KMS / no sweep key / no deposit master key — RSends never holds keys
    #  or funds. The payer pays RSendsRouter directly from their own wallet; the
    #  indexer watches PaymentMade events.
    # ══════════════════════════════════════════════════════
    # JSON map of chain_id → RSendsRouter address, e.g. {"8453":"0xRouter..."}
    rsends_router_addresses_json: str = ""
    # JSON map of chain_id → RPC URL (optional; falls back to rpc_manager defaults)
    indexer_rpc_urls_json: str = ""
    # Fallback confirmation depth (latest - N) used when the chain's finalized
    # tag is unavailable/disabled. A settlement is FINAL (and only then is the
    # invoice marked paid + webhook fired) once its block is this deep AND its
    # stored block hash is still canonical.
    indexer_confirmations: int = 2
    # Prefer the chain's finalized/safe block tag (Base/Ethereum support it) to
    # decide finality; set False to always use the indexer_confirmations depth.
    indexer_use_finalized_tag: bool = True
    # Block tag treated as final ("finalized" or "safe").
    indexer_finalized_tag: str = "finalized"
    # How far below the final head we keep re-verifying `final` rows' block hash,
    # so a deeper-than-expected reorg of an already-finalized log can still be
    # detected and reversed.
    indexer_reorg_safety_depth: int = 64
    # JSON map of chain_id → start block for first-run backfill, e.g. {"8453": 0}
    indexer_start_blocks_json: str = ""
    # Widest eth_getLogs block range a single request may span. The per-tick
    # window is scanned in chunks of at most this many blocks. Default 10 =
    # the Alchemy free-tier cap on Base Sepolia; raise only if EVERY
    # configured provider accepts the wider range.
    indexer_getlogs_max_range: int = 10

    # ── Server ────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Dev/Debug Flags (must remain False/unset in production) ──
    rsend_dev_auth_bypass: bool = False

    # ── CORS Origins (prod) ───────────────────────────────
    cors_origins: str = "https://rsends-noncustodial.example,https://app.rsends-noncustodial.example"

    # ── Anomaly Detection ─────────────────────────────────
    anomaly_z_score_threshold: float = 3.0
    anomaly_min_sample_size: int = 10

    # ── Telegram Bot ──────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Alert Notifications (separate from sweep notifications) ──
    telegram_alert_chat_id: str = ""   # dedicated chat/group for critical alerts

    # ── Merchant approval queue ───────────────────────────
    # Chat that receives the "merchant pending approval" message at KYB submit
    # (falls back to telegram_chat_id). Optional: unset → notification disabled
    # (one startup WARNING), the admin approval page remains the source of truth.
    telegram_approvals_chat_id: str = ""

    # ── Notification Rate Limit ───────────────────────────
    notification_rate_limit: int = 30          # max messages per minute per chat
    notification_rate_window: int = 60         # sliding window in seconds

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

    # NON-CUSTODIAL: platform-fee sweep config removed. Any protocol fee is taken
    # atomically on-chain by RSendsRouter (if enabled), never swept by RSends.

    # ── End-user Auth (Session JWT) ──────────────────────
    auth_jwt_secret: str = ""                 # HS256 secret for access tokens; >=64 chars required in prod

    # ── Email (Resend) ───────────────────────────────────
    resend_api_key: str = ""                  # Resend API key (re_...) — required when email_dev_mode is False
    email_from: str = "security@rsends.io"    # From header; falls back to "onboarding@resend.dev" if unset
    email_dev_mode: bool = True               # If True: log and skip send. Safer default; prod must set False.
    frontend_url: str = "http://localhost:3000"  # Used for email CTAs (e.g. settings links)

    # ── App base URL (email verification links) ──────────
    # Public app origin (e.g. https://app.rsends.io) used to build the
    # email-verification link {APP_URL}/{locale}/verify-email?token=... . No
    # localhost fallback: the link must be clickable from the recipient's inbox.
    # Required whenever emails are actually sent (email_dev_mode=False) or in
    # production — enforced in validate_settings().
    app_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── Parsed JSON config helpers (non-custodial on-chain settlement) ──
    @property
    def rsends_router_addresses(self) -> dict:
        """{chain_id(str) -> RSendsRouter address} parsed from the JSON env."""
        return _parse_json_map(self.rsends_router_addresses_json)

    @property
    def indexer_rpc_urls(self) -> dict:
        return _parse_json_map(self.indexer_rpc_urls_json)

    @property
    def indexer_start_blocks(self) -> dict:
        return _parse_json_map(self.indexer_start_blocks_json)


_HEX_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _parse_json_map(raw: str) -> dict:
    """Parse a JSON object env string into a dict; {} on empty/invalid."""
    if not raw:
        return {}
    import json
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        return {}


class StartupValidationError(SystemExit):
    """Raised when required configuration is missing or invalid."""
    pass


def is_prod_posture(settings: Settings) -> bool:
    """Unified production-posture check (see H6): prod unless DEBUG=true AND
    ENVIRONMENT does not start with 'prod'. This is the single definition of
    the expression validate_settings() gates the Redis-TLS / OAuth /
    JWT-secret prod guards on — any runtime dev-only relaxation (e.g. email
    auto-verify in email_auth_service) must use this same check so it can
    never diverge from the prod guards.
    """
    env = os.getenv("ENVIRONMENT", "").lower()
    return (not settings.debug) or env.startswith("prod")


# Render Key Value internal hostnames are bare `red-<id>` labels (no dots) on
# the private network — never internet-routable. Anything else (FQDNs, IP
# literals, IPv6, localhost) must keep using rediss:// in prod.
_RENDER_INTERNAL_REDIS_HOST = re.compile(r"^red-[a-z0-9]+$")


def _is_render_internal_plaintext_redis_url(url: str) -> bool:
    """True iff `url` is plaintext redis:// AND its host is a Render-internal
    Key Value hostname. Malformed URLs return False (fail closed)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname  # may raise ValueError (invalid IPv6 literal)
    except ValueError:
        return False
    if parts.scheme != "redis":
        return False
    return bool(host) and _RENDER_INTERNAL_REDIS_HOST.fullmatch(host) is not None


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
    is_prod = is_prod_posture(settings)

    # NON-CUSTODIAL: no SWEEP_PRIVATE_KEY / SIGNER_MODE / KMS / Vault validation.
    # The platform holds no keys and signs nothing.

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

    # ── ADMIN_API_TOKEN (prod only) ───────────────────────
    if is_prod:
        if settings.admin_api_token in ("", "change-me-in-production-min-32-chars"):
            errors.append(
                "ADMIN_API_TOKEN is empty or the default placeholder. "
                "The admin surface (/api/v1/audit, /admin/aml/*, /health/config) "
                "is unusable without it. Set a unique secret >= 32 chars "
                "(distinct from HMAC_SECRET)."
            )
        elif len(settings.admin_api_token) < 32:
            errors.append(
                f"ADMIN_API_TOKEN is too short ({len(settings.admin_api_token)} chars). "
                "Must be >= 32 characters in production."
            )
        elif settings.admin_api_token == settings.hmac_secret:
            errors.append(
                "ADMIN_API_TOKEN must be DIFFERENT from HMAC_SECRET — reusing "
                "the webhook/audit HMAC secret as the admin bearer is exactly "
                "the coupling this token exists to remove."
            )

    # ── DATABASE_URL (prod only) ──────────────────────────
    if is_prod and "localhost" in settings.database_url and "sqlite" not in settings.database_url:
        warnings.append(
            "DATABASE_URL points to localhost in production mode. "
            "This is likely incorrect — verify your connection string."
        )

    # NON-CUSTODIAL: no DEPOSIT_MASTER_KEY — the payer pays RSendsRouter directly.
    if is_prod and not settings.rsends_router_addresses:
        warnings.append(
            "RSENDS_ROUTER_ADDRESSES_JSON is empty. The on-chain PaymentMade "
            "indexer will be disabled until per-chain RSendsRouter addresses are set."
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
            "TELEGRAM_BOT_TOKEN is empty. Telegram notifications (merchant "
            "approval queue, ops alerts) are disabled; the /admin/approvals "
            "page remains the source of truth for pending merchants."
        )

    # ── Production hardening (F-BE-09, F-BE-13, F-BE-01) ──
    # Gated on the unified is_prod (not-DEBUG or ENVIRONMENT=prod) so these
    # actually run on the documented deploy path (DEBUG=false), not only when
    # ENVIRONMENT=production (which is never set) — H6.
    if is_prod:
        for _name, _url in (
            ("REDIS_URL", settings.redis_url),
            ("CELERY_BROKER_URL", settings.celery_broker_url),
        ):
            if _url.startswith("redis://") and not _is_render_internal_plaintext_redis_url(_url):
                errors.append(
                    f"{_name} uses plaintext redis:// toward a non-internal host "
                    "in production. Plaintext is only allowed for Render-internal "
                    "Key Value hostnames (redis://[:password@]red-xxxx:6379/N); "
                    "use rediss:// (TLS) for any external/public endpoint."
                )

        if "rpagos:password@" in settings.database_url:
            errors.append("Default placeholder database credentials detected in production")

        if settings.debug:
            errors.append("DEBUG=true is forbidden when ENVIRONMENT=production")

        # ── Email delivery (fail-closed, same class as ADMIN_API_TOKEN) ──
        # EMAIL_DEV_MODE=true skips every send while signup still returns 201:
        # a production configured that way looks alive but no one can ever
        # receive a verification/welcome email. Keyed strictly on
        # ENVIRONMENT=production (staging postures may still run mail-less).
        if os.getenv("ENVIRONMENT", "").lower().startswith("prod") and settings.email_dev_mode:
            errors.append(
                "EMAIL_DEV_MODE=true is forbidden when ENVIRONMENT=production. "
                "Emails would be silently skipped (log-only) while signup keeps "
                "returning 201. Set EMAIL_DEV_MODE=false and a real RESEND_API_KEY."
            )

        # ── User-auth hardening ──
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

    # ── APP_URL (email verification links) ───────────────
    # Required whenever emails actually go out (email_dev_mode=False) or in
    # production. No localhost fallback — the verification link must be a public
    # origin reachable from the recipient's inbox.
    if is_prod or not settings.email_dev_mode:
        if not settings.app_url:
            errors.append(
                "APP_URL is empty. Email verification links cannot be built. "
                "Set APP_URL to the public app origin (e.g. https://app.rsends.io)."
            )
        elif "localhost" in settings.app_url or "127.0.0.1" in settings.app_url:
            errors.append(
                "APP_URL points to localhost. Verification links must use a public "
                "origin reachable from the recipient's inbox (no localhost fallback)."
            )

    # ── Wallet anti-replay (H4) ───────────────────────────
    # Legacy wallet signatures are replayable bearers (security/auth.py L150-151).
    # Allowed in dev/rollout, but forbidden in prod — fail closed at startup.
    if is_prod and settings.wallet_auth_allow_legacy:
        errors.append(
            "WALLET_AUTH_ALLOW_LEGACY=true is forbidden in production: legacy "
            "wallet signatures are replayable. Set WALLET_AUTH_ALLOW_LEGACY=false."
        )

    # NON-CUSTODIAL: no oracle signer — transfers are not oracle-gated; the payer
    # calls RSendsRouter directly and funds settle atomically on-chain.

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

    if (
        os.getenv("RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS") == "1"
        and env not in ("development", "test")
    ):
        raise RuntimeError(
            "RSEND_E2E_ALLOW_LOOPBACK_WEBHOOKS is set but ENVIRONMENT="
            f"{env or '<unset>'!r} (must be 'development' or 'test'). "
            "Refusing to start — this flag relaxes the webhook SSRF egress "
            "guard for loopback targets (E2E harness only)."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
