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
    # Optional. A key yields an RPC endpoint only for the chains in
    # ALCHEMY_RPC_URL_TEMPLATES (below); coverage for anything else comes from
    # RPC_PROVIDERS_JSON. See the provider-coverage block in validate_settings.
    alchemy_api_key: str = ""

    # ══════════════════════════════════════════════════════
    #  NON-CUSTODIAL on-chain settlement
    #  No KMS / no sweep key / no deposit master key — RSends never holds keys
    #  or funds. The payer pays RSendsRouter directly from their own wallet; the
    #  indexer watches PaymentMade events.
    # ══════════════════════════════════════════════════════
    # JSON map of chain_id → RSendsRouter address, e.g. {"8453":"0xRouter..."}
    rsends_router_addresses_json: str = ""
    # JSON map of chain_id → RSendsRouterV2 address (ownerless, FEE-LESS
    # single-merchant — the mainnet router: payer→merchant only). A chain in
    # this map creates v2 intents (v2 wins over v1 if both are set; the
    # indexer watches both so in-flight v1 payments still settle) — the
    # mainnet cutover is this one env var.
    rsends_router_v2_addresses_json: str = ""
    # JSON map of chain_id → RSendsSplitRouter address (ownerless, fee-less
    # N-way split). FAIL-CLOSED: split intent creation 422s SPLIT_UNAVAILABLE
    # for any chain not in this map — set it only after the contract is
    # deployed and the indexer knows the event (see DEPLOY_RUNBOOK 1e).
    split_router_addresses_json: str = ""
    # Optional JSON map { chain_id : [ {name, url[, priority]} ] } of EXTRA
    # RPC providers merged into rpc_manager's failover list, between Alchemy
    # (priority -1) and the built-in public fallbacks (default priority 0,
    # stable sort → config wins ties). Adding a second paid vendor at mainnet
    # is one env edit, zero code. Malformed input is ignored with a warning —
    # never a boot failure.
    rpc_providers_json: str = ""
    # Proactive RPC health checks (one eth_blockNumber per provider per 30s,
    # started for the indexer's chains at app startup). Feeds provider
    # health-based routing in RPCManager.call, the rpc_provider_healthy /
    # rpc_block_height gauges and the all-providers-down CRITICAL. One-env
    # rollback: set false and restart — call() then tries every provider in
    # priority order exactly as before.
    rpc_health_checks_enabled: bool = True
    # Confirmation depth (latest - N) used as the PAID gate when the finalized
    # tag is disabled (INDEXER_USE_FINALIZED_TAG=false — fix A). A settlement
    # is FINAL (invoice paid + webhook fired) once its block is this deep AND
    # its stored block hash is still canonical. 15 on Base (2s blocks) ≈ Paid
    # in ~35s, with margin over any observed OP-stack sequencer reorg and over
    # the B-2 reorg-evidence window (3×5s ticks). Depth-final rows stay
    # RECONCILABLE until the chain's TRUE finality (the finalized tag) passes
    # them (F-1): a deeper-than-N reorg in that window reverses the settlement
    # and fires payment.reversed — no longer alert-only.
    indexer_confirmations: int = 15
    # Prefer the chain's finalized/safe block tag (Base/Ethereum support it)
    # as the PAID gate; set False to pay at the indexer_confirmations depth
    # instead. The tag is consulted in BOTH modes — in depth mode it only
    # drives the terminal (true-finality) boundary, never the paid gate. In
    # tag mode a tag outage PAUSES finalization loudly (F-10: gauge
    # rsend_indexer_finality_degraded + WARNING/CRITICAL) instead of silently
    # degrading to depth semantics.
    indexer_use_finalized_tag: bool = True
    # Block tag treated as final ("finalized" or "safe").
    indexer_finalized_tag: str = "finalized"
    # INERT: superseded by the true-finality terminal boundary (F-1) — final
    # rows are re-verified against the finalized tag, not a fixed depth. Kept
    # for env compatibility only.
    indexer_reorg_safety_depth: int = 64
    # JSON map of chain_id → start block for first-run backfill, e.g. {"8453": 0}
    indexer_start_blocks_json: str = ""
    # ── TRON watch-only poller ────────────────────────────────
    # JSON array of TRON HTTP node base URLs, primary first:
    #   TRON_NODE_URLS_JSON='["https://api.trongrid.io","https://<failover>"]'
    # Empty (the default) means the poller does not start, which is not an
    # error — the same shape as an empty router map skipping the EVM indexer.
    # Every listed node must prove it serves TRON mainnet at boot or the
    # backend refuses to start; see app/services/tron_poller.py.
    tron_node_urls_json: str = ""
    # The SAME thing for the Nile testnet, e.g.
    #   TRON_NILE_NODE_URLS_JSON='["https://nile.trongrid.io"]'
    # A SEPARATE variable, deliberately, rather than one variable plus a network
    # flag: with a flag, pointing production at a testnet (or the reverse) is a
    # one-character edit with no signal. With two, each is proven at boot
    # against the network it is named for, and a swap stops the boot.
    # Either may be set without the other; an empty one means only that this
    # network is not watched. Nile needs no API key.
    tron_nile_node_urls_json: str = ""
    # TronGrid API key, sent as the TRON-PRO-API-KEY header. Optional: the free
    # tier answers keyless at a lower rate limit. Shared by both networks —
    # same provider, and Nile answers keyless.
    trongrid_api_key: str = ""
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
        return _parse_json_map(self.rsends_router_addresses_json, "RSENDS_ROUTER_ADDRESSES_JSON")

    @property
    def rsends_router_v2_addresses(self) -> dict:
        """{chain_id(str) -> RSendsRouterV2 address} parsed from the JSON env."""
        return _parse_json_map(self.rsends_router_v2_addresses_json, "RSENDS_ROUTER_V2_ADDRESSES_JSON")

    @property
    def split_router_addresses(self) -> dict:
        """{chain_id(str) -> RSendsSplitRouter address} parsed from the JSON env."""
        return _parse_json_map(self.split_router_addresses_json, "SPLIT_ROUTER_ADDRESSES_JSON")

    @property
    def rpc_extra_providers(self) -> dict:
        """{chain_id(int) -> [ {name, url, priority} ]} parsed from
        RPC_PROVIDERS_JSON. Entries without a usable name/url and keys that
        are not chain ids are dropped (with a warning) — never raises."""
        raw = _parse_json_map(self.rpc_providers_json)
        if self.rpc_providers_json.strip() not in ("", "{}") and not raw:
            # _parse_json_map swallows a parse failure into {}. Silently
            # running with zero extra providers is exactly the "configured but
            # not actually there" failure mode this var exists to avoid.
            logger.warning(
                "RPC_PROVIDERS_JSON is set but is not a JSON object — ignored "
                "entirely; NO extra RPC providers are configured"
            )
        out: dict = {}
        for chain_key, entries in raw.items():
            try:
                chain_id = int(chain_key)
            except (TypeError, ValueError):
                logger.warning(
                    "RPC_PROVIDERS_JSON: ignoring non-numeric chain id %r", chain_key
                )
                continue
            if not isinstance(entries, list):
                logger.warning(
                    "RPC_PROVIDERS_JSON: chain %s value is not a list — ignored", chain_key
                )
                continue
            cleaned = []
            for entry in entries:
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("name"), str) and entry["name"]
                    and isinstance(entry.get("url"), str) and entry["url"]
                ):
                    cleaned.append(
                        {
                            "name": entry["name"],
                            "url": entry["url"],
                            "priority": int(entry.get("priority", 0)),
                        }
                    )
                else:
                    logger.warning(
                        "RPC_PROVIDERS_JSON: ignoring malformed provider entry "
                        "for chain %s (need non-empty name and url)", chain_key
                    )
            if cleaned:
                out[chain_id] = cleaned
        return out

    @property
    def indexer_start_blocks(self) -> dict:
        return _parse_json_map(self.indexer_start_blocks_json, "INDEXER_START_BLOCKS_JSON")


