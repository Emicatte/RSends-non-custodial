"""Bootstrap legacy tables pre-alembic.

These tables were historically created by Base.metadata.create_all() at
backend startup (see app/db/session.py:init_db). Subsequent migrations
(0001+) assumed their existence. This makes them explicit so
`alembic upgrade head` from a clean schema works end-to-end.

Tables:
- transaction_logs       (db_models.py:46)
- compliance_snapshots   (db_models.py:95)    FK -> transaction_logs
- anomaly_alerts         (db_models.py:131)
- blacklisted_wallets    (aml_models.py:57)
- strategies             (strategy_models.py:14)

Enums:
- txstatus       (completed|failed|pending|cancelled)
- anomalytype    (volume_spike|amount_outlier|frequency_burst|unusual_network)

Zero behavior change: the tables are created empty, populated naturally by
existing code paths (same state as pre-drop).

Revision ID: 0000
Revises: (none - new first migration)
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # Enum types (txstatus, anomalytype) are auto-created by SQLAlchemy
    # on first use, following the codebase convention (see 0014_aml_tables).

    # ── transaction_logs ──────────────────────────────────────────
    op.create_table(
        "transaction_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fiscal_ref", sa.String(128), nullable=False, unique=True),
        sa.Column("payment_ref", sa.String(128), nullable=True),
        sa.Column("tx_hash", sa.String(66), nullable=False, unique=True),
        sa.Column("gross_amount", sa.Float(), nullable=False),
        sa.Column("net_amount", sa.Float(), nullable=False),
        sa.Column("fee_amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("eur_value", sa.Float(), nullable=True),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "completed",
                "failed",
                "pending",
                "cancelled",
                name="txstatus",
            ),
            nullable=False,
            server_default="completed",
        ),
        sa.Column("recipient", sa.String(42), nullable=True),
        sa.Column("x_signature", sa.String(256), nullable=False),
        sa.Column(
            "signature_valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("tx_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_transaction_logs_fiscal_ref", "transaction_logs", ["fiscal_ref"]
    )
    op.create_index(
        "ix_transaction_logs_tx_hash", "transaction_logs", ["tx_hash"]
    )
    op.create_index(
        "ix_tx_currency_date",
        "transaction_logs",
        ["currency", "tx_timestamp"],
    )
    op.create_index(
        "ix_tx_status_date",
        "transaction_logs",
        ["status", "tx_timestamp"],
    )

    # ── compliance_snapshots ──────────────────────────────────────
    op.create_table(
        "compliance_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("transaction_logs.id"),
            unique=True,
            nullable=False,
        ),
        sa.Column("compliance_id", sa.String(64), unique=True, nullable=False),
        sa.Column("block_timestamp", sa.String(64), nullable=True),
        sa.Column("fiat_rate", sa.Float(), nullable=True),
        sa.Column("asset", sa.String(16), nullable=True),
        sa.Column("fiat_gross", sa.Float(), nullable=True),
        sa.Column("ip_jurisdiction", sa.String(8), nullable=True),
        sa.Column(
            "mica_applicable",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
        sa.Column(
            "dac8_reportable",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
        sa.Column("network", sa.String(32), nullable=True),
        sa.Column("fiscal_ref", sa.String(128), nullable=True),
        sa.Column(
            "dac8_xml_generated",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
        sa.Column("dac8_xml_path", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # ── anomaly_alerts ────────────────────────────────────────────
    op.create_table(
        "anomaly_alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "anomaly_type",
            sa.Enum(
                "volume_spike",
                "amount_outlier",
                "frequency_burst",
                "unusual_network",
                name="anomalytype",
            ),
            nullable=False,
        ),
        sa.Column("z_score", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "affected_tx_count",
            sa.Integer(),
            nullable=True,
            server_default="0",
        ),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # ── blacklisted_wallets ───────────────────────────────────────
    op.create_table(
        "blacklisted_wallets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("address", sa.String(42), unique=True, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("added_by", sa.String(42), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=True,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_blacklisted_wallets_address",
        "blacklisted_wallets",
        ["address"],
    )

    # ── strategies ────────────────────────────────────────────────
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_address", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=True,
            server_default=sa.true(),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=True,
            server_default="0",
        ),
        sa.Column(
            "chain_family",
            sa.String(),
            nullable=True,
            server_default="evm",
        ),
        sa.Column("chain_id", sa.String(), nullable=True),
        sa.Column(
            "conditions",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "actions",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("max_executions_per_day", sa.Integer(), nullable=True),
        sa.Column(
            "cooldown_seconds",
            sa.Integer(),
            nullable=True,
            server_default="60",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "total_executions",
            sa.Integer(),
            nullable=True,
            server_default="0",
        ),
        sa.Column("last_executed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_strategies_owner_address", "strategies", ["owner_address"]
    )


def downgrade() -> None:
    op.drop_index("ix_strategies_owner_address", table_name="strategies")
    op.drop_table("strategies")

    op.drop_index(
        "ix_blacklisted_wallets_address", table_name="blacklisted_wallets"
    )
    op.drop_table("blacklisted_wallets")

    op.drop_table("anomaly_alerts")
    op.drop_table("compliance_snapshots")

    op.drop_index("ix_tx_status_date", table_name="transaction_logs")
    op.drop_index("ix_tx_currency_date", table_name="transaction_logs")
    op.drop_index("ix_transaction_logs_tx_hash", table_name="transaction_logs")
    op.drop_index(
        "ix_transaction_logs_fiscal_ref", table_name="transaction_logs"
    )
    op.drop_table("transaction_logs")

    bind = op.get_bind()
    if _is_postgres():
        postgresql.ENUM(name="anomalytype").drop(bind, checkfirst=True)
        postgresql.ENUM(name="txstatus").drop(bind, checkfirst=True)
