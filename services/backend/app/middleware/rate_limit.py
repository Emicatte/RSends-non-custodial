"""
RPagos Backend — Rate Limiting Middleware v2

Sliding window rate limiting con limiti per-endpoint e per-chiave:
  - Se Redis è disponibile → sliding window via sorted set
  - Se Redis non è disponibile → fallback in-memory (con warning)

Limiti configurabili per endpoint, con chiave basata su:
  - API key (merchant_id) per endpoint autenticati
  - IP address per endpoint pubblici

Limiti specifici:
  POST /api/v1/merchant/payment-intent       → 30/min  per API key
  POST /api/v1/merchant/webhook/register      → 5/hora  per API key
  GET  /api/v1/merchant/payment-intent/{id}   → 60/min  per API key
  GET  /api/v1/public/payment-intent/{id}     → 20/min  per IP (hosted checkout)
  POST /api/v1/tx/callback                    → 10/min  per IP
  GET  /api/v1/audit/log                      → 30/min  per IP
  Admin brute-force: 5/min per IP, ban 15min dopo 10 fail/ora

Headers di risposta:
  X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  Rate limit rules
# ═══════════════════════════════════════════════════════════════

# (max_requests, window_seconds, key_type)
# key_type: "api_key" = per merchant API key, "ip" = per IP
# IMPORTANT: ordered MOST-SPECIFIC-PREFIX-FIRST. `_match_endpoint` returns the
# FIRST matching prefix, so a bare prefix placed before its trailing-slash
# subpath would shadow the stricter subpath limit (dead code). The
# `payment-intent/` (cancel/resolve, 10/60) entry MUST precede the bare
# `payment-intent` (create, 100/60) entry for that reason.
ENDPOINT_LIMITS: list[tuple[str, str, int, int, str]] = [
    # method, path_prefix,                          max,  window, key_type
    ("POST", "/api/v1/merchant/payment-intent/",     10,    60,  "api_key"),  # cancel, resolve (before the bare create prefix)
    ("POST", "/api/v1/merchant/payment-intent",     100,    60,  "api_key"),  # create
    ("POST", "/api/v1/merchant/webhook/register",     5,  3600,  "api_key"),
    ("POST", "/api/v1/merchant/webhook/test",        10,    60,  "api_key"),
    ("GET",  "/api/v1/merchant/payment-intent/",     60,    60,  "api_key"),  # get by id
    ("GET",  "/api/v1/merchant/transactions",        60,    60,  "api_key"),
    ("POST", "/api/v1/public/payment-intent",        5,     60,  "ip"),  # tx hint (unauthenticated → per-IP)
    ("GET",  "/api/v1/public/payment-intent",        20,    60,  "ip"),  # hosted checkout polling (unauthenticated → per-IP)
    ("POST", "/api/v1/tx/callback",                  10,    60,  "ip"),
    ("GET",  "/api/v1/audit/log",                    30,    60,  "ip"),
    # Admin approval surface (X-Admin-Token, server-to-server). Most-specific
    # first: the decision subpaths (trailing slash) precede the bare list.
    ("POST", "/admin/approvals/",                    30,    60,  "ip"),  # approve/decline
    ("GET",  "/admin/approvals",                     60,    60,  "ip"),  # queue list
    # Org admin mutations (settlement_wallet, member roles, …) — per-IP.
    ("PATCH", "/api/v1/organizations",               30,    60,  "ip"),
    # End-user auth (session mgmt)
    ("POST", "/api/v1/auth/refresh",                 20,    60,  "ip"),   # 20/min
    ("POST", "/api/v1/auth/logout",                  30,    60,  "ip"),   # 30/min
    # Session-authed org payments (Phase C read / Phase D create+cancel) — per-IP
    # (JWT, no API key). Most-specific-prefix-first: the cancel subpath (trailing
    # slash) MUST precede the bare create prefix so _match_endpoint doesn't shadow it.
    ("POST",   "/api/v1/user/org/payment-intents/", 30,     60,  "ip"),  # cancel
    ("POST",   "/api/v1/user/org/payment-intents",  30,     60,  "ip"),  # create
    ("GET",    "/api/v1/user/org/payment-intents",  120,    60,  "ip"),
    # Session-authed org webhooks (Phase E) — per-IP. Trailing-slash prefix
    # (test-fire under /webhooks/{id}/test) MUST precede the bare register entry.
    # This entry also covers POST /webhooks/{id}/enable (auto-disable remedy):
    # `_match_endpoint` is first-matching-prefix-wins and `{id}` is variable, so
    # any /webhooks/{id}/... POST lands here. Sharing is deliberate — 10/min per
    # IP is generous for re-enabling, and isolating it would mean reshaping the
    # URL rather than fixing a problem. See user_org_webhooks_routes.enable_org_webhook.
    ("POST",   "/api/v1/user/org/webhooks/",         10,    60,  "ip"),  # {id}/test, {id}/enable
    ("POST",   "/api/v1/user/org/webhooks",           5,  3600,  "ip"),  # register
    ("GET",    "/api/v1/user/org/webhooks",          120,    60,  "ip"),  # list + deliveries
    # Session-minted rsend_ merchant keys (Option B, 2026-07-15) — per-IP.
    # Trailing-slash prefix ({id}/revoke) MUST precede the bare mint entry.
    ("POST",   "/api/v1/user/org/merchant-keys/",    10,    60,  "ip"),  # {id}/revoke
    ("POST",   "/api/v1/user/org/merchant-keys",      5,  3600,  "ip"),  # mint
    ("GET",    "/api/v1/user/org/merchant-keys",     120,    60,  "ip"),  # list
    # AutoSplit source wallets — per-IP. The trailing-slash prefix covers the
    # SIWE pair (/challenge, /verify) and {id}/disable, and MUST precede the
    # bare GET: _match_endpoint returns the first startswith hit, so a bare
    # entry placed above would shadow the write rule into dead code.
    ("POST",   "/api/v1/user/org/source-wallets/",   10,    60,  "ip"),
    ("GET",    "/api/v1/user/org/source-wallets",   120,    60,  "ip"),
    # Session-authed org stats (Phase E) — per-IP. The volume-series SUBPATH must
    # precede the bare `stats` prefix: _match_endpoint returns the first
    # startswith hit, so the bare entry would otherwise shadow it into dead code.
    # Lower ceiling than the tiles because the /app card does not poll it.
    ("GET",    "/api/v1/user/org/stats/volume-series", 60,   60,  "ip"),
    ("GET",    "/api/v1/user/org/stats",             120,    60,  "ip"),
    # Session-authed onboarding (state, consents, company profile) — per-IP
    # (JWT, no API key). The submit subpath MUST precede the bare
    # company-profile prefix (most-specific-prefix-first).
    ("POST",   "/api/v1/user/org/company-profile/submit", 10, 60, "ip"),
    ("PATCH",  "/api/v1/user/org/company-profile",   60,    60,  "ip"),  # debounced autosave
    ("GET",    "/api/v1/user/org/company-profile",  120,    60,  "ip"),
    ("GET",    "/api/v1/user/onboarding",           120,    60,  "ip"),
    ("POST",   "/api/v1/user/consents",              10,    60,  "ip"),
    # User-scoped saved-routes CRUD (defense in depth over the auth gate)
    ("POST",   "/api/v1/user/routes",                30,    60,  "ip"),
    ("PATCH",  "/api/v1/user/routes",                60,    60,  "ip"),
    ("DELETE", "/api/v1/user/routes",                30,    60,  "ip"),
    ("GET",    "/api/v1/user/routes",               120,    60,  "ip"),
]


# Admin brute-force protection
ADMIN_RATE_LIMIT = (5, 60)             # 5 attempts/min per IP
ADMIN_BAN_THRESHOLD = 10               # 10 failed attempts in 1 hour
ADMIN_BAN_WINDOW = 3600                # 1 hour window for counting failures
ADMIN_BAN_DURATION = 900               # 15 min ban

DEFAULT_GET_LIMIT = (60, 60)
DEFAULT_POST_LIMIT = (30, 60)

# ── Per-intent ceiling on the hosted checkout poll ────────────
#
# The public status view is unauthenticated AND every request runs a live
# quoteFee eth_call (public_routes.get_public_payment_intent →
# router_registry.build_onchain_payment, uncached), so it amplifies one cheap
# HTTP request into paid RPC work. The per-IP rule above bounds a single
# address; it bounds nothing against a caller holding several. This second
# bucket is keyed on the intent ALONE and is what actually caps the RPC spend
# one payment link can cause.
#
# Sized well clear of legitimate use: at the checkout's steady 6 req/min this is
# ~20 concurrent watchers on one link, while capping the endpoint at 4 eth_calls
# per second per intent no matter how many addresses are polling.
#
# NOTE: this bound used to exist by accident. Before the client IP reached the
# backend every request carried the same proxy address, so the per-IP bucket was
# in effect a global one. Making IPs real removed that; this restores it on
# purpose.
PUBLIC_INTENT_PREFIX = "/api/v1/public/payment-intent"
PUBLIC_INTENT_GLOBAL_LIMIT = (240, 60)

# Paths exempt from rate limiting entirely
RATE_LIMIT_EXEMPTIONS: set[str] = set()


# ═══════════════════════════════════════════════════════════════
#  In-memory fallback
# ═══════════════════════════════════════════════════════════════

class InMemoryRateLimiter:
    """Fallback in-memory sliding window usando liste di timestamp."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        # Periodic cleanup counter
        self._ops = 0

    def check(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, reset_epoch)."""
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            self._ops += 1
            # Periodic cleanup every 1000 ops to prevent memory leak
            if self._ops % 1000 == 0:
                self._cleanup(now)

            bucket = self._buckets[key]
            self._buckets[key] = [t for t in bucket if t > window_start]
            self._buckets[key].append(now)
            count = len(self._buckets[key])

        remaining = max(0, max_requests - count)
        reset_epoch = int(now + window_seconds)
        allowed = count <= max_requests

        return allowed, remaining, reset_epoch

    def count(self, key: str, window_seconds: int) -> int:
        """Count entries in window without adding a new one."""
        now = time.time()
        window_start = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key, [])
            return sum(1 for t in bucket if t > window_start)

    def record(self, key: str) -> None:
        """Record a timestamp without checking limits."""
        now = time.time()
        with self._lock:
            self._buckets[key].append(now)

    def _cleanup(self, now: float) -> None:
        """Remove stale keys (older than 1 hour)."""
        stale_keys = [
            k for k, v in self._buckets.items()
            if not v or v[-1] < now - 3600
        ]
        for k in stale_keys:
            del self._buckets[k]


_memory_limiter = InMemoryRateLimiter()
_redis_warned = False


# ═══════════════════════════════════════════════════════════════
#  Redis sliding window
# ═══════════════════════════════════════════════════════════════

async def _check_redis(
    key: str, max_requests: int, window_seconds: int,
) -> tuple[bool, int, int]:
    """Sliding window via Redis sorted set.

    Returns (allowed, remaining, reset_epoch).
    """
    from app.services.cache_service import get_redis

    r = await get_redis()
    now = time.time()
    window_start = now - window_seconds

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {str(now): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    results = await pipe.execute()

    count = results[2]
    remaining = max(0, max_requests - count)
    reset_epoch = int(now + window_seconds)
    allowed = count <= max_requests

    return allowed, remaining, reset_epoch


async def _redis_count(key: str, window_seconds: int) -> int:
    """Count entries in a Redis sorted set window without adding."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    now = time.time()
    window_start = now - window_seconds

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    results = await pipe.execute()
    return results[1]


