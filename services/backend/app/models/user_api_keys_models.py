"""SQLAlchemy ORM model for user_api_keys.

User-scoped programmatic access keys. Completely separate namespace from the
merchant `api_keys` table. Soft-delete via `is_active=False` + `revoked_at`
so audit history stays intact; `uq_user_api_keys_hash` is global across rows
including revoked ones.

`org_id` is nullable v1 — Prompt 11 will populate it when Organizations
(Prompt 10) land, without requiring a table rewrite.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)

from app.models.auth_models import _JSONB, _UUID
from app.models.db_models import Base


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

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
    # Prompt 11: org-scoped. Every row belongs to exactly one org; rows
    # CASCADE-delete when the org is deleted.
    org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Audit trail: which user (a member of `org_id`) created the key. Goes to
    # NULL if that user's account is later deleted — the key remains, owned
    # by the org.
    created_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    label = Column(Text, nullable=False, default="")

    # Key material
    key_prefix = Column(String(32), nullable=False, index=True)
    display_prefix = Column(String(48), nullable=False)
    key_hash = Column(String(128), nullable=False, unique=True)
    hash_version = Column(SmallInteger, nullable=False, default=1)

    environment = Column(String(8), nullable=False, default="live")

    scopes = Column(_JSONB(), nullable=False, default=list)

    rate_limit_rpm = Column(Integer, nullable=False, default=60)

    is_active = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    last_used_at = Column(DateTime(timezone=True), nullable=True)
    last_used_ip = Column(String(45), nullable=True)
    total_requests = Column(Integer, nullable=False, default=0)

    extra_metadata = Column(_JSONB(), nullable=False, default=dict)
