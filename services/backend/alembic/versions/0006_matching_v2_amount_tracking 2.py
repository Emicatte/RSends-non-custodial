"""Matching v2: amount tracking + tolerance config + new IntentStatus values.

New columns on payment_intents:
  - amount_received (String, default "0")
  - overpaid_amount (String, nullable)
  - underpaid_amount (String, nullable)
  - amount_tolerance_percent (Float, default 1.0)
  - allow_partial (Boolean, default false)
  - allow_overpayment (Boolean, default true)

New enum values for intentstatus:
  - partial
  - overpaid

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add new enum values (must run outside transaction in PostgreSQL) ──
    op.execute("COMMIT")
    op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'partial'")
    op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'overpaid'")
    op.execute("BEGIN")

    # ── Amount tracking columns ─────────────────────────────
    op.add_column(
        "payment_intents",
        sa.Column("amount_received", sa.String, nullable=False, server_default="0"),
    )
    op.add_column(
        "payment_intents",
        sa.Column("overpaid_amount", sa.String, nullable=True),
    )
    op.add_column(
        "payment_intents",
        sa.Column("underpaid_amount", sa.String, nullable=True),
    )

    # ── Merchant tolerance config columns ───────────────────
    op.add_column(
        "payment_intents",
        sa.Column(
            "amount_tolerance_percent", sa.Float, nullable=False, server_default="1.0",
        ),
    )
    op.add_column(
        "payment_intents",
        sa.Column(
            "allow_partial", sa.Boolean, nullable=False, server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "payment_intents",
        sa.Column(
            "allow_overpayment", sa.Boolean, nullable=False, server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_intents", "allow_overpayment")
    op.drop_column("payment_intents", "allow_partial")
    op.drop_column("payment_intents", "amount_tolerance_percent")
    op.drop_column("payment_intents", "underpaid_amount")
    op.drop_column("payment_intents", "overpaid_amount")
    op.drop_column("payment_intents", "amount_received")
    # Note: PostgreSQL non supporta la rimozione di valori da un enum type.
    # I valori 'partial' e 'overpaid' resteranno nel tipo intentstatus.