async def _redis_record(key: str, window_seconds: int) -> None:
    """Record a timestamp in a Redis sorted set."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    now = time.time()
    pipe = r.pipeline()
    pipe.zadd(key, {str(now): now})
    pipe.expire(key, window_seconds)
    await pipe.execute()


async def _redis_is_banned(key: str) -> bool:
    """Check if a ban key exists in Redis."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    return await r.exists(key) > 0


async def _redis_ban(key: str, duration: int) -> None:
    """Set a ban key with TTL."""
    from app.services.cache_service import get_redis

    r = await get_redis()
    await r.setex(key, duration, "1")


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _get_client_ip(request: Request) -> str:
    """Estrai il client IP reale (dietro reverse proxy)."""
    from app.security.trusted_proxy import get_real_client_ip

    return get_real_client_ip(request)


def _get_api_key_id(request: Request) -> str | None:
    """Estrai l'API key identifier dal request (set by APIKeyMiddleware)."""
    client = getattr(request.state, "client", None)
    if client and isinstance(client, dict):
        return client.get("client_id")
    # Fallback: estrarre dall'header Authorization prima che il middleware lo processi
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            return token[:24]  # Use prefix as identifier (no full key in Redis)
    return None


def _public_intent_id(path: str) -> str | None:
    """The intent id from a public checkout status path, or None if this is not
    one. Deliberately narrow: the ceiling belongs to intent polling, not to
    `/public/*` in general."""
    if not path.startswith(PUBLIC_INTENT_PREFIX + "/"):
        return None
    intent_id = path[len(PUBLIC_INTENT_PREFIX):].strip("/")
    return intent_id or None


