"""User-linked EVM wallets verified via SIWE (EIP-4361).

One table, user-scoped, soft-deletable:
- user_wallets: stores wallets an authenticated user has proven ownership of.
  v1 is EVM-only (chain_family='evm'). Addresses are stored lowercased in
  `address` for case-insensitive matching; `display_address` keeps the EIP-55
  checksum for UI rendering.

Uniqueness is enforced via partial unique indexes (where unlinked_at IS NULL)
so the same address can be relinked after an unlink while the old row is
preserved for audit. A second partial unique guarantees at most one primary
per (user, chain_family) when active.

Dual-mode migration (Postgres in prod, SQLite in tests): mirrors 0023/0024/0025.
SQLite ≥3.8 supports partial indexes via sqlite_where, so both dialects get
the same integrity guarantees.

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()

    op.create_table(
        "user_wallets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()") if is_pg else None,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chain_family", sa.Text(), nullable=False, server_default="evm"),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("display_address", sa.Text(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("verified_chain_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "verified_via",
            sa.Text(),
            nullable=False,
            server_default="siwe",
        ),
        sa.Column("unlinked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlinked_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'"),
        ),
    )

    # Plain index for the common "list my wallets" query path.
    op.create_index(
        "idx_user_wallets_user_id",
        "user_wallets",
        ["user_id"],
    )

    # Partial unique: same (user, chain_family, address) can exist multiple
    # times only if earlier rows were soft-deleted. Keeps audit trail.
    op.create_index(
        "uq_user_wallets_active",
        "user_wallets",
        ["user_id", "chain_family", "address"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
        sqlite_where=sa.text("unlinked_at IS NULL"),
    )

    # Partial unique: at most one active primary per (user, chain_family).
    # postgresql_nulls_not_distinct hardens future schema changes; a no-op
    # today since both indexed columns are NOT NULL, and ignored on PG<15 /
    # SQLite.
    primary_index_kwargs = {
        "unique": True,
        "postgresql_where": sa.text("is_primary = true AND unlinked_at IS NULL"),
        "sqlite_where": sa.text("is_primary = 1 AND unlinked_at IS NULL"),
    }
    try:
        op.create_index(
            "uq_user_wallets_one_primary",
            "user_wallets",
            ["user_id", "chain_family"],
            postgresql_nulls_not_distinct=True,
            **primary_index_kwargs,
        )
    except TypeError:
        # Older SQLAlchemy without postgresql_nulls_not_distinct kwarg.
        op.create_index(
            "uq_user_wallets_one_primary",
            "user_wallets",
            ["user_id", "chain_family"],
            **primary_index_kwargs,
        )

    # Lookup by address (for future tx attribution). Active rows only.
    op.create_index(
        "idx_user_wallets_active_lookup",
        "user_wallets",
        ["address", "chain_family"],
        postgresql_where=sa.text("unlinked_at IS NULL"),
        sqlite_where=sa.text("unlinked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_user_wallets_active_lookup", table_name="user_wallets")
    op.drop_index("uq_user_wallets_one_primary", table_name="user_wallets")
    op.drop_index("uq_user_wallets_active", table_name="user_wallets")
    op.drop_index("idx_user_wallets_user_id", table_name="user_wallets")
    op.drop_table("user_wallets")
