"""Command Center models + ForwardingRule V2 + AuditLog chain hash.

New tables:
  - distribution_lists
  - distribution_recipients
  - sweep_batches
  - sweep_batch_items
  - spending_ledger
  - nonce_tracker
  - circuit_breaker_states

Altered tables:
  - forwarding_rules: destination_wallet → nullable, +distribution_list_id FK, +CHECK
  - audit_log: +sequence_number, +chain_hash, +previous_hash

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ══════════════════════════════════════════════════════════════
    #  distribution_lists
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "distribution_lists",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("owner_address", sa.String(42), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("chain_id", sa.Integer(), nullable=False, server_default="8453"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_dist_list_owner", "distribution_lists", ["owner_address", "chain_id"]
    )
    op.create_index(
        "ix_dist_list_active", "distribution_lists", ["is_active"]
    )

    # ══════════════════════════════════════════════════════════════
    #  distribution_recipients
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "distribution_recipients",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "list_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("distribution_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("percent_bps", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "percent_bps >= 1 AND percent_bps <= 10000",
            name="ck_recipient_bps_range",
        ),
        sa.UniqueConstraint("list_id", "address", name="uq_recipient_list_addr"),
    )
    op.create_index(
        "ix_recipient_list_active", "distribution_recipients", ["list_id", "is_active"]
    )

    # ══════════════════════════════════════════════════════════════
    #  sweep_batches
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "sweep_batches",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("incoming_tx_hash", sa.String(66), nullable=False),
        sa.Column("source_address", sa.String(42), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("total_amount_wei", sa.String(78), nullable=False),
        sa.Column("token_address", sa.String(42), nullable=True),
        sa.Column("token_symbol", sa.String(16), nullable=False, server_default="ETH"),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="PENDING"
        ),
        sa.Column(
            "forwarding_rule_id",
            sa.Integer(),
            sa.ForeignKey("forwarding_rules.id"),
            nullable=True,
        ),
        sa.Column(
            "distribution_list_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("distribution_lists.id"),
            nullable=True,
        ),
        sa.Column("gas_price_wei", sa.String(78), nullable=True),
        sa.Column("total_gas_cost_wei", sa.String(78), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("incoming_tx_hash", name="uq_batch_incoming_tx"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','FAILED','PARTIAL')",
            name="ck_sweep_batch_status",
        ),
    )
    op.create_index(
        "ix_batch_status_created", "sweep_batches", ["status", "created_at"]
    )
    op.create_index(
        "ix_batch_source_chain", "sweep_batches", ["source_address", "chain_id"]
    )
    op.create_index("ix_batch_rule", "sweep_batches", ["forwarding_rule_id"])

    # ══════════════════════════════════════════════════════════════
    #  sweep_batch_items
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "sweep_batch_items",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("sweep_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_address", sa.String(42), nullable=False),
        sa.Column("amount_wei", sa.String(78), nullable=False),
        sa.Column("percent_bps", sa.Integer(), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="PENDING"
        ),
        sa.Column("nonce", sa.Integer(), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tx_hash", name="uq_batch_item_tx_hash"),
        sa.CheckConstraint(
            "status IN ('PENDING','SIGNING','SUBMITTED','CONFIRMED','FAILED')",
            name="ck_batch_item_status",
        ),
        sa.CheckConstraint(
            "percent_bps >= 1 AND percent_bps <= 10000",
            name="ck_batch_item_bps_range",
        ),
    )
    op.create_index(
        "ix_item_batch_status", "sweep_batch_items", ["batch_id", "status"]
    )

    # ══════════════════════════════════════════════════════════════
    #  spending_ledger
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "spending_ledger",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("source_address", sa.String(42), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("amount_wei", sa.String(78), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column(
            "sweep_batch_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("sweep_batches.id"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('RESERVE','RELEASE')",
            name="ck_spending_direction",
        ),
        sa.CheckConstraint(
            "tier IN ('per_tx','per_hour','per_day','global_daily','velocity')",
            name="ck_spending_tier",
        ),
    )
    op.create_index(
        "ix_spending_source_chain",
        "spending_ledger",
        ["source_address", "chain_id", "created_at"],
    )
    op.create_index("ix_spending_created", "spending_ledger", ["created_at"])
    op.create_index("ix_spending_batch", "spending_ledger", ["sweep_batch_id"])

    # ══════════════════════════════════════════════════════════════
    #  nonce_tracker
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "nonce_tracker",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("current_nonce", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_confirmed_nonce", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chain_id", "address", name="uq_nonce_chain_addr"),
        sa.CheckConstraint(
            "current_nonce >= last_confirmed_nonce",
            name="ck_nonce_ordering",
        ),
        sa.CheckConstraint("pending_count >= 0", name="ck_nonce_pending_gte0"),
    )

    # ══════════════════════════════════════════════════════════════
    #  circuit_breaker_states
    # ══════════════════════════════════════════════════════════════
    op.create_table(
        "circuit_breaker_states",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "state", sa.String(16), nullable=False, server_default="CLOSED"
        ),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("force_reason", sa.Text(), nullable=True),
        sa.Column("error_rate", sa.Float(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_cb_state_name"),
        sa.CheckConstraint(
            "state IN ('CLOSED','OPEN','HALF_OPEN')",
            name="ck_cb_state_valid",
        ),
        sa.CheckConstraint("failure_count >= 0", name="ck_cb_failures_gte0"),
        sa.CheckConstraint("success_count >= 0", name="ck_cb_successes_gte0"),
    )

    # ══════════════════════════════════════════════════════════════
    #  ALTER: forwarding_rules V2
    # ══════════════════════════════════════════════════════════════

    # Make destination_wallet nullable (was NOT NULL)
    op.alter_column(
        "forwarding_rules",
        "destination_wallet",
        existing_type=sa.String(42),
        nullable=True,
    )

    # Add distribution_list_id FK
    op.add_column(
        "forwarding_rules",
        sa.Column(
            "distribution_list_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_fwd_dist_list",
        "forwarding_rules",
        "distribution_lists",
        ["distribution_list_id"],
        ["id"],
    )
    op.create_index(
        "ix_fwd_dist_list", "forwarding_rules", ["distribution_list_id"]
    )

    # CHECK: must have dest OR distribution list
    op.create_check_constraint(
        "ck_fwd_dest_or_distlist",
        "forwarding_rules",
        "destination_wallet IS NOT NULL OR distribution_list_id IS NOT NULL",
    )

    # ══════════════════════════════════════════════════════════════
    #  ALTER: audit_log — chain hash for tamper detection
    # ══════════════════════════════════════════════════════════════

    # sequence_number: monotonically increasing, gaps = tampering
    op.add_column(
        "audit_log",
        sa.Column("sequence_number", sa.BigInteger(), nullable=True),
    )
    # chain_hash: SHA-256(previous_hash || entry_data)
    op.add_column(
        "audit_log",
        sa.Column("chain_hash", sa.String(64), nullable=True),
    )
    # previous_hash: chain_hash of the preceding entry ("0"*64 for first)
    op.add_column(
        "audit_log",
        sa.Column("previous_hash", sa.String(64), nullable=True),
    )

    # Backfill existing rows (if any) with placeholder values
    op.execute(
        "UPDATE audit_log SET sequence_number = id, "
        "chain_hash = '0000000000000000000000000000000000000000000000000000000000000000', "
        "previous_hash = '0000000000000000000000000000000000000000000000000000000000000000' "
        "WHERE sequence_number IS NULL"
    )

    # Now make NOT NULL
    op.alter_column("audit_log", "sequence_number", nullable=False)
    op.alter_column("audit_log", "chain_hash", nullable=False)
    op.alter_column("audit_log", "previous_hash", nullable=False)

    op.create_index("idx_audit_log_seq", "audit_log", ["sequence_number"], unique=True)


def downgrade() -> None:
    # ── Undo audit_log chain hash ─────────────────────────────
    op.drop_index("idx_audit_log_seq", table_name="audit_log")
    op.drop_column("audit_log", "previous_hash")
    op.drop_column("audit_log", "chain_hash")
    op.drop_column("audit_log", "sequence_number")

    # ── Undo forwarding_rules V2 ──────────────────────────────
    op.drop_constraint("ck_fwd_dest_or_distlist", "forwarding_rules", type_="check")
    op.drop_index("ix_fwd_dist_list", table_name="forwarding_rules")
    op.drop_constraint("fk_fwd_dist_list", "forwarding_rules", type_="foreignkey")
    op.drop_column("forwarding_rules", "distribution_list_id")
    op.alter_column(
        "forwarding_rules",
        "destination_wallet",
        existing_type=sa.String(42),
        nullable=False,
    )

    # ── Drop new tables (reverse FK order) ────────────────────
    op.drop_table("circuit_breaker_states")
    op.drop_table("nonce_tracker")

    op.drop_index("ix_spending_batch", table_name="spending_ledger")
    op.drop_index("ix_spending_created", table_name="spending_ledger")
    op.drop_index("ix_spending_source_chain", table_name="spending_ledger")
    op.drop_table("spending_ledger")

    op.drop_index("ix_item_batch_status", table_name="sweep_batch_items")
    op.drop_table("sweep_batch_items")

    op.drop_index("ix_batch_rule", table_name="sweep_batches")
    op.drop_index("ix_batch_source_chain", table_name="sweep_batches")
    op.drop_index("ix_batch_status_created", table_name="sweep_batches")
    op.drop_table("sweep_batches")

    op.drop_index("ix_recipient_list_active", table_name="distribution_recipients")
    op.drop_table("distribution_recipients")

    op.drop_index("ix_dist_list_active", table_name="distribution_lists")
    op.drop_index("ix_dist_list_owner", table_name="distribution_lists")
    op.drop_table("distribution_lists")
