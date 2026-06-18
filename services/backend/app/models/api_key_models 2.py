"""API Key model — stores hashed keys for merchant authentication."""
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, Boolean, DateTime, Integer, SmallInteger, Index
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

    owner_address = Column(String(42), nullable=False, index=True)

    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(32), nullable=False)
    display_prefix = Column(String(32), nullable=True)
    key_hash_v2 = Column(String(128), nullable=True)
    hash_version = Column(SmallInteger, nullable=False, default=1)

    label = Column(String(100), nullable=False, default="Default")

    is_active = Column(Boolean, default=True, nullable=False)

    # Scope — what this key can do
    scope = Column(String(16), nullable=False, default="write")

    # Environment — test or live
    environment = Column(String(8), nullable=False, default="live")

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
    )
