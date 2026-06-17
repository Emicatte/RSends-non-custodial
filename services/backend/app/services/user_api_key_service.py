"""User API key lifecycle: generate, hash, verify, rate-limit.

Coexists with merchant keys (app/security/api_keys.py). Zero import across
the two — bcrypt primitives are re-implemented locally (5 lines) to keep the
systems decoupled per the Prompt 9 "0 dependency incrociata" constraint.

Key format: rsusr_live_<30-char-urlsafe-token> (~40 chars).
Hashing: bcrypt v1 (cost=12), hash_version reserved for future migrations.
Rate limit: Redis fixed-window counter, 60 rpm per key default. Gracefully
degrades (allow) if Redis is down — rate limiting is defensive, not a
security boundary.
"""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple, TYPE_CHECKING

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cache_service import get_redis

if TYPE_CHECKING:
    from app.models.user_api_keys_models import UserApiKey

log = logging.getLogger(__name__)

KEY_PREFIX_RAW = "rsusr_live_"
# "rsusr_live_" (11 chars) + 12 chars of token = 23 chars for index lookup.
KEY_PREFIX_LEN = 23
BCRYPT_ROUNDS = 12
# Prompt 11: the cap is per-ORG, not per-user. Team members collectively share
# the quota. `MAX_KEYS_PER_USER` retained as a back-compat alias for anything
# that might still import the old name.
MAX_KEYS_PER_ORG = 5
MAX_KEYS_PER_USER = MAX_KEYS_PER_ORG  # deprecated alias
DEFAULT_RATE_LIMIT_RPM = 60
RATE_LIMIT_REDIS_PREFIX = "user_api_key_rl:"


class UserApiKeyError(Exception):
    """Auth/verification failures with a stable `code` for the API layer."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _generate_plaintext() -> Tuple[str, str, str]:
    """Returns (plaintext, key_prefix, display_prefix).

    - plaintext: full key given to user ONCE
    - key_prefix: first 23 chars ("rsusr_live_" + 12), indexed for fast lookup
    - display_prefix: truncated UI rendering "rsusr_live_abcdefg...XyZ9"
    """
    random_part = secrets.token_urlsafe(30)  # ~40 chars url-safe
    plaintext = f"{KEY_PREFIX_RAW}{random_part}"
    key_prefix = plaintext[:KEY_PREFIX_LEN]
    display_prefix = f"{plaintext[:18]}...{plaintext[-4:]}"
    return plaintext, key_prefix, display_prefix


def _hash_key(plaintext: str) -> str:
    """Bcrypt hash of plaintext. CPU-bound (~100-300ms at cost=12)."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def _verify_key(plaintext: str, stored_hash: str) -> bool:
    """Constant-time verification. ValueError on malformed hash → False."""
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def count_active_keys_for_org(db: AsyncSession, org_id: str) -> int:
    from app.models.user_api_keys_models import UserApiKey

    result = await db.execute(
        select(func.count())
        .select_from(UserApiKey)
        .where(
            UserApiKey.org_id == org_id,
            UserApiKey.is_active.is_(True),
            UserApiKey.revoked_at.is_(None),
        )
    )
    return int(result.scalar() or 0)


# Back-compat alias for any remaining callers — counts by user_id.
async def count_active_keys(db: AsyncSession, user_id: str) -> int:
    from app.models.user_api_keys_models import UserApiKey

    result = await db.execute(
        select(func.count())
        .select_from(UserApiKey)
        .where(
            UserApiKey.user_id == user_id,
            UserApiKey.is_active.is_(True),
            UserApiKey.revoked_at.is_(None),
        )
    )
    return int(result.scalar() or 0)


