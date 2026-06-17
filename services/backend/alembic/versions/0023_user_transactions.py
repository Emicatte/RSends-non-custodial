"""Create user_transactions table for persistent RSends-submitted tx history.

Additive — one new table, FK to users.id ON DELETE CASCADE. Idempotent inserts
via composite UNIQUE(user_id, chain_id, tx_hash) to tolerate concurrent emits
and client-side merge replays.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()") if _is_postgres() else None,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Chain & identity
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("wallet_address", sa.Text(), nullable=False),
        # Classification
        sa.Column("tx_type", sa.Text(), nullable=False),
        sa.Column(
            "tx_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "direction",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'out'"),
        ),
        # Amount / token
        sa.Column("token_symbol", sa.Text(), nullable=True),
        sa.Column("token_address", sa.Text(), nullable=True),
        sa.Column("amount_raw", sa.Text(), nullable=True),
        sa.Column("amount_decimal", sa.Numeric(38, 18), nullable=True),
        sa.Column("counterparty_address", sa.Text(), nullable=True),
        # Metadata & gas
        sa.Column(
            "extra_metadata",
            postgresql.JSONB() if _is_postgres() else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'"),
        ),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("gas_price_gwei", sa.Numeric(38, 9), nullable=True),
        sa.Column("block_number", sa.BigInteger(), nullable=True),
        # Timestamps
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "chain_id", "tx_hash", name="uq_user_tx_hash"
        ),
    )
    op.create_index(
        "idx_user_tx_user_id", "user_transactions", ["user_id"]
    )
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_user_tx_user_submitted "
            "ON user_transactions(user_id, submitted_at DESC)"
        )
        op.execute(
            "CREATE INDEX idx_user_tx_status "
            "ON user_transactions(user_id, tx_status) "
            "WHERE tx_status IN ('pending','confirming')"
        )
    else:
        op.create_index(
            "idx_user_tx_user_submitted",
            "user_transactions",
            ["user_id", "submitted_at"],
        )
        op.create_index(
            "idx_user_tx_status",
            "user_transactions",
            ["user_id", "tx_status"],
        )
    op.create_index(
        "idx_user_tx_chain",
        "user_transactions",
        ["user_id", "chain_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_tx_chain", table_name="user_transactions")
    op.drop_index("idx_user_tx_status", table_name="user_transactions")
    op.drop_index("idx_user_tx_user_submitted", table_name="user_transactions")
    op.drop_index("idx_user_tx_user_id", table_name="user_transactions")
    op.drop_table("user_transactions")
