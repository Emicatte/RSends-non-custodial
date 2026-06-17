"""
RSends Backend — Key Management Service.

Signers:
  LocalSigner  — private key from env var (dev/testnet only, warns on mainnet)
  KMSSigner    — AWS KMS via boto3; key never leaves the HSM

Factory:
  get_signer(mode) where mode = SIGNER_MODE env var ("local" | "kms")

All signers implement the AbstractSigner interface.
"""

import abc
import asyncio
import logging
import threading
import time as _time
from collections import defaultdict
from typing import Optional

from eth_account import Account

from app.config import get_settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
#  KMS Rate Limiter (local defence-in-depth, on top of IAM)
# ═══════════════════════════════════════════════════════════════

class KMSRateLimiter:
    """In-process rate limiter for KMS signing — defence-in-depth.

    Complements the IAM-level rate limit.  Thread-safe via a lock
    so concurrent asyncio-to-thread calls don't race.
    """

    def __init__(self, max_per_minute: int = 60, max_per_hour: int = 500):
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self._minute_counts: dict[str, int] = defaultdict(int)
        self._hour_counts: dict[str, int] = defaultdict(int)
        self._last_reset_minute: float = _time.monotonic()
        self._last_reset_hour: float = _time.monotonic()
        self._lock = threading.Lock()

    def check_and_increment(self, operation: str = "sign") -> bool:
        """Return True if the operation is within limits, False to reject."""
        with self._lock:
            now = _time.monotonic()

            if now - self._last_reset_minute > 60:
                self._minute_counts.clear()
                self._last_reset_minute = now
            if now - self._last_reset_hour > 3600:
                self._hour_counts.clear()
                self._last_reset_hour = now

            self._minute_counts[operation] += 1
            self._hour_counts[operation] += 1

            if self._minute_counts[operation] > self.max_per_minute:
                logger.critical(
                    "KMS rate limit EXCEEDED: %d/%d per minute for %s",
                    self._minute_counts[operation], self.max_per_minute, operation,
                )
                return False

            if self._hour_counts[operation] > self.max_per_hour:
                logger.critical(
                    "KMS rate limit EXCEEDED: %d/%d per hour for %s",
                    self._hour_counts[operation], self.max_per_hour, operation,
                )
                return False

            return True


# ═══════════════════════════════════════════════════════════════
#  KMS Audit Logger (append-only DB log)
# ═══════════════════════════════════════════════════════════════

