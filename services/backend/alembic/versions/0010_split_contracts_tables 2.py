"""Multi-wallet split system — create split_contracts, split_recipients, split_executions.

Additive migration: crea le 3 tabelle del nuovo sistema split N-wallet.
NON tocca forwarding_rules (split 2-way legacy resta invariato).

Percentuali in basis points (interi): 10000 = 100.00%.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── split_contracts ─────────────────────────────────────────
    op.create_table(
        "split_contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("contract_ref", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("master_wallet", sa.String(length=42), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default="8453"),
        sa.Column("chain_family", sa.String(length=10), nullable=True, server_default="evm"),
        sa.Column("allowed_tokens", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("is_locked", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("rsend_fee_bps", sa.Integer(), nullable=True, server_default="50"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_id", "version", name="uq_client_version"),
        sa.CheckConstraint("rsend_fee_bps >= 0", name="ck_split_contract_fee_nonneg"),
        sa.CheckConstraint("rsend_fee_bps <= 10000", name="ck_split_contract_fee_max"),
    )
    op.create_index(
        "ix_split_contracts_client_id",
        "split_contracts",
        ["client_id"],
    )
    op.create_index(
        "ix_split_contract_client_active",
        "split_contracts",
        ["client_id", "is_active"],
    )

    # ── split_recipients ────────────────────────────────────────
    op.create_table(
        "split_recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("wallet_address", sa.String(length=42), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=True, server_default="recipient"),
        sa.Column("share_bps", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["split_contracts.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("share_bps > 0", name="ck_share_positive"),
        sa.CheckConstraint("share_bps <= 10000", name="ck_share_max"),
        sa.UniqueConstraint("contract_id", "position", name="uq_split_recipient_position"),
    )
    op.create_index(
        "ix_split_recipients_contract_id",
        "split_recipients",
        ["contract_id"],
    )
    op.create_index(
        "ix_split_recipient_contract",
        "split_recipients",
        ["contract_id", "is_active"],
    )

    # ── split_executions ────────────────────────────────────────
    op.create_table(
        "split_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contract_id", sa.Integer(), nullable=False),
        sa.Column("source_tx_hash", sa.String(), nullable=False),
        sa.Column("input_amount", sa.String(), nullable=False),
        sa.Column("input_token", sa.String(), nullable=False),
        sa.Column("input_decimals", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True, server_default="pending"),
        sa.Column("total_distributed", sa.String(), nullable=True),
        sa.Column("rsend_fee", sa.String(), nullable=True),
        sa.Column("remainder", sa.String(), nullable=True, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("distribution_detail", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contract_id"],
            ["split_contracts.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_split_executions_contract_id",
        "split_executions",
        ["contract_id"],
    )
    op.create_index(
        "ix_split_execution_contract_status",
        "split_executions",
        ["contract_id", "status"],
    )
    op.create_index(
        "ix_split_execution_source_tx",
        "split_executions",
        ["source_tx_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_split_execution_source_tx", table_name="split_executions")
    op.drop_index("ix_split_execution_contract_status", table_name="split_executions")
    op.drop_index("ix_split_executions_contract_id", table_name="split_executions")
    op.drop_table("split_executions")

    op.drop_index("ix_split_recipient_contract", table_name="split_recipients")
    op.drop_index("ix_split_recipients_contract_id", table_name="split_recipients")
    op.drop_table("split_recipients")

    op.drop_index("ix_split_contract_client_active", table_name="split_contracts")
    op.drop_index("ix_split_contracts_client_id", table_name="split_contracts")
    op.drop_table("split_contracts")