# Chains for which an ALCHEMY_API_KEY yields a usable RPC endpoint, and the URL
# it produces. Single source of truth: rpc_manager builds its Alchemy provider
# from this table and validate_settings decides provider coverage from the same
# keys. Two gates over one concept that drift apart is issue #87 — do not
# re-declare this set anywhere else.
ALCHEMY_RPC_URL_TEMPLATES: dict[int, str] = {
    8453: "https://base-mainnet.g.alchemy.com/v2/{key}",
    84532: "https://base-sepolia.g.alchemy.com/v2/{key}",
    1: "https://eth-mainnet.g.alchemy.com/v2/{key}",
    42161: "https://arb-mainnet.g.alchemy.com/v2/{key}",
}

_HEX_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def _parse_json_map(raw: str, name: str = "JSON map") -> dict:
    """Parse a JSON object env string into a dict; {} on empty/invalid.

    Malformed input WARNS, matching what RPC_PROVIDERS_JSON already does. It
    used to return `{}` in silence, which for the router maps means the indexer
    is disabled and payment detection stops with no log line naming the cause.
    Empty stays quiet: unset is a legitimate state and the callers that care
    already say so at startup.
    """
    if not raw:
        return {}
    import json
    try:
        val = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning(
            "%s: malformed JSON — ignoring the value, the map is EMPTY. "
            "Anything that reads it is now disabled.", name,
        )
        return {}
    if not isinstance(val, dict):
        logger.warning(
            "%s: JSON parsed as %s, expected an object — ignoring the value, "
            "the map is EMPTY. Anything that reads it is now disabled.",
            name, type(val).__name__,
        )
        return {}
    return val


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

    # ── RPC provider coverage (per chain, vendor-neutral) ──
    # ALCHEMY_API_KEY used to be an unconditional error. That made a
    # dual-provider deployment behave as a single-provider one: a merchant with
    # a healthy second vendor still could not remove a quota-exhausted Alchemy
    # key, because startup refused without it (incident 2026-08-28).
    #
    # What actually matters is that every chain the indexer watches has at
    # least one CONFIGURED provider — Alchemy, or an RPC_PROVIDERS_JSON entry.
    # rpc_manager's built-in public fallbacks deliberately do NOT count: they
    # are best-effort and rate-limited, and a chain keys the payment cursor,
    # the test/live stamp and the on-chain invoice id. Name the chain, never a
    # vendor — the old message sent operators to one signup page, which is why
    # the reflex fix was "put the dead key back" instead of "configure a
    # provider".
    _uncovered: list[str] = []
    _extra_providers = settings.rpc_extra_providers or {}
    for _chain_key in (settings.rsends_router_addresses or {}):
        try:
            _cid = int(_chain_key)
        except (TypeError, ValueError):
            continue  # a non-numeric key is already reported by the map checks
        _has_alchemy = bool(settings.alchemy_api_key) and _cid in ALCHEMY_RPC_URL_TEMPLATES
        if not _has_alchemy and not _extra_providers.get(_cid):
            _uncovered.append(str(_cid))
    if _uncovered:
        errors.append(
            f"No RPC provider is configured for chain(s) {', '.join(_uncovered)}. "
            "Only the built-in best-effort public endpoints remain, which are "
            "rate-limited and unfit as the sole source for a chain that keys the "
            "payment cursor, the test/live stamp and the invoice id. Set "
            "ALCHEMY_API_KEY (it serves chains "
            f"{', '.join(str(c) for c in sorted(ALCHEMY_RPC_URL_TEMPLATES))}), or add "
            "an entry for each chain above to RPC_PROVIDERS_JSON."
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

    # A router map that is PRESENT but does not parse is a typo in one of the
    # env vars the money path depends on. The parsed map is {} and, before the
    # parser learned to warn, nothing said so — the indexer just never started.
    # Empty is still only a warning (a not-yet-configured deployment is a real
    # state); *malformed* is an error in prod, because it is never intentional.
    for _env, _json_attr, _map_attr in (
        ("RSENDS_ROUTER_ADDRESSES_JSON", "rsends_router_addresses_json", "rsends_router_addresses"),
        ("RSENDS_ROUTER_V2_ADDRESSES_JSON", "rsends_router_v2_addresses_json", "rsends_router_v2_addresses"),
        ("SPLIT_ROUTER_ADDRESSES_JSON", "split_router_addresses_json", "split_router_addresses"),
    ):
        _raw = (getattr(settings, _json_attr, "") or "").strip()
        if _raw and not (getattr(settings, _map_attr, {}) or {}):
            _msg = (
                f"{_env} is set but does not parse to a JSON object. The map is "
                f"EMPTY, so everything reading it (indexer chains, router lookups, "
                f"split availability) is silently disabled. Fix the value, or unset "
                f"it deliberately."
            )
            (errors if is_prod else warnings).append(_msg)

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