class KMSAuditLogger:
    """Persists every KMS operation to kms_audit_log (non-blocking)."""

    @staticmethod
    async def log_operation(
        key_id: str,
        operation: str,
        *,
        chain_id: Optional[int] = None,
        context: Optional[dict] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Write to Postgres. Failures are logged but never raised."""
        try:
            from app.db.session import async_session
            from app.models.kms_models import KMSAuditLog

            async with async_session() as db:
                entry = KMSAuditLog(
                    key_id=key_id,
                    operation=operation,
                    chain_id=chain_id,
                    context=context,
                    success=success,
                    error=error,
                )
                db.add(entry)
                await db.commit()
        except Exception as exc:
            logger.warning("KMS audit log write failed (non-fatal): %s", exc)


# ═══════════════════════════════════════════════════════════════
#  Key Rotation Manager
# ═══════════════════════════════════════════════════════════════

class KeyRotationManager:
    """Manages KMS key rotation.

    - Active key signs new transactions.
    - Previous keys are retained for verification of old signatures.
    - Rotation period is handled externally (e.g. 90-day cron);
      this class only tracks which keys to use.
    """

    def __init__(
        self,
        active_key_id: str,
        previous_key_ids: Optional[list[str]] = None,
    ):
        self.active_key_id = active_key_id
        self.previous_key_ids = previous_key_ids or []

    @property
    def all_key_ids(self) -> list[str]:
        return [self.active_key_id] + self.previous_key_ids


# ═══════════════════════════════════════════════════════════════
#  Exception
# ═══════════════════════════════════════════════════════════════

class SignerError(Exception):
    """Key management or signing error."""
    pass


# ═══════════════════════════════════════════════════════════════
#  Abstract Interface
# ═══════════════════════════════════════════════════════════════

class AbstractSigner(abc.ABC):
    """Interface for transaction signers.

    Every signer must be able to:
      - sign_transaction(tx_dict) → raw signed TX bytes
      - sign_hash(msg_hash) → (v, r, s) for EIP-712 / arbitrary hash signing
      - get_address() → checksummed Ethereum address
    """

    @abc.abstractmethod
    async def sign_transaction(self, tx_dict: dict) -> bytes:
        """Sign an EVM transaction dictionary.

        Args:
            tx_dict: Fully-populated transaction dict
                     (to, value, gas, nonce, chainId, etc.).

        Returns:
            Raw signed transaction bytes ready for ``eth_sendRawTransaction``.
        """
        ...

    @abc.abstractmethod
    async def sign_hash(self, msg_hash: bytes) -> tuple[int, int, int]:
        """Sign a 32-byte hash (e.g. EIP-712 digest).

        Args:
            msg_hash: 32-byte hash to sign.

        Returns:
            (v, r, s) signature components.
        """
        ...

    @abc.abstractmethod
    async def get_address(self) -> str:
        """Return the signer's Ethereum address (checksummed)."""
        ...


# ═══════════════════════════════════════════════════════════════
#  LocalSigner (env-var private key)
# ═══════════════════════════════════════════════════════════════

class LocalSigner(AbstractSigner):
    """Signs with a local private key loaded from ``SWEEP_PRIVATE_KEY``.

    WARNING:
        Only for development and testnet.
        Emits a loud warning if used on mainnet chain_ids.
    """

    MAINNET_CHAIN_IDS = frozenset({1, 8453, 42161, 137, 10, 56})

    def __init__(self, private_key: Optional[str] = None):
        settings = get_settings()
        self._key = private_key or settings.sweep_private_key
        if not self._key:
            raise SignerError(
                "No private key configured (set SWEEP_PRIVATE_KEY env var)"
            )

        self._account = Account.from_key(self._key)
        logger.info("LocalSigner initialised: %s", self._account.address)

    async def sign_transaction(self, tx_dict: dict) -> bytes:
        """Sign via local private key.

        Logs a WARNING when signing for mainnet chain_ids.
        """
        chain_id = tx_dict.get("chainId", 0)
        if chain_id in self.MAINNET_CHAIN_IDS:
            logger.warning(
                "LocalSigner used on MAINNET chain %d — use KMS in production!",
                chain_id,
            )

        signed = self._account.sign_transaction(tx_dict)
        return signed.raw_transaction

    async def sign_hash(self, msg_hash: bytes) -> tuple[int, int, int]:
        """Sign a 32-byte hash via local key (e.g. EIP-712)."""
        from eth_account.messages import encode_defunct, _hash_eip191_message

        signed = self._account.unsafe_sign_hash(msg_hash)
        return signed.v, signed.r, signed.s

    async def get_address(self) -> str:
        return self._account.address


# ═══════════════════════════════════════════════════════════════
#  KMSSigner (AWS KMS — HSM-backed)
# ═══════════════════════════════════════════════════════════════

class KMSSigner(AbstractSigner):
    """Signs via AWS KMS — the private key never leaves the HSM.

    Requirements:
      - ``boto3`` installed
      - KMS key with ``ECC_SECG_P256K1`` key spec
      - IAM permissions: ``kms:Sign``, ``kms:GetPublicKey``

    Features:
      - Address derived from KMS public key, cached after first call
      - Retry with exponential backoff (max 3 attempts)
      - EIP-2 low-s normalisation
    """

    MAX_RETRIES = 3
    BASE_DELAY = 0.5  # seconds

    def __init__(
        self,
        key_id: Optional[str] = None,
        region: Optional[str] = None,
        previous_key_ids: Optional[list[str]] = None,
        rate_limit_per_minute: int = 60,
        rate_limit_per_hour: int = 500,
    ):
        settings = get_settings()
        self._key_id = key_id or settings.kms_key_id
        self._region = region or settings.aws_region

        if not self._key_id:
            raise SignerError("No KMS key ID configured (set KMS_KEY_ID env var)")

        try:
            import boto3
        except ImportError:
            raise SignerError("boto3 is required for KMS signer: pip install boto3")

        self._kms = boto3.client("kms", region_name=self._region)
        self._cached_address: Optional[str] = None

        # ── Hardening: rate limiter, audit, rotation ──────
        self._rate_limiter = KMSRateLimiter(
            max_per_minute=rate_limit_per_minute,
            max_per_hour=rate_limit_per_hour,
        )
        self._audit = KMSAuditLogger()
        self._rotation = KeyRotationManager(
            active_key_id=self._key_id,
            previous_key_ids=previous_key_ids or [],
        )

        logger.info(
            "KMSSigner initialised: key=%s region=%s previous_keys=%d",
            self._key_id,
            self._region,
            len(self._rotation.previous_key_ids),
        )

    # ── Address derivation ────────────────────────────────

    async def get_address(self) -> str:
        """Derive Ethereum address from KMS public key (cached)."""
        if self._cached_address:
            return self._cached_address

        address = await asyncio.to_thread(self._derive_address)
        self._cached_address = address
        return address

    def _derive_address(self) -> str:
        """Synchronous address derivation from KMS."""
        from eth_keys import keys as eth_keys
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_der_public_key,
        )

        response = self._kms.get_public_key(KeyId=self._key_id)
        pub_key_der = response["PublicKey"]

        # Parse DER → uncompressed point (04 || x || y)
        pub_key = load_der_public_key(pub_key_der)
        raw_bytes = pub_key.public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )

        # eth_keys expects 64 bytes (x || y) without the 0x04 prefix
        pub = eth_keys.PublicKey(raw_bytes[1:])
        address = pub.to_checksum_address()

        logger.info("KMS address derived: %s", address)
        return address

    # ── Hash signing (EIP-712 etc.) ─────────────────────────

    async def sign_hash(self, msg_hash: bytes) -> tuple[int, int, int]:
        """Sign a 32-byte hash via KMS.

        Rate-limited and audit-logged. Returns (v, r, s) with v = 27|28.
        """
        if not self._rate_limiter.check_and_increment("sign_hash"):
            await self._audit.log_operation(
                self._key_id, "sign_hash",
                success=False, error="rate_limit_exceeded",
            )
            raise SignerError("KMS signing rate limit exceeded")

        try:
            r, s = await asyncio.to_thread(self._kms_sign_hash, msg_hash)
            v_raw = await asyncio.to_thread(self._recover_v, msg_hash, r, s)
            # Fire-and-forget audit
            asyncio.create_task(self._audit.log_operation(
                self._key_id, "sign_hash", success=True,
            ))
            return v_raw + 27, r, s
        except Exception as exc:
            asyncio.create_task(self._audit.log_operation(
                self._key_id, "sign_hash",
                success=False, error=str(exc)[:500],
            ))
            raise

    # ── Transaction signing ───────────────────────────────

    async def sign_transaction(self, tx_dict: dict) -> bytes:
        """Sign a transaction via KMS.

        Rate-limited and audit-logged.
        Supports legacy (type 0) and EIP-1559 (type 2) transactions.
        """
        if not self._rate_limiter.check_and_increment("sign_tx"):
            await self._audit.log_operation(
                self._key_id, "sign_tx",
                chain_id=tx_dict.get("chainId"),
                success=False, error="rate_limit_exceeded",
            )
            raise SignerError("KMS signing rate limit exceeded")

        chain_id = tx_dict.get("chainId")
        tx_context = {
            "to": tx_dict.get("to", "")[:42],
            "chain_id": chain_id,
        }

        try:
            result = await asyncio.to_thread(self._sign_sync, tx_dict)
            asyncio.create_task(self._audit.log_operation(
                self._key_id, "sign_tx",
                chain_id=chain_id, context=tx_context, success=True,
            ))
            return result
        except Exception as exc:
            asyncio.create_task(self._audit.log_operation(
                self._key_id, "sign_tx",
                chain_id=chain_id, context=tx_context,
                success=False, error=str(exc)[:500],
            ))
            raise

    def _sign_sync(self, tx_dict: dict) -> bytes:
        """Synchronous signing pipeline."""
        from eth_account._utils.legacy_transactions import (
            serializable_unsigned_transaction_from_dict,
            encode_transaction,
        )

        # Prepare unsigned transaction and compute hash
        unsigned = serializable_unsigned_transaction_from_dict(tx_dict)
        msg_hash = unsigned.hash()

        # Sign hash via KMS
        r, s = self._kms_sign_hash(bytes(msg_hash))

        # Determine recovery parameter v
        v_raw = self._recover_v(bytes(msg_hash), r, s)

        # EIP-155 v encoding
        chain_id = tx_dict.get("chainId")
        if chain_id:
            v = v_raw + 35 + chain_id * 2
        else:
            v = v_raw + 27

        return encode_transaction(unsigned, vrs=(v, r, s))

    def _kms_sign_hash(self, msg_hash: bytes) -> tuple[int, int]:
        """Sign a 32-byte hash via KMS with retry + backoff.

        Returns:
            (r, s) integers with EIP-2 low-s normalisation.
        """
        from cryptography.hazmat.primitives.asymmetric.utils import (
            decode_dss_signature,
        )

        der_signature: Optional[bytes] = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._kms.sign(
                    KeyId=self._key_id,
                    Message=msg_hash,
                    MessageType="DIGEST",
                    SigningAlgorithm="ECDSA_SHA_256",
                )
                der_signature = response["Signature"]
                break
            except Exception as exc:
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "KMS sign attempt %d failed: %s — retrying in %.1fs",
                        attempt + 1,
                        exc,
                        delay,
                    )
                    _time.sleep(delay)
                else:
                    raise SignerError(
                        f"KMS signing failed after {self.MAX_RETRIES} attempts: {exc}"
                    )

        r, s = decode_dss_signature(der_signature)

        # EIP-2: ensure s is in lower half of curve order
        SECP256K1_ORDER = (
            0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        )
        if s > SECP256K1_ORDER // 2:
            s = SECP256K1_ORDER - s

        return r, s

    def _recover_v(self, msg_hash: bytes, r: int, s: int) -> int:
        """Determine recovery parameter v by trial (0 or 1)."""
        from eth_keys.datatypes import Signature

        address = self._cached_address or self._derive_address()

        for v_candidate in (0, 1):
            try:
                sig = Signature(vrs=(v_candidate, r, s))
                recovered = sig.recover_public_key_from_msg_hash(msg_hash)
                if recovered.to_checksum_address().lower() == address.lower():
                    return v_candidate
            except Exception:
                continue

        raise SignerError("Failed to determine recovery parameter v")

    # ── Key rotation: verify with active + previous keys ──────

    async def verify_with_rotation(
        self, msg_hash: bytes, signature_der: bytes,
    ) -> bool:
        """Verify a signature against the active key and all previous keys.

        Useful after key rotation to validate old signatures.
        """
        for key_id in self._rotation.all_key_ids:
            try:
                response = await asyncio.to_thread(
                    self._kms.verify,
                    KeyId=key_id,
                    Message=msg_hash,
                    Signature=signature_der,
                    SigningAlgorithm="ECDSA_SHA_256",
                    MessageType="DIGEST",
                )
                if response.get("SignatureValid"):
                    asyncio.create_task(self._audit.log_operation(
                        key_id, "verify", success=True,
                    ))
                    return True
            except Exception:
                continue

        asyncio.create_task(self._audit.log_operation(
            self._key_id, "verify",
            success=False, error="no_matching_key",
        ))
        return False

    # ── Health check ──────────────────────────────────────────

    async def health_check(self) -> dict:
        """Check that the KMS key is usable. Returns component status dict."""
        try:
            response = await asyncio.to_thread(
                self._kms.describe_key, KeyId=self._key_id,
            )
            meta = response.get("KeyMetadata", {})
            enabled = meta.get("Enabled", False)
            state = meta.get("KeyState", "Unknown")
            return {
                "status": "healthy" if enabled else "unhealthy",
                "key_id": self._key_id,
                "key_state": state,
                "enabled": enabled,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "key_id": self._key_id,
                "error": str(exc)[:200],
            }


