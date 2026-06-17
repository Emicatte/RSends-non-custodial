"""Add daily_snapshots table and hmac_signature column to audit_log.

Additive migration — no existing tables are modified destructively.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── daily_snapshots table ──────────────────────────────────
    op.create_table(
        "daily_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("treasury_address", sa.String(42), nullable=False),
        sa.Column("on_chain_balance", sa.Numeric(28, 18), nullable=False),
        sa.Column("ledger_balance", sa.Numeric(28, 18), nullable=False),
        sa.Column("diff", sa.Numeric(28, 18), nullable=False),
        sa.Column("diff_pct", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok','mismatch','critical')",
            name="ck_snapshot_status",
        ),
    )
    op.create_index(
        "ix_daily_snapshot_date_chain",
        "daily_snapshots",
        ["date", "chain_id"],
        unique=True,
    )

    # ── hmac_signature on audit_log ────────────────────────────
    op.add_column(
        "audit_log",
        sa.Column("hmac_signature", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "hmac_signature")
    op.drop_index("ix_daily_snapshot_date_chain", table_name="daily_snapshots")
    op.drop_table("daily_snapshots")
