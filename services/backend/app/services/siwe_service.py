"""SIWE (EIP-4361) challenge/verify for EVM wallets.

Security properties enforced:
- Nonce is 16-byte random, stored in Redis with a 5-minute TTL (SETEX),
  key scoped to (user_id, nonce). Payload includes the full canonical
  SIWE message plus the claimed address and chain_id.
- Replay protection: nonce is single-use. verify_challenge() always calls
  DELETE before any signature work, regardless of outcome.
- Server-authoritative message: the message hashed for recovery is the
  one the server built and stored, not a client-submitted copy — prevents
  any tampering with domain/statement/URI/issued_at.
- Domain binding: 'domain' field is derived from settings.frontend_url.
- Chain ID allow-list mirrors the frontend EVM_CHAIN_IDS config exactly.
- Signature: verified via eth_account.Account.recover_message against
  encode_defunct(text=stored_message). Address compared case-insensitive.

Out of scope (v1):
- EIP-1271 smart-contract wallet signatures (Safe, Argent)
- Solana/Tron (separate service files)
"""

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import is_address, to_checksum_address

from app.config import get_settings
from app.services.cache_service import get_redis

log = logging.getLogger(__name__)


# Align with frontend EVM_CHAIN_IDS at app/providers.tsx:33
# (10 mainnets + Base Sepolia for dev).
SUPPORTED_EVM_CHAIN_IDS = frozenset(
    {
        1,       # Ethereum
        10,      # Optimism
        56,      # BNB Chain
        137,     # Polygon
        324,     # zkSync Era
        8453,    # Base
        42161,   # Arbitrum One
        42220,   # Celo
        43114,   # Avalanche C-Chain
        81457,   # Blast
        84532,   # Base Sepolia
    }
)

NONCE_TTL_SECONDS = 300  # 5 minutes
NONCE_REDIS_PREFIX = "wallet_nonce:"
# Prompt 11: the cap is per-ORG, not per-user. Back-compat alias retained so
# older imports keep working during the transition.
MAX_WALLETS_PER_ORG = 10
MAX_WALLETS_PER_USER = MAX_WALLETS_PER_ORG  # deprecated alias
SIWE_STATEMENT = "Link this wallet to your RSends account."


class SIWEError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class SIWEUnavailable(Exception):
    """Raised when Redis is down — caller should return 503."""


def _domain_from_settings() -> str:
    parsed = urlparse(get_settings().frontend_url)
    return parsed.netloc or "localhost"


def _uri_from_settings() -> str:
    base = get_settings().frontend_url.rstrip("/")
    return f"{base}/settings/wallets"


def _iso_z(dt: datetime) -> str:
    """UTC ISO-8601 with trailing 'Z', no microseconds (EIP-4361 style)."""
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_siwe_message(
    *,
    domain: str,
    address: str,
    statement: str,
    uri: str,
    chain_id: int,
    nonce: str,
    issued_at: datetime,
    expiration_time: datetime,
) -> str:
    """Compose an EIP-4361 message. See https://eips.ethereum.org/EIPS/eip-4361"""
    return (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n\n"
        f"{statement}\n\n"
        f"URI: {uri}\n"
        f"Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {_iso_z(issued_at)}\n"
        f"Expiration Time: {_iso_z(expiration_time)}"
    )


def _nonce_key(user_id: str, nonce: str) -> str:
    return f"{NONCE_REDIS_PREFIX}{user_id}:{nonce}"


async def create_challenge(
    user_id: str,
    address: str,
    chain_id: int,
) -> Tuple[str, str, datetime]:
    """Build an EIP-4361 challenge and stash the canonical message in Redis.

    Returns (siwe_message, nonce, expires_at).
    """
    if chain_id not in SUPPORTED_EVM_CHAIN_IDS:
        raise SIWEError("chain_not_supported", f"chain_id {chain_id}")
    if not is_address(address):
        raise SIWEError("invalid_address")

    r = await get_redis()
    if r is None:
        raise SIWEUnavailable()

    address_cs = to_checksum_address(address)
    nonce = secrets.token_hex(16)
    issued_at = datetime.now(timezone.utc)
    expiration_time = issued_at + timedelta(seconds=NONCE_TTL_SECONDS)

    message = _build_siwe_message(
        domain=_domain_from_settings(),
        address=address_cs,
        statement=SIWE_STATEMENT,
        uri=_uri_from_settings(),
        chain_id=chain_id,
        nonce=nonce,
        issued_at=issued_at,
        expiration_time=expiration_time,
    )

    payload = json.dumps(
        {
            "message": message,
            "address": address.lower(),
            "chain_id": chain_id,
        }
    )
    await r.setex(_nonce_key(user_id, nonce), NONCE_TTL_SECONDS, payload)

    log.info(
        "siwe_challenge_created user=%s addr=%s chain=%d nonce=%s",
        user_id[:8],
        address.lower()[:10] + "...",
        chain_id,
        nonce[:8] + "...",
    )
    return message, nonce, expiration_time


async def verify_challenge(
    user_id: str,
    nonce: str,
    address: str,
    chain_id: int,
    signature: str,
) -> str:
    """Verify SIWE signature against the server-stored message.

    Consumes the nonce (single-use) BEFORE any crypto work. Raises SIWEError
    on any mismatch; returns the verified canonical message on success so
    the caller can log an audit hash.
    """
    if not is_address(address):
        raise SIWEError("invalid_address")
    if chain_id not in SUPPORTED_EVM_CHAIN_IDS:
        raise SIWEError("chain_not_supported")

    r = await get_redis()
    if r is None:
        raise SIWEUnavailable()

    key = _nonce_key(user_id, nonce)
    stored_raw = await r.get(key)
    # Single-use: always delete, regardless of success below.
    try:
        await r.delete(key)
    except Exception:
        log.exception("siwe_nonce_delete_failed")

    if not stored_raw:
        raise SIWEError("nonce_expired_or_used")

    if isinstance(stored_raw, bytes):
        stored_raw = stored_raw.decode("utf-8")

    try:
        stored = json.loads(stored_raw)
    except Exception:
        raise SIWEError("nonce_context_mismatch", "unparseable payload")

    if stored.get("address") != address.lower():
        raise SIWEError("nonce_context_mismatch", "address")
    if int(stored.get("chain_id", -1)) != chain_id:
        raise SIWEError("nonce_context_mismatch", "chain_id")

    stored_message = stored.get("message")
    if not isinstance(stored_message, str) or not stored_message:
        raise SIWEError("nonce_context_mismatch", "message")

    try:
        encoded = encode_defunct(text=stored_message)
        recovered = Account.recover_message(encoded, signature=signature)
    except Exception as e:
        raise SIWEError("signature_malformed", str(e)[:100])

    if recovered.lower() != address.lower():
        raise SIWEError("signature_mismatch")

    log.info(
        "siwe_verified user=%s addr=%s chain=%d",
        user_id[:8],
        address.lower()[:10] + "...",
        chain_id,
    )
    return stored_message