# ═══════════════════════════════════════════════════════════════
#  VaultSigner (HashiCorp Vault — self-hosted HSM alternative)
# ═══════════════════════════════════════════════════════════════

class VaultSigner(AbstractSigner):
    """Signs via HashiCorp Vault Transit secrets engine.

    Requirements:
      - ``hvac`` installed (``pip install hvac``)
      - Vault Transit engine mounted at ``transit/``
      - Key type: ``ecdsa-p256`` (secp256k1 not natively supported;
        use the Vault plugin or store the key in Vault KV and sign locally)

    Environment:
      - ``VAULT_ADDR``: Vault server URL
      - ``VAULT_TOKEN``: authentication token
      - ``VAULT_KEY_NAME``: transit key name (default: ``rsend-signer``)

    Status: STUB — raises NotImplementedError. Implement when Vault
    is deployed. The interface is ready for drop-in replacement.
    """

    def __init__(self):
        import os

        self._addr = os.getenv("VAULT_ADDR", "")
        self._token = os.getenv("VAULT_TOKEN", "")
        self._key_name = os.getenv("VAULT_KEY_NAME", "rsend-signer")

        if not self._addr or not self._token:
            raise SignerError(
                "VAULT_ADDR and VAULT_TOKEN must be set for Vault signer"
            )

        logger.info("VaultSigner initialised: addr=%s key=%s", self._addr, self._key_name)

    async def sign_transaction(self, tx_dict: dict) -> bytes:
        raise NotImplementedError(
            "VaultSigner.sign_transaction() not yet implemented — "
            "see key_manager.py for integration guide"
        )

    async def sign_hash(self, msg_hash: bytes) -> tuple[int, int, int]:
        raise NotImplementedError(
            "VaultSigner.sign_hash() not yet implemented"
        )

    async def get_address(self) -> str:
        raise NotImplementedError(
            "VaultSigner.get_address() not yet implemented"
        )