def _match_endpoint(method: str, path: str) -> tuple[int, int, str] | None:
    """Trova il limite specifico per questo endpoint."""
    for rule_method, rule_prefix, max_req, window, key_type in ENDPOINT_LIMITS:
        if method == rule_method and path.startswith(rule_prefix):
            return max_req, window, key_type
    return None


def _make_rate_headers(max_req: int, remaining: int, reset_epoch: int) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(max_req),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_epoch),
    }


def _make_429(max_req: int, remaining: int, reset_epoch: int, retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "error": "RATE_LIMIT_EXCEEDED",
            "retry_after": retry_after,
        },
        headers={
            **_make_rate_headers(max_req, remaining, reset_epoch),
            "Retry-After": str(retry_after),
        },
    )


# ═══════════════════════════════════════════════════════════════
#  Admin brute-force tracking
# ═══════════════════════════════════════════════════════════════

# In-memory ban set (fallback)
_ip_bans: dict[str, float] = {}
_ip_bans_lock = Lock()


async def _check_admin_ban(ip: str) -> bool:
    """Check if IP is banned from admin access."""
    ban_key = f"admin_ban:{ip}"
    try:
        return await _redis_is_banned(ban_key)
    except Exception:
        with _ip_bans_lock:
            ban_until = _ip_bans.get(ip, 0)
            if ban_until > time.time():
                return True
            elif ip in _ip_bans:
                del _ip_bans[ip]
        return False


