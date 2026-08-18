"""SQLAlchemy ORM model for user_wallets.

EVM-only in v1. `address` is lowercased for case-insensitive matching;
`display_address` holds the EIP-55 checksum for UI rendering. Soft-delete
semantics via `unlinked_at` — the uniqueness constraints are partial (active
rows only), so the same address can be relinked after unlink while preserving
audit rows.

The two partial unique indexes live in `__table_args__` below AND in migration
0017. Both are required and they are not redundant: `create_all` (which
migration 0001 runs, and which every test module runs) builds the schema from
this model, while already-migrated databases only ever get DDL from a revision.
They were originally created by migrations 0026/0030, and were silently lost
when the chain was squashed into 0001 — the model had no `__table_args__`, so
`create_all` never reproduced them and no database, production included, has
enforced them since. Anything relying on them (the `IntegrityError` → 409
handlers in `user_wallets_routes.py`, `_promote_primary`'s "index is the
backstop") was quietly inert for that whole period.
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)

from app.models.db_models import Base
from app.models.auth_models import _UUID, _JSONB


class UserWallet(Base):
    __tablename__ = "user_wallets"

    # Recovered verbatim from the deleted migration 0030 (Step 3.4), which
    # re-scoped 0026's user-scoped originals onto the org. BOTH dialect
    # predicates are mandatory: SQLAlchemy silently drops a dialect-mismatched
    # `*_where`, so a `postgresql_where`-only index degrades to a FULL unique
    # index on the SQLite test engine — which would forbid an org from ever
    # holding two wallet rows, i.e. reject legitimate data rather than merely
    # under-enforce. Note the deliberate boolean-literal split (`true` on PG,
    # `1` on SQLite): `is_primary = 1` is a type error on Postgres.
    #
    # Deviation from the recovered definition, deliberate: 0026/0030 also
    # passed `postgresql_nulls_not_distinct=True` on the one-primary index.
    # It is a documented no-op today (org_id and chain_family are both NOT
    # NULL) and it renders DDL that requires PostgreSQL >= 15, so it is
    # omitted rather than pinning a server-version floor for no behavioural
    # gain.
    __table_args__ = (
        # Same (org, chain_family, address) may repeat only across soft-deleted
        # rows — unlink → relink keeps the audit trail. The key is ORG-scoped:
        # the same address in two different orgs is legitimate and relied upon.
        Index(
            "uq_user_wallets_active_org",
            "org_id",
            "chain_family",
            "address",
            unique=True,
            postgresql_where=text("unlinked_at IS NULL"),
            sqlite_where=text("unlinked_at IS NULL"),
        ),
        # At most one ACTIVE primary per (org, chain_family). Partial on
        # is_primary as well, so an org still holds many active wallets.
        Index(
            "uq_user_wallets_one_primary_org",
            "org_id",
            "chain_family",
            unique=True,
            postgresql_where=text("is_primary = true AND unlinked_at IS NULL"),
            sqlite_where=text("is_primary = 1 AND unlinked_at IS NULL"),
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