# ═══════════════════════════════════════════════════════════════
#  Factory
# ═══════════════════════════════════════════════════════════════

_signer: Optional[AbstractSigner] = None


def get_signer(mode: Optional[str] = None) -> AbstractSigner:
    """Get or create the configured signer (singleton).

    Args:
        mode: ``"local"``, ``"kms"``, or ``"vault"``.
              Defaults to ``SIGNER_MODE`` env var.

    Returns:
        An ``AbstractSigner`` instance.
    """
    global _signer

    if _signer is not None:
        return _signer

    settings = get_settings()
    mode = mode or settings.signer_mode

    if mode == "kms":
        _signer = KMSSigner()
    elif mode == "vault":
        _signer = VaultSigner()
    else:
        _signer = LocalSigner()

    logger.info("Signer backend: %s (%s)", mode, type(_signer).__name__)
    return _signer


# ═══════════════════════════════════════════════════════════════
#  Oracle signer factory (M1) — dedicated, separate from the sweep signer
# ═══════════════════════════════════════════════════════════════

_oracle_signers: Optional[list[AbstractSigner]] = None


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def get_oracle_signers() -> list[AbstractSigner]:
    """Get or create the ORACLE signer SET (singleton).

    Returns one signer for a single-signer oracle (V4), or N for an M-of-N
    multisig (V5/V6 threshold). Reads the comma-separated multi-key vars,
    falling back to the single-key vars when unset. Signs EIP-712 oracle
    approvals with the oracle key(s) — NEVER the sweep hot wallet.

    In prod set ``ORACLE_SIGNER_MODE=kms`` so keys stay in the HSM and never
    enter the web tier (M1).
    """
    global _oracle_signers

    if _oracle_signers is not None:
        return _oracle_signers

    settings = get_settings()
    mode = (settings.oracle_signer_mode or "local").lower()

    if mode == "kms":
        ids = _split_csv(settings.oracle_kms_key_ids) or _split_csv(settings.oracle_kms_key_id)
        if not ids:
            raise SignerError("oracle_signer_mode=kms requires ORACLE_KMS_KEY_ID(S)")
        signers: list[AbstractSigner] = [KMSSigner(key_id=kid) for kid in ids]
    else:
        keys = _split_csv(settings.oracle_signer_private_keys) or _split_csv(
            settings.oracle_signer_private_key
        )
        if not keys:
            raise SignerError("oracle_signer_mode=local requires ORACLE_SIGNER_PRIVATE_KEY(S)")
        signers = [LocalSigner(private_key=pk) for pk in keys]

    _oracle_signers = signers
    logger.info("Oracle signer set: %s × %d", mode, len(signers))
    return _oracle_signers


def get_oracle_signer() -> AbstractSigner:
    """The primary oracle signer (first of the set) — single-signer V4 path."""
    return get_oracle_signers()[0]
