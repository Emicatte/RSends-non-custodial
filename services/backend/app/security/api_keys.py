"""
RSend API Key Authentication

Ogni client (merchant) ha una API key unica.
La key viene inviata nell'header: Authorization: Bearer rsend_xxx

Per ora: le key sono in un dict (poi DB/Redis in produzione).
L'endpoint webhook Alchemy è ESENTE (usa HMAC).
Health check è ESENTE.
Debug mode = auth disabilitata.
"""
import bcrypt
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from typing import Optional

from fastapi import Request, HTTPException

from app.config import get_settings

logger = logging.getLogger("api_keys")

PREFIX_LEN = 24

# The only environments a key may carry. Kept in step with
# app.models.api_key_models.KeyEnvironment, which enforces the same set on the
# column; importing it here would be a cycle (models import this module's peers).
_VALID_ENVIRONMENTS = frozenset({"test", "live"})

# Endpoints esenti da API key auth
EXEMPT_PATHS = {
    "/health",
    "/health/ready",
    "/health/rpc",
    "/health/config",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/ws/",  # WebSocket
    "/api/v1/keys",  # Key management uses wallet address, not API key
    # ── JWT-authenticated user & org endpoints ──
    "/api/v1/auth",            # OAuth + email login/signup/refresh/logout/me
    "/api/v1/user/",           # routes, transactions, contacts, notifications,
                               # wallets, account, api-keys (JWT via require_user_id)
    "/api/v1/organizations",   # org CRUD + memberships + invites (JWT)
    "/api/v1/invites",         # invite preview/accept/decline (JWT)
    # ── Wallet-signature auth (X-Wallet-Address + X-Wallet-Signature) ──
    "/api/v1/distributions",   # require_wallet_auth
    "/api/v1/forwarding",      # sweeper forwarding/*, require_wallet_auth
    # ── Admin token / internal ──
    "/api/v1/audit",           # X-Admin-Token
    "/admin/approvals",        # X-Admin-Token (require_admin on the router)
    "/api/internal/signing",   # called by Next.js oracle, internal-only
    "/api/internal/oracle",    # oracle digest signer, internal-only (M1)
    # ── HMAC-signed ingestion ──
    "/api/v1/tx/callback",     # verify_signature() (HMAC)
}

def is_exempt(path: str) -> bool:
    """Check if path is exempt from API key auth."""
    for exempt in EXEMPT_PATHS:
        if path.startswith(exempt):
            return True
    return False


# ── M8: GET deny-by-default allowlist ─────────────────────────────
# Non-exempt GET paths that may be reached WITHOUT an API key under
# deny-by-default. Two kinds:
#   - self-authenticating: the handler enforces its own auth via a route
#     dependency or @require_wallet_auth (X-Admin-Token / wallet signature),
#     which runs INSIDE the handler — the middleware must let the GET through.
#   - genuinely public: open reads by design (price feed, public checkout
#     status, health probe, account-header recent tx).
GET_PUBLIC_PREFIXES = {
    # self-authenticating (own dependency runs in the handler)
    "/api/v1/ledger",                   # require_admin
    "/admin/aml",                       # require_admin
    "/api/v1/splits",                   # @require_wallet_auth
    "/api/v1/dashboard",                # @require_wallet_auth
    # genuinely public
    "/api/v1/prices",                   # public price feed
    "/api/v1/health/sweep",             # public health probe (sweeper router)
    "/api/v1/public/payment-intent",    # hosted checkout status — id-as-secret, limited view
    "/api/v1/tx/recent",                # account-header recent tx (public read)
}


def is_get_public(path: str) -> bool:
    """True if a GET to `path` may proceed without an API key (M8 allowlist)."""
    for prefix in GET_PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def hash_api_key(key: str) -> str:
    """Hash an API key for storage (v1 SHA-256). Kept for legacy lookups."""
    return hashlib.sha256(key.encode()).hexdigest()


def _v2_hash(key: str) -> str:
    """Hash an API key with bcrypt (v2). Per-key salt, cost factor 12."""
    return bcrypt.hashpw(key.encode(), bcrypt.gensalt(rounds=12)).decode()


def _v2_verify(key: str, hashed: str) -> bool:
    """Verify a plaintext key against a bcrypt hash."""
    try:
        return bcrypt.checkpw(key.encode(), hashed.encode())
    except Exception:
        return False


