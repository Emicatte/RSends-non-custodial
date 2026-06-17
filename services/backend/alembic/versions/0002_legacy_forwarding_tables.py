"""Legacy forwarding tables (forwarding_rules, sweep_logs, audit_logs).

Queste tabelle esistevano prima di Alembic e venivano create da
metadata.create_all() all'avvio. Questa migrazione le porta
sotto la gestione di Alembic.

NOTA: Se le tabelle esistono già nel DB (produzione con init_db preesistente),
eseguire: alembic stamp 0002 --purge  oppure applicare manualmente.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── forwarding_rules ──────────────────────────────────────────────────
    op.create_table(
        "forwarding_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("source_wallet", sa.String(length=42), nullable=False),
        sa.Column("destination_wallet", sa.String(length=42), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("split_enabled", sa.Boolean(), nullable=False),
        sa.Column("split_percent", sa.Integer(), nullable=False),
        sa.Column("split_destination", sa.String(length=42), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("min_threshold", sa.Float(), nullable=False),
        sa.Column(
            "gas_strategy",
            sa.Enum("fast", "normal", "slow", name="gasstrategy"),
            nullable=True,
        ),
        sa.Column("max_gas_percent", sa.Float(), nullable=True),
        sa.Column("gas_limit_gwei", sa.Integer(), nullable=False),
        sa.Column("cooldown_sec", sa.Integer(), nullable=False),
        sa.Column(
            "max_daily_vol", sa.Numeric(precision=28, scale=18), nullable=True
        ),
        sa.Column("token_address", sa.String(length=42), nullable=True),
        sa.Column("token_symbol", sa.String(length=16), nullable=True),
        sa.Column("token_filter", sa.JSON(), nullable=True),
        sa.Column("auto_swap", sa.Boolean(), nullable=False),
        sa.Column("swap_to_token", sa.String(length=42), nullable=True),
        sa.Column("notify_enabled", sa.Boolean(), nullable=False),
        sa.Column("notify_channel", sa.String(length=20), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=50), nullable=True),
        sa.Column("email_address", sa.String(length=255), nullable=True),
        sa.Column("schedule_json", sa.JSON(), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_forwarding_rules_source_wallet"),
        "forwarding_rules",
        ["source_wallet"],
        unique=False,
    )
    op.create_index(
        op.f("ix_forwarding_rules_user_id"),
        "forwarding_rules",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_fwd_paused",
        "forwarding_rules",
        ["is_paused", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_fwd_source_active",
        "forwarding_rules",
        ["source_wallet", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_fwd_user_chain",
        "forwarding_rules",
        ["user_id", "chain_id"],
        unique=False,
    )

    # ── audit_logs (forwarding rule audit trail) ──────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=42), nullable=False),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["forwarding_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_actor", "audit_logs", ["actor"], unique=False
    )
    op.create_index(
        "ix_audit_created", "audit_logs", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_rule_id"), "audit_logs", ["rule_id"], unique=False
    )
    op.create_index(
        "ix_audit_rule_action",
        "audit_logs",
        ["rule_id", "action"],
        unique=False,
    )

    # ── sweep_logs ────────────────────────────────────────────────────────
    op.create_table(
        "sweep_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("source_wallet", sa.String(length=42), nullable=False),
        sa.Column("destination_wallet", sa.String(length=42), nullable=False),
        sa.Column("is_split", sa.Boolean(), nullable=True),
        sa.Column("split_index", sa.Integer(), nullable=True),
        sa.Column("split_percent", sa.Integer(), nullable=True),
        sa.Column("split_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("amount_wei", sa.String(length=78), nullable=False),
        sa.Column("amount_human", sa.Float(), nullable=False),
        sa.Column(
            "amount_display",
            sa.Numeric(precision=28, scale=18),
            nullable=False,
        ),
        sa.Column(
            "amount_usd", sa.Numeric(precision=18, scale=2), nullable=True
        ),
        sa.Column(
            "primary_amount",
            sa.Numeric(precision=28, scale=18),
            nullable=True,
        ),
        sa.Column(
            "split_amount", sa.Numeric(precision=28, scale=18), nullable=True
        ),
        sa.Column("token_symbol", sa.String(length=16), nullable=True),
        sa.Column("gas_used", sa.BigInteger(), nullable=True),
        sa.Column(
            "gas_price_gwei", sa.Numeric(precision=12, scale=4), nullable=True
        ),
        sa.Column(
            "gas_cost_eth", sa.Numeric(precision=28, scale=18), nullable=True
        ),
        sa.Column("gas_percent", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "executing",
                "completed",
                "failed",
                "gas_too_high",
                "skipped",
                name="sweepstatus",
            ),
            nullable=True,
        ),
        sa.Column("tx_hash", sa.String(length=66), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("trigger_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("fiscal_ref", sa.String(length=50), nullable=True),
        sa.Column("compliance_check", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["rule_id"], ["forwarding_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash"),
    )
    op.create_index(
        "ix_sweep_executed", "sweep_logs", ["executed_at"], unique=False
    )
    op.create_index(
        "ix_sweep_fiscal", "sweep_logs", ["fiscal_ref"], unique=False
    )
    op.create_index(
        op.f("ix_sweep_logs_rule_id"), "sweep_logs", ["rule_id"], unique=False
    )
    op.create_index(
        "ix_sweep_rule_status",
        "sweep_logs",
        ["rule_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_sweep_status",
        "sweep_logs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sweep_status", table_name="sweep_logs")
    op.drop_index("ix_sweep_rule_status", table_name="sweep_logs")
    op.drop_index(op.f("ix_sweep_logs_rule_id"), table_name="sweep_logs")
    op.drop_index("ix_sweep_fiscal", table_name="sweep_logs")
    op.drop_index("ix_sweep_executed", table_name="sweep_logs")
    op.drop_table("sweep_logs")
    op.drop_index("ix_audit_rule_action", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_rule_id"), table_name="audit_logs")
    op.drop_index("ix_audit_created", table_name="audit_logs")
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_fwd_user_chain", table_name="forwarding_rules")
    op.drop_index("ix_fwd_source_active", table_name="forwarding_rules")
    op.drop_index("ix_fwd_paused", table_name="forwarding_rules")
    op.drop_index(
        op.f("ix_forwarding_rules_user_id"), table_name="forwarding_rules"
    )
    op.drop_index(
        op.f("ix_forwarding_rules_source_wallet"),
        table_name="forwarding_rules",
    )
    op.drop_table("forwarding_rules")