async def record_admin_failure(ip: str) -> None:
    """Record a failed admin auth attempt. Ban IP if threshold exceeded."""
    fail_key = f"admin_fail:{ip}"
    ban_key = f"admin_ban:{ip}"

    try:
        await _redis_record(fail_key, ADMIN_BAN_WINDOW)
        fail_count = await _redis_count(fail_key, ADMIN_BAN_WINDOW)
        if fail_count >= ADMIN_BAN_THRESHOLD:
            await _redis_ban(ban_key, ADMIN_BAN_DURATION)
            logger.warning("Admin IP banned: %s (%d failures in window)", ip, fail_count)
    except Exception:
        _memory_limiter.record(fail_key)
        fail_count = _memory_limiter.count(fail_key, ADMIN_BAN_WINDOW)
        if fail_count >= ADMIN_BAN_THRESHOLD:
            with _ip_bans_lock:
                _ip_bans[ip] = time.time() + ADMIN_BAN_DURATION
            logger.warning("Admin IP banned (in-memory): %s (%d failures)", ip, fail_count)


# ═══════════════════════════════════════════════════════════════
#  Middleware
# ═══════════════════════════════════════════════════════════════

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        global _redis_warned

        path = request.url.path
        method = request.method

        # Skip health checks and metrics
        if path.startswith("/health") or path == "/metrics":
            return await call_next(request)

        # Skip exempt paths
        if path in RATE_LIMIT_EXEMPTIONS:
            return await call_next(request)

        client_ip = _get_client_ip(request)

        # ── Admin brute-force protection ─────────────────────
        if path.startswith("/api/v1/audit/"):
            if await _check_admin_ban(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "RATE_LIMIT_EXCEEDED",
                        "retry_after": ADMIN_BAN_DURATION,
                        "message": "Too many failed attempts. Try again later.",
                    },
                    headers={"Retry-After": str(ADMIN_BAN_DURATION)},
                )

        # ── Global per-key rate limit ────────────────────────
        client = getattr(request.state, "client", None)
        if client and client.get("key_id"):
            _key_id = client["key_id"]
            _rpm = client.get("rate_limit_rpm", 100)
            _global_rl_key = f"rl:global:key:{_key_id}"
            try:
                _allowed, _remaining, _reset = await _check_redis(_global_rl_key, _rpm, 60)
            except Exception:
                from app.config import get_settings
                if not get_settings().debug:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": "RATE_LIMIT_UNAVAILABLE",
                            "message": "Rate limiting service temporarily unavailable — retry later",
                        },
                        headers={"Retry-After": "5"},
                    )
                _allowed, _remaining, _reset = _memory_limiter.check(_global_rl_key, _rpm, 60)
            if not _allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "KEY_RATE_LIMIT_EXCEEDED",
                        "message": f"API key rate limit exceeded: {_rpm} requests/minute",
                    },
                    headers=_make_rate_headers(_rpm, 0, _reset),
                )

        # ── Determine rate limit key and limits ──────────────
        endpoint_rule = _match_endpoint(method, path)
        if endpoint_rule:
            max_req, window, key_type = endpoint_rule
            if key_type == "api_key":
                api_key_id = _get_api_key_id(request)
                rl_key = f"rl:key:{api_key_id or client_ip}:{method}:{path.split('?')[0]}"
            else:
                rl_key = f"rl:ip:{client_ip}:{method}:{path.split('?')[0]}"
        else:
            # Default limits
            if method == "GET":
                max_req, window = DEFAULT_GET_LIMIT
            else:
                max_req, window = DEFAULT_POST_LIMIT
            rl_key = f"rl:ip:{client_ip}:{method}:{path.rsplit('/', 1)[0]}"

        # ── Check rate limit ─────────────────────────────────
        try:
            allowed, remaining, reset_epoch = await _check_redis(rl_key, max_req, window)
        except Exception:
            if not _redis_warned:
                logger.warning("Redis unavailable for rate limiting — using in-memory fallback")
                _redis_warned = True

            # F-BE-10: in production with multiple workers, in-memory fallback
            # gives effective_limit = N_workers × configured_limit. Fail closed.
            from app.config import get_settings
            if not get_settings().debug:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "RATE_LIMIT_UNAVAILABLE",
                        "message": "Rate limiting service temporarily unavailable — retry later",
                    },
                    headers={"Retry-After": "5"},
                )

            allowed, remaining, reset_epoch = _memory_limiter.check(rl_key, max_req, window)

        rate_headers = _make_rate_headers(max_req, remaining, reset_epoch)

        if not allowed:
            return _make_429(max_req, remaining, reset_epoch, retry_after=window)

        # ── Per-intent ceiling (hosted checkout only) ────────
        # Checked AFTER the per-IP rule, and only for requests that rule let
        # through: an address already over its own allowance must not spend the
        # budget shared by everyone else watching the same link.
        intent_id = _public_intent_id(path)
        if intent_id is not None:
            _i_max, _i_window = PUBLIC_INTENT_GLOBAL_LIMIT
            _i_key = f"rl:intent:{intent_id}"
            try:
                _i_allowed, _i_remaining, _i_reset = await _check_redis(
                    _i_key, _i_max, _i_window
                )
            except Exception:
                from app.config import get_settings
                if not get_settings().debug:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": "RATE_LIMIT_UNAVAILABLE",
                            "message": "Rate limiting service temporarily unavailable — retry later",
                        },
                        headers={"Retry-After": "5"},
                    )
                _i_allowed, _i_remaining, _i_reset = _memory_limiter.check(
                    _i_key, _i_max, _i_window
                )

            if not _i_allowed:
                # Same envelope as every other 429 — `{error, retry_after}` is a
                # frozen promise (docs/INTEGRATION_CONTRACT.md §9).
                return _make_429(
                    _i_max, _i_remaining, _i_reset, retry_after=_i_window
                )

        # ── Execute request ──────────────────────────────────
        response = await call_next(request)

        # ── Track admin auth failures ────────────────────────
        if path.startswith("/api/v1/audit/") and response.status_code == 403:
            await record_admin_failure(client_ip)

        # ── Attach rate limit headers ────────────────────────
        for k, v in rate_headers.items():
            response.headers[k] = v

        return response