def generate_api_key(environment: str = "test") -> tuple[str, dict]:
    """Generate a new API key with v2 (bcrypt) hashing.

    Returns (plaintext_key, db_fields). The plaintext is shown once to the
    merchant and never stored. db_fields contains all columns for ApiKey —
    INCLUDING `environment`, so a caller that does `ApiKey(**db_fields)` cannot
    end up with a row whose column contradicts the prefix baked into the key
    string. Verification reads the column while the merchant reads the string;
    they must be one decision, made here.

    The value is normalized and validated rather than defaulted: the branch used
    to be `"rsend_test_" if environment == "test" else "rsend_live_"`, so any
    value that was not exactly "test" — a typo, a casing variant, an empty
    string — silently produced a live-looking key. Raises ValueError instead.
    """
    env = (environment or "").strip().lower()
    if env not in _VALID_ENVIRONMENTS:
        raise ValueError(
            f"environment must be one of {sorted(_VALID_ENVIRONMENTS)}, got {environment!r}"
        )

    plaintext = f"rsend_{env}_{secrets.token_hex(24)}"
    db_fields = {
        "key_hash": hash_api_key(plaintext),
        "key_prefix": plaintext[:PREFIX_LEN],
        "display_prefix": plaintext[:20] + "...",
        "key_hash_v2": _v2_hash(plaintext),
        "hash_version": 2,
        "environment": env,
    }
    return plaintext, db_fields


async def verify_api_key(request: Request) -> Optional[dict]:
    """
    Verify API key from Authorization header.

    Dual-path verification:
      Path 1 (v2): Lookup by key_prefix, verify with bcrypt.
      Path 2 (v1): Lookup by SHA-256 hash, auto-upgrade to v2 on success.

    Returns client info dict or None if invalid.
    """
    settings = get_settings()

    if (
        os.getenv("RSEND_DEV_AUTH_BYPASS") == "1"
        and not os.getenv("ENVIRONMENT", "").lower().startswith("prod")
    ):
        return {"client_id": "debug", "name": "Debug Mode"}

    if is_exempt(request.url.path):
        return {"client_id": "exempt", "name": "Exempt Path"}

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None

    key = auth[7:]
    if not key.startswith("rsend_"):
        return None

    from app.db.session import async_session
    from app.models.api_key_models import ApiKey
    from sqlalchemy import select

    async with async_session() as db:
        # Path 1: v2 candidates (indexed by prefix)
        prefix = key[:PREFIX_LEN]
        q = select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.hash_version == 2,
            ApiKey.is_active == True,  # noqa: E712
        )
        result = await db.execute(q)
        for candidate in result.scalars():
            if candidate.key_hash_v2 and _v2_verify(key, candidate.key_hash_v2):
                candidate.last_used_at = datetime.now(timezone.utc)
                candidate.total_requests = (candidate.total_requests or 0) + 1
                await db.commit()
                return _api_key_to_dict(candidate)

        # Path 2: v1 legacy lookup (SHA-256)
        key_hash = hash_api_key(key)
        q = select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.is_active == True,  # noqa: E712
        )
        result = await db.execute(q)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return None

        # Auto-upgrade to v2
        try:
            api_key.key_prefix = prefix
            api_key.display_prefix = api_key.display_prefix or (key[:20] + "...")
            api_key.key_hash_v2 = _v2_hash(key)
            api_key.hash_version = 2
        except Exception as e:
            logger.warning(
                "API key auto-upgrade to v2 failed for key_id=%s: %s",
                api_key.id, e,
            )

        api_key.last_used_at = datetime.now(timezone.utc)
        api_key.total_requests = (api_key.total_requests or 0) + 1
        await db.commit()

        return _api_key_to_dict(api_key)


def _api_key_to_dict(api_key) -> dict:
    return {
        # client_id (= merchant_id stamped on intents/webhooks) stays the
        # owner address until the full merchant_id re-key; org_id is the
        # key's tenant (0014) for consumers that scope by org.
        "client_id": api_key.owner_address,
        "org_id": api_key.org_id,
        "name": api_key.label,
        "key_id": api_key.id,
        "scope": api_key.scope or "write",
        "environment": api_key.environment or "live",
        "rate_limit_rpm": api_key.rate_limit_rpm or 100,
    }
