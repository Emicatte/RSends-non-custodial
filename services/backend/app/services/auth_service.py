"""
RPagos Backend — End-user auth service.

Responsibilities:
- Verify Google ID tokens via google-auth (canonical Google-blessed path,
  handles public key caching + iss/aud/exp validation).
- Issue + verify HS256 access tokens (via PyJWT).
- Create / rotate / revoke sessions backed by Redis.
- Fail closed when Redis is unavailable (auth is security-critical).

Cookies + DB backup rows are created in the route handler — this module
only owns token + Redis session state.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import threading
import time
from typing import Optional, Tuple

import jwt  # PyJWT
from jwt import InvalidTokenError
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as g_requests
from pydantic import BaseModel

from app.config import get_settings
from app.services.cache_service import get_redis

logger = logging.getLogger(__name__)

# ─── Session / token TTLs ─────────────────────────────────────
ACCESS_TOKEN_TTL = 15 * 60              # 15 min
REFRESH_TOKEN_TTL = 7 * 24 * 60 * 60    # 7 days

SESSION_REDIS_PREFIX = "auth:session:"
SESSION_REDIS_TTL = REFRESH_TOKEN_TTL


class GoogleUserInfo(BaseModel):
    sub: str
    email: str
    email_verified: bool
    name: Optional[str] = None
    picture: Optional[str] = None
    locale: Optional[str] = None


class AuthError(Exception):
    """Raised on any auth validation failure.

    `code` is a short machine-readable string; the HTTP route layer maps it
    to a status code + audit event_type.
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ─── Google ID token verification ─────────────────────────────

# Module-level JWKS cache. google-auth's verify_oauth2_token calls
# request(url=GOOGLE_CERTS_URL) on every token verification. Its in-process
# cert cache dies on every worker restart (frequent on Render free-tier), so
# we layer a 1h TTL cache keyed by URL to amortize the outbound HTTPS fetch
# (free-tier egress can stall 10-30 s, overrunning upstream proxy timeouts).
_certs_cache: dict[str, tuple[float, object]] = {}
_certs_lock = threading.Lock()
_CERTS_TTL_S = 3600


class _CachingRequest(g_requests.Request):
    # threading.Lock (not asyncio.Lock) because this is driven from inside
    # asyncio.to_thread. Also bounds the outbound timeout to 60 s so a
    # stuck fetch surfaces as an error well inside Vercel's 25 s cap.
    def __call__(
        self,
        url,
        method="GET",
        body=None,
        headers=None,
        timeout=60,
        **kwargs,
    ):
        now = time.monotonic()
        if method == "GET":
            with _certs_lock:
                hit = _certs_cache.get(url)
                if hit and hit[0] > now:
                    return hit[1]
        resp = super().__call__(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )
        if method == "GET" and 200 <= resp.status < 300:
            with _certs_lock:
                _certs_cache[url] = (now + _CERTS_TTL_S, resp)
        return resp


_g_request_cache: Optional[_CachingRequest] = None


def _google_request() -> _CachingRequest:
    """Cached Request instance with per-URL JWKS caching."""
    global _g_request_cache
    if _g_request_cache is None:
        _g_request_cache = _CachingRequest()
    return _g_request_cache


async def verify_google_id_token(
    token: str,
    expected_nonce: Optional[str] = None,
) -> GoogleUserInfo:
    """Verify a Google ID token. Returns GoogleUserInfo or raises AuthError.

    google-auth validates signature + iss + aud + exp against Google's
    published JWKS. We additionally check nonce + email_verified.

    The underlying call is sync + uses urllib → wrap in a thread so the
    event loop stays free under concurrent logins.
    """
    settings = get_settings()
    if not settings.google_oauth_client_id:
        raise AuthError("server_misconfigured", "GOOGLE_OAUTH_CLIENT_ID is not set")

    try:
        claims = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            token,
            _google_request(),
            settings.google_oauth_client_id,
        )
    except ValueError as e:
        raise AuthError("invalid_token", f"Google ID token rejected: {e}")

    if expected_nonce and claims.get("nonce") != expected_nonce:
        raise AuthError("invalid_nonce", "Nonce mismatch")

    if not claims.get("email_verified"):
        raise AuthError("email_not_verified", "Google email not verified")

    return GoogleUserInfo(
        sub=claims["sub"],
        email=claims["email"],
        email_verified=bool(claims["email_verified"]),
        name=claims.get("name"),
        picture=claims.get("picture"),
        locale=claims.get("locale"),
    )


# ─── Access token (HS256 via PyJWT) ───────────────────────────

def _make_access_token(user_id: str, session_id: str) -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "sid": session_id,
            "typ": "access",
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )


