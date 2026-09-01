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

    # Org-level settlement address: the wallet where the org receives on-chain
    # payments, shared across team members. NULL until an admin sets it in
    # Settings (never auto-derived). Stored lowercase. Migration 0008.
    # EVM ONLY — it is validated as ^0x[a-fA-F0-9]{40}$ and lowercased, and it
    # remains the PRIMARY payout address.
    settlement_wallet = Column(Text, nullable=True)

    # TRON payout address (migration 0022). A SEPARATE column, not a second use
    # of the one above: base58check excludes `0 O I l`, so the lowercasing that
    # normalises an EVM address can turn a TRON one into a string that is not
    # base58 at all and whose checksum no longer verifies. Two columns, two
    # validators, no branching on a guess about which chain a value belongs to.
    # NULL = this org has not set a TRON payout address. Split payments are
    # unaffected and stay EVM-only: splits execute through the immutable fee
    # router, and a watch-only chain has no router to carry legs.
    settlement_wallet_tron = Column(Text, nullable=True)

    # Staged onboarding (migration 0009). Two INDEPENDENT status fields:
    # onboarding_status: 'created' -> 'email_verified' -> 'company_submitted'.
    #   Forward-only (onboarding_service.advance_onboarding_status);
    #   'company_submitted' = full testnet access. Default is the earliest
    #   state (fail-closed); org_service sets the real initial state per the
    #   owner's email verification.
    # activation_status: 'not_started' | 'kyb_pending' | 'active' | 'rejected'.
    #   Slot for the future external business-verification provider and admin
    #   tooling; nothing transitions it in-app today. The chain-access guard
    #   (app/services/chain_access.py) requires 'active' for mainnet chains.
    onboarding_status = Column(Text, nullable=False, default="created")
    activation_status = Column(Text, nullable=False, default="not_started")

    # Manual merchant approval (migration 0010). Independent of the two fields
    # above: 'pending_approval' -> 'approved' | 'declined', decided only by an
    # operator via the admin approval surface (X-Admin-Token routes). Fail
    # closed: anything other than 'approved' denies operational access
    # (require_org_approved / the merchant API-key gate). Python-side default
    # ONLY — no server_default, to keep create_all parity with a migrated DB
    # (env.py compares server defaults); org_service always sets it explicitly.
    approval_status = Column(Text, nullable=False, default="pending_approval")
    approval_requested_at = Column(DateTime(timezone=True), nullable=True)
    approval_decided_at = Column(DateTime(timezone=True), nullable=True)
    approval_decided_by = Column(Text, nullable=True)
    decline_reason = Column(Text, nullable=True)

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
