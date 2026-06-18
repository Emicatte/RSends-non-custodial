"""Late payment policy columns + new IntentStatus values.

New columns on payment_intents:
  - late_payment_policy (String(10), default "auto")
  - completed_late (Boolean, default false)
  - late_minutes (Integer, nullable)

New enum values for intentstatus:
  - review
  - refunded

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add new enum values (must run outside transaction in PostgreSQL) ──
    op.execute("COMMIT")
    op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'review'")
    op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'refunded'")
    op.execute("BEGIN")

    # ── Add late payment columns to payment_intents ──────────
    op.add_column(
        "payment_intents",
        sa.Column("late_payment_policy", sa.String(10), nullable=False, server_default="auto"),
    )
    op.add_column(
        "payment_intents",
        sa.Column("completed_late", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "payment_intents",
        sa.Column("late_minutes", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_intents", "late_minutes")
    op.drop_column("payment_intents", "completed_late")
    op.drop_column("payment_intents", "late_payment_policy")
    # Note: PostgreSQL non supporta la rimozione di valori da un enum type.
    # I valori 'review' e 'refunded' resteranno nel tipo intentstatus.