async def create_key(
    db: AsyncSession,
    user_id: str,
    org_id: str,
    label: str,
    scopes: List[str],
) -> Tuple["UserApiKey", str]:
    """Generate + insert a new key scoped to `org_id`. `user_id` is recorded as
    the creator (`created_by_user_id`) for audit. Returns (ORM row, plaintext).

    Caller is responsible for the commit so audit + key insertion share a txn.
    Raises ValueError("max_keys_reached") if the org already has MAX active
    keys — the quota is shared across all members of the org.
    """
    from app.models.user_api_keys_models import UserApiKey

    active = await count_active_keys_for_org(db, org_id)
    if active >= MAX_KEYS_PER_ORG:
        raise ValueError("max_keys_reached")

    plaintext, key_prefix, display_prefix = _generate_plaintext()
    key_hash = _hash_key(plaintext)

    row = UserApiKey(
        user_id=user_id,
        org_id=org_id,
        created_by_user_id=user_id,
        label=label[:100],
        scopes=list(scopes),
        key_prefix=key_prefix,
        display_prefix=display_prefix,
        key_hash=key_hash,
        hash_version=1,
        environment="live",
        rate_limit_rpm=DEFAULT_RATE_LIMIT_RPM,
        is_active=True,
    )
    db.add(row)
    await db.flush()  # populate id / server_defaults for audit payload
    return row, plaintext


async def verify_request_key(
    db: AsyncSession,
    authorization_header: str,
    required_scope: str,
    request_ip: Optional[str] = None,
) -> "UserApiKey":
    """Extract Bearer key, verify, enforce scope + rate limit.

    Mutates `last_used_at`, `last_used_ip`, `total_requests` on the ORM row.
    Caller MUST commit to persist the usage update.
    """
    from app.models.user_api_keys_models import UserApiKey

    if not authorization_header.startswith("Bearer "):
        raise UserApiKeyError("no_bearer")

    plaintext = authorization_header[7:].strip()
    if not plaintext.startswith(KEY_PREFIX_RAW) or len(plaintext) < KEY_PREFIX_LEN:
        raise UserApiKeyError("invalid_format")

    key_prefix = plaintext[:KEY_PREFIX_LEN]

    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.key_prefix == key_prefix,
            UserApiKey.is_active.is_(True),
            UserApiKey.revoked_at.is_(None),
        )
    )
    candidates = result.scalars().all()

    matched: Optional[UserApiKey] = None
    for cand in candidates:
        if _verify_key(plaintext, cand.key_hash):
            matched = cand
            break

    if matched is None:
        raise UserApiKeyError("invalid_key")

    if required_scope not in (matched.scopes or []):
        raise UserApiKeyError("scope_insufficient")

    await _enforce_rate_limit(str(matched.id), matched.rate_limit_rpm)

    matched.last_used_at = datetime.now(timezone.utc)
    if request_ip:
        matched.last_used_ip = request_ip[:45]
    matched.total_requests = (matched.total_requests or 0) + 1

    return matched


async def _enforce_rate_limit(key_id: str, rpm: int) -> None:
    """Fixed-window counter: INCR on 1-minute bucket.

    Gracefully degrades if Redis is unavailable (get_redis returns None) —
    rate limiting is defensive UX protection, not a security boundary. The
    hard security boundary is key validity + scope check.
    """
    r = await get_redis()
    if r is None:
        return

    bucket = int(time.time() // 60)
    redis_key = f"{RATE_LIMIT_REDIS_PREFIX}{key_id}:{bucket}"

    try:
        count = await r.incr(redis_key)
        if count == 1:
            await r.expire(redis_key, 90)  # 1min window + 30s grace
        if count > rpm:
            raise UserApiKeyError("rate_limit_exceeded")
    except UserApiKeyError:
        raise
    except Exception as e:
        log.warning("rate-limit Redis op failed for %s: %s", key_id, e)
        return


async def revoke_key(
    db: AsyncSession,
    org_id: str,
    key_id: str,
    reason: str = "user_requested",
) -> "UserApiKey":
    """Soft-revoke. Idempotent: re-revoke returns the already-revoked row.

    Scoped by org — any admin of the owning org can revoke regardless of which
    team member originally created the key.
    """
    from app.models.user_api_keys_models import UserApiKey

    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.id == key_id,
            UserApiKey.org_id == org_id,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise ValueError("not_found")

    if key.revoked_at is not None:
        return key  # idempotent

    now = datetime.now(timezone.utc)
    key.is_active = False
    key.revoked_at = now
    key.revoked_reason = (reason or "")[:200]
    key.updated_at = now
    return key
