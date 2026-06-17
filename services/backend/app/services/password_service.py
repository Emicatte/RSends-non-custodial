"""Password hashing, verification, and policy validation.

- bcrypt cost 12 (matches user_api_key_service + security/api_keys conventions).
- Policy: min 10 chars, reject common patterns, reject breached passwords
  (HaveIBeenPwned k-anonymity; fail-open on network errors).
"""

from __future__ import annotations

import hashlib
import logging

import bcrypt
import httpx

log = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
MIN_LENGTH = 10
MAX_LENGTH = 256
HIBP_API_BASE = "https://api.pwnedpasswords.com/range"
HIBP_TIMEOUT_SECONDS = 3.0
HIBP_MAX_BREACH_COUNT = 5

WEAK_PATTERNS = {
    "password", "12345678", "qwerty", "letmein",
    "admin", "welcome", "monkey", "abc12345",
}


class PasswordPolicyError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def hash_password(plaintext: str) -> str:
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plaintext.encode("utf-8"), salt).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


async def check_hibp(password: str) -> int:
    """Check HaveIBeenPwned via SHA-1 k-anonymity API. Returns breach count (0 = safe).

    Fail-open on network/timeout errors: returns 0 so connectivity issues
    don't block signups over a best-effort policy check.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        async with httpx.AsyncClient(timeout=HIBP_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                f"{HIBP_API_BASE}/{prefix}",
                headers={"User-Agent": "rsend-backend"},
            )
            if resp.status_code != 200:
                log.warning("hibp_non_200", extra={"status": resp.status_code})
                return 0

            for line in resp.text.splitlines():
                parts = line.split(":")
                if len(parts) == 2 and parts[0].strip() == suffix:
                    try:
                        return int(parts[1].strip())
                    except ValueError:
                        return 0
            return 0
    except Exception as e:
        log.warning("hibp_failed_fail_open", extra={"error": str(e)[:100]})
        return 0


async def validate_policy(password: str) -> None:
    """Raises PasswordPolicyError if the password fails policy."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(
            "password_too_short", f"min {MIN_LENGTH} characters"
        )
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(
            "password_too_long", f"max {MAX_LENGTH} characters"
        )

    lower = password.lower()
    for weak in WEAK_PATTERNS:
        if weak in lower:
            raise PasswordPolicyError(
                "password_too_common", "contains a common weak pattern"
            )

    breach_count = await check_hibp(password)
    if breach_count > HIBP_MAX_BREACH_COUNT:
        raise PasswordPolicyError(
            "password_breached",
            f"this password has appeared in {breach_count} data breaches",
        )
