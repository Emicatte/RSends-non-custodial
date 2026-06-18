"""SQLAlchemy ORM models for organizations, memberships, org_invites.

Fase 2 core — introduces the Organization concept without migrating any
existing user-scoped table. Prompt 11 will migrate api_keys + wallets to
org-scope. The other user-scoped tables stay user-scoped.

Role set (stored as plain text): "admin" | "operator" | "viewer".
Invite status: "pending" | "accepted" | "declined" | "expired" | "revoked".

Soft-delete on organizations via `deleted_at` — v1 only personal orgs are
non-deletable; non-personal delete UI arrives in a future prompt.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.models.auth_models import _JSONB, _UUID
from app.models.db_models import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(
        _UUID(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False, unique=True, index=True)
    owner_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_personal = Column(Boolean, nullable=False, default=False)
    plan = Column(Text, nullable=False, default="free")

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
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    extra_metadata = Column(_JSONB(), nullable=False, default=dict)


class Membership(Base):
    __tablename__ = "memberships"

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
    org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(Text, nullable=False)
    invited_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    joined_at = Column(
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

    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_memberships_user_org"),
    )


class OrgInvite(Base):
    __tablename__ = "org_invites"

    id = Column(
        _UUID(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(Text, nullable=False, index=True)
    role = Column(Text, nullable=False)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    invited_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(Text, nullable=False, default="pending")

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    declined_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
