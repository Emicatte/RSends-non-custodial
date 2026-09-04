"""SQLAlchemy ORM model for source_wallets — the wallets AutoSplit empties.

Mirrors migration 0024 exactly. The pairing is load-bearing in BOTH directions:
`create_all` builds the schema from this model (migration 0001, and every test
module), while an already-migrated database only ever receives DDL from the
revision. A column or predicate present in one and absent from the other is
invisible until production — that asymmetry is precisely how `user_wallets`
lost both of its unique indexes for months.

What this table deliberately does NOT hold: the split policy itself. Recipients,
bps and minAmount live on chain, where the merchant can rewrite them with their
own key and without touching our API; mirroring them would guarantee drift. The
row carries only the org linkage, the keeper's watch scope, and the pause flag.

Tenancy is `org_id`, never an owner address — a new table has no reason to join
the custodial-era wallet-address tenant key that `payment_intents` and
`merchant_webhooks` are still waiting to be re-keyed off.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
    text,
)

from app.models.auth_models import _UUID
from app.models.db_models import Base


class SourceWallet(Base):
    __tablename__ = "source_wallets"

    __table_args__ = (
        # GLOBAL (cross-org) uniqueness of the ACTIVE registration. Safe only
        # because registration is SIWE-verified: without ownership proof this
        # same index would let anyone squat the address of a wallet that is
        # already visible on chain. Ownership proof and uniqueness scope are a
        # single decision.
        #
        # The partial predicate is what makes disable -> re-register work: a
        # merchant resuming a paused wallet must not collide with their own
        # historical row, and the audit trail must not have to be deleted to
        # let them back in.
        #
        # BOTH dialect predicates are mandatory. SQLAlchemy silently DROPS a
        # dialect-mismatched `*_where`, so a `postgresql_where`-only index
        # degrades to a FULL unique index on the SQLite engine CI runs —
        # rejecting legitimate re-registration rather than merely
        # under-enforcing. No boolean literal appears here, so unlike
        # user_wallets there is no `true`/`1` split to carry.
        Index(
            "uq_source_wallets_active",
            "chain_id",
            "address",
            "token_symbol",
            unique=True,
            postgresql_where=text("disabled_at IS NULL"),
            sqlite_where=text("disabled_at IS NULL"),
        ),
        CheckConstraint(
            "environment IN ('test', 'live')",
            name="ck_source_wallets_environment",
        ),
        # Backstop for the lowercase-at-rest invariant: a writer that forgets
        # to fold the address fails loudly instead of inserting a row the
        # uniqueness index cannot recognise as a duplicate.
        CheckConstraint(
            "address = lower(address)",
            name="ck_source_wallets_address_lower",
        ),
    )

    id = Column(_UUID(), primary_key=True, default=lambda: str(uuid.uuid4()))

    org_id = Column(
        _UUID(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Audit trail: which member registered it. NULL if that account is later
    # deleted — the registration belongs to the org and outlives the person.
    created_by_user_id = Column(
        _UUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # BIGINT, not INTEGER: migration 0020 had to widen two other chain_id
    # columns because a TRON id overflows a Postgres INTEGER and SQLite cannot
    # reproduce the failure. AutoSplit is EVM-only today; the column is wide
    # anyway because a future chain id is what nobody re-checks.
    chain_id = Column(BigInteger, nullable=False)
    # Derived from the chain server-side, never client-supplied.
    environment = Column(Text, nullable=False)

    # Lowercase at rest for matching; checksummed twin for display.
    address = Column(Text, nullable=False)
    display_address = Column(Text, nullable=False)

    # Symbol only — the token ADDRESS is never stored and never accepted from a
    # client; it is resolved through `router_registry.token_for(chain, symbol)`
    # at each use site. One row per (wallet, token), mirroring the contract's
    # own `_policies[merchant][token]` key.
    token_symbol = Column(Text, nullable=False)

    label = Column(Text, nullable=False, server_default="", default="")

    # Soft disable = keeper pause without an on-chain transaction. Re-enable is
    # a fresh row (relink semantics), so every pause stays in the audit trail.
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_reason = Column(Text, nullable=True)

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