async def verify_access_token(token: str) -> dict:
    """Decode an access token + confirm the session is still live in Redis.

    Raises AuthError on any failure.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token, settings.auth_jwt_secret, algorithms=["HS256"]
        )
    except InvalidTokenError as e:
        raise AuthError("invalid_token", f"Access token invalid: {e}")

    if claims.get("typ") != "access":
        raise AuthError("invalid_token", "Not an access token")

    sid = claims.get("sid")
    if not sid:
        raise AuthError("invalid_token", "Missing sid claim")

    r = await get_redis()
    if r is None:
        raise AuthError("auth_unavailable", "Session store unavailable")
    raw = await r.get(f"{SESSION_REDIS_PREFIX}{sid}")
    if not raw:
        raise AuthError("session_revoked", "Session not found or expired")

    return claims


# ─── Session lifecycle ────────────────────────────────────────

async def create_session(
    *,
    user_id: str,
    ip: str,
    user_agent: str,
) -> Tuple[str, str, str, str]:
    """Create a new session.

    Returns (session_id, access_token, refresh_token, refresh_token_hash).
    The route handler persists a UserSession row for audit backup.
    """
    # GDPR: block login for users whose grace period has already elapsed.
    # In-grace users (scheduled_for > now) are still allowed in so they can
    # reach the cancel button. Lazy import keeps this module's import graph
    # free of SQLAlchemy at top level.
    from datetime import datetime, timezone
    from sqlalchemy import select as _select
    from app.db.session import async_session as _async_session
    from app.models.auth_models import User as _User

    async with _async_session() as _check_db:
        _u = (
            await _check_db.execute(_select(_User).where(_User.id == user_id))
        ).scalar_one_or_none()
        if (
            _u is not None
            and _u.deletion_scheduled_for is not None
            and _u.deletion_scheduled_for < datetime.now(timezone.utc)
        ):
            raise AuthError("account_deleted", "This account has been deleted")

    session_id = secrets.token_hex(32)
    refresh_token = secrets.token_urlsafe(48)
    refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

    r = await get_redis()
    if r is None:
        raise AuthError("auth_unavailable", "Session store unavailable")

    await r.set(
        f"{SESSION_REDIS_PREFIX}{session_id}",
        json.dumps({
            "user_id": user_id,
            "refresh_hash": refresh_hash,
            "ip": ip,
            "ua_hash": hashlib.sha256(user_agent.encode()).hexdigest()[:16],
            "created_at": int(time.time()),
        }),
        ex=SESSION_REDIS_TTL,
    )

    # Fire-and-forget: record device + maybe send "new device" email.
    # Lazy import keeps auth_service free of celery/task deps at module load.
    # Any failure (broker down, task module import error) is swallowed —
    # a notification hiccup must never break login.
    try:
        from app.tasks.email_tasks import send_new_device_email_task
        send_new_device_email_task.delay(
            user_id=user_id, ip=ip, user_agent=user_agent
        )
    except Exception:
        logger.exception("email_task_dispatch_failed")

    access_token = _make_access_token(user_id, session_id)
    return session_id, access_token, refresh_token, refresh_hash


async def rotate_refresh_token(
    *,
    session_id: str,
    old_refresh_token: str,
    ip: str,
) -> Tuple[str, str, str]:
    """Rotate refresh token (one-time-use).

    Returns (new_access_token, new_refresh_token, user_id).

    Security: if the provided refresh token hash does NOT match the stored
    hash, we treat it as possible theft → revoke the session immediately and
    raise `refresh_reuse_detected`.
    """
    r = await get_redis()
    if r is None:
        raise AuthError("auth_unavailable", "Session store unavailable")

    key = f"{SESSION_REDIS_PREFIX}{session_id}"
    raw = await r.get(key)
    if not raw:
        raise AuthError("session_revoked", "Session not found")

    data = json.loads(raw)
    expected_hash = data["refresh_hash"]
    provided_hash = hashlib.sha256(old_refresh_token.encode()).hexdigest()

    if not secrets.compare_digest(provided_hash, expected_hash):
        # Possible token theft — revoke the whole session
        await r.delete(key)
        raise AuthError(
            "refresh_reuse_detected",
            "Refresh token reuse — session revoked",
        )

    # Rotate
    new_refresh = secrets.token_urlsafe(48)
    new_refresh_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
    data["refresh_hash"] = new_refresh_hash
    data["ip"] = ip
    data["rotated_at"] = int(time.time())
    await r.set(key, json.dumps(data), ex=SESSION_REDIS_TTL)

    new_access = _make_access_token(data["user_id"], session_id)
    return new_access, new_refresh, data["user_id"]


async def revoke_session(session_id: str) -> None:
    """Revoke a session instantly. No-op if Redis is down (best effort)."""
    r = await get_redis()
    if r is None:
        return
    await r.delete(f"{SESSION_REDIS_PREFIX}{session_id}")


def peek_unverified_email(id_token_str: str) -> Optional[str]:
    """Extract `email` claim from an ID token WITHOUT verifying.

    ONLY for use as a rate-limit bucket key. Never trust this value as identity.
    Returns None if the token is malformed.
    """
    try:
        return jwt.decode(
            id_token_str,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False},
            algorithms=["RS256", "HS256"],
        ).get("email")
    except Exception:
        return None
