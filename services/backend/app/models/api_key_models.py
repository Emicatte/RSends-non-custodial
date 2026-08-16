"""API Key model — stores hashed keys for merchant authentication."""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import validates

from app.models.db_models import Base


class KeyScope(str, enum.Enum):
    read = "read"
    write = "write"
    admin = "admin"


class KeyEnvironment(str, enum.Enum):
    test = "test"
    live = "live"


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Vestigial for key tenancy since migration 0014 (org_id is the tenant
    # key), but still authoritative for the request identity: verify_api_key
    # derives client_id (= merchant_id stamped on intents/webhooks) from it.
    # Dropping it belongs to the full merchant_id re-key pass.
    owner_address = Column(String(42), nullable=False, index=True)

    # The key's owning organization — the tenant key for the api_keys surface
    # (mint/list/revoke/cap/recipient-gate). Added nullable in 0011 for
    # session mints; backfilled + NOT NULL in 0014, and the wallet-signed
    # generate route now stamps it fail-closed, so no NULL-org key can exist.
    org_id = Column(String(36), nullable=False, index=True)

    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(32), nullable=False)
    display_prefix = Column(String(32), nullable=True)
    key_hash_v2 = Column(String(128), nullable=True)
    hash_version = Column(SmallInteger, nullable=False, default=1)

    label = Column(String(100), nullable=False, default="Default")

    is_active = Column(Boolean, default=True, nullable=False)

    # Scope — what this key can do
    scope = Column(String(16), nullable=False, default="write")

    # Environment — test or live. The insert default is the POWERLESS one: a row
    # created without an explicit environment must not be able to move real
    # money. This is deliberately the mirror image of the READ-side fallbacks
    # (api_keys._api_key_to_dict, merchant_routes._get_environment), which
    # resolve a missing value to "live" so an unstamped key meets the STRICT
    # gate. Two different questions; do not "align" them.
    environment = Column(String(8), nullable=False, default="test")

    # Per-key rate limit (requests per minute)
    rate_limit_rpm = Column(Integer, nullable=False, default=100)

    # Usage tracking
    total_requests = Column(Integer, nullable=False, default=0)
    total_intents_created = Column(Integer, nullable=False, default=0)
    total_volume_usd = Column(String(32), nullable=True, default="0")

    # Monthly limits (0 = unlimited)
    monthly_intent_limit = Column(Integer, nullable=False, default=0)
    monthly_volume_limit_usd = Column(String(32), nullable=True, default="0")

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_api_keys_owner_active", "owner_address", "is_active"),
        Index("ix_api_keys_env", "environment"),
        CheckConstraint(
            "environment IN ('test', 'live')", name="ck_api_keys_environment"
        ),
    )

    @validates("environment")
    def _validate_environment(self, _key, value):
        """Bind KeyEnvironment to the column it was written for.

        The enum was declared and referenced nowhere, so the column was a plain
        String(8) that would accept any short string — including one that
        contradicts the key's own prefix. Migration 0016 adds the matching CHECK
        at the database level; this catches it at the ORM boundary with a usable
        error instead of an IntegrityError at flush time.
        """
        if value is None:
            return value
        try:
            return KeyEnvironment(value).value
        except ValueError:
            raise ValueError(
                f"environment must be one of "
                f"{sorted(e.value for e in KeyEnvironment)}, got {value!r}"
            ) from None
