"""Per-user notification preferences + known-device ledger.

Two tables, both FK'd to users.id ON DELETE CASCADE. Reuses _UUID TypeDecorator
from auth_models for Postgres/SQLite dual-mode support.

NotificationPreference: user_id is the PK (one row per user). Defaults mirror
the migration (email_login_new_device ON, telegram_* reserved for future wiring).

KnownDevice: composite UNIQUE(user_id, fingerprint) so repeat logins from the
same (UA family + IP /24) combo update in place instead of creating duplicates.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    email_login_new_device = Column(Boolean, nullable=False, default=True)
    telegram_tx_confirmed = Column(Boolean, nullable=False, default=True)
    telegram_tx_failed = Column(Boolean, nullable=False, default=True)
    telegram_price_alerts = Column(Boolean, nullable=False, default=False)
    telegram_chat_id = Column(Text, nullable=True)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class KnownDevice(Base):
    __tablename__ = "known_devices"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "fingerprint", name="uq_known_devices_user_fp"
        ),
    )

    id = Column(
        _UUID(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fingerprint = Column(Text, nullable=False)
    user_agent_snippet = Column(Text, nullable=True)
    ip_first_seen = Column(Text, nullable=True)
    ip_last_seen = Column(Text, nullable=True)
    first_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    login_count = Column(Integer, nullable=False, default=1)
