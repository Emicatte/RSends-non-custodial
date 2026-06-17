"""Sweep fields and new statuses (sweeping, settled) for PaymentIntent.

New columns on payment_intents:
  - sweep_tx_hash (String(66), nullable, indexed)
  - swept_at (DateTime, nullable)

New enum values for intent_status:
  - sweeping
  - settled

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Sweep TX hash ─────────────────────────────────────────
    op.add_column(
        "payment_intents",
        sa.Column("sweep_tx_hash", sa.String(66), nullable=True),
    )
    op.create_index(
        "ix_intent_sweep_tx_hash",
        "payment_intents",
        ["sweep_tx_hash"],
    )

    # ── Swept at timestamp ────────────────────────────────────
    op.add_column(
        "payment_intents",
        sa.Column("swept_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Nota: i nuovi enum values (sweeping, settled) sono gestiti
    # automaticamente da SQLAlchemy con String-based enum.
    # Per PostgreSQL con enum nativo, aggiungere:
    #   op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'sweeping'")
    #   op.execute("ALTER TYPE intentstatus ADD VALUE IF NOT EXISTS 'settled'")


def downgrade() -> None:
    op.drop_column("payment_intents", "swept_at")
    op.drop_index("ix_intent_sweep_tx_hash", table_name="payment_intents")
    op.drop_column("payment_intents", "sweep_tx_hash")
