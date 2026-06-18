"""Create AML tables: sanctions_list, aml_alerts, aml_config.

Additive migration — does not touch existing blacklisted_wallets table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sanctions_list ────────────────────────────────────
    op.create_table(
        "sanctions_list",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("program", sa.String(50), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sanctions_address", "sanctions_list", ["address"])
    op.create_index(
        "ix_sanctions_address_active",
        "sanctions_list",
        ["address", "is_active"],
    )

    # ── aml_alerts ────────────────────────────────────────
    op.create_table(
        "aml_alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("sender", sa.String(42), nullable=False),
        sa.Column("recipient", sa.String(42), nullable=False),
        sa.Column("chain_id", sa.Integer, nullable=True),
        sa.Column("amount_eur", sa.Float, nullable=True),
        sa.Column("token_symbol", sa.String(20), nullable=True),
        sa.Column(
            "alert_type",
            sa.Enum(
                "sanctions_hit", "threshold_single", "threshold_daily",
                "threshold_monthly", "velocity", "structuring",
                "round_trip", "new_wallet_high_value",
                name="alerttype",
            ),
            nullable=False,
        ),
        sa.Column(
            "risk_level",
            sa.Enum("low", "medium", "high", "blocked", name="risklevel"),
            nullable=False,
        ),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "reviewed", "escalated", "dismissed", name="alertstatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text, nullable=True),
        sa.Column("requires_kyc", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("sar_filed", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_aml_alerts_created_at", "aml_alerts", ["created_at"])
    op.create_index("ix_aml_alerts_status", "aml_alerts", ["status"])
    op.create_index("ix_aml_alerts_sender", "aml_alerts", ["sender"])
    op.create_index(
        "ix_aml_alerts_sender_ts",
        "aml_alerts",
        ["sender", "created_at"],
    )

    # ── aml_config (single row) ───────────────────────────
    op.create_table(
        "aml_config",
        sa.Column("id", sa.Integer, primary_key=True, default=1),
        sa.Column("threshold_single_eur", sa.Float, nullable=False, server_default="1000.0"),
        sa.Column("threshold_daily_eur", sa.Float, nullable=False, server_default="5000.0"),
        sa.Column("threshold_monthly_eur", sa.Float, nullable=False, server_default="15000.0"),
        sa.Column("velocity_limit_per_hour", sa.Integer, nullable=False, server_default="10"),
        sa.Column("structuring_window_hours", sa.Integer, nullable=False, server_default="24"),
        sa.Column("structuring_min_count", sa.Integer, nullable=False, server_default="5"),
        sa.Column("structuring_threshold_pct", sa.Float, nullable=False, server_default="0.9"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Insert default config row
    op.execute(
        "INSERT INTO aml_config (id, threshold_single_eur, threshold_daily_eur, "
        "threshold_monthly_eur, velocity_limit_per_hour, structuring_window_hours, "
        "structuring_min_count, structuring_threshold_pct) "
        "VALUES (1, 1000.0, 5000.0, 15000.0, 10, 24, 5, 0.9)"
    )


def downgrade() -> None:
    op.drop_table("aml_config")
    op.drop_index("ix_aml_alerts_sender_ts", table_name="aml_alerts")
    op.drop_index("ix_aml_alerts_sender", table_name="aml_alerts")
    op.drop_index("ix_aml_alerts_status", table_name="aml_alerts")
    op.drop_index("ix_aml_alerts_created_at", table_name="aml_alerts")
    op.drop_table("aml_alerts")
    op.drop_index("ix_sanctions_address_active", table_name="sanctions_list")
    op.drop_index("ix_sanctions_address", table_name="sanctions_list")
    op.drop_table("sanctions_list")

    # Drop enums (PostgreSQL-specific)
    op.execute("DROP TYPE IF EXISTS alerttype")
    op.execute("DROP TYPE IF EXISTS risklevel")
    op.execute("DROP TYPE IF EXISTS alertstatus")
