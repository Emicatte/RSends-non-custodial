"""SQLAlchemy ORM model for user_wallets.

EVM-only in v1. `address` is lowercased for case-insensitive matching;
`display_address` holds the EIP-55 checksum for UI rendering. Soft-delete
semantics via `unlinked_at` — uniqueness constraints in the migration are
partial (active rows only), so the same address can be relinked after
unlink while preserving audit rows.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID, _JSONB


class UserWallet(Base):
    __tablename__ = "user_wallets"

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
    # Audit trail: which user (a member of `org_id`) linked the wallet. Goes
    # to NULL if that user's account is later deleted — the wallet remains,
    # owned by the org.
    created_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    chain_family = Column(Text, nullable=False, default="evm")
    address = Column(Text, nullable=False)
    display_address = Column(Text, nullable=False)
    chain_id = Column(Integer, nullable=True)
    verified_chain_id = Column(Integer, nullable=False)

    label = Column(Text, nullable=False, default="")
    is_primary = Column(Boolean, nullable=False, default=False)

    verified_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    verified_via = Column(Text, nullable=False, default="siwe")

    unlinked_at = Column(DateTime(timezone=True), nullable=True)
    unlinked_reason = Column(Text, nullable=True)

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
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    extra_metadata = Column(_JSONB(), nullable=False, default=dict)
