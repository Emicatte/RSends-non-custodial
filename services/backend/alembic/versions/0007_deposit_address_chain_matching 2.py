"""Deposit address, chain, and matching fields for PaymentIntent.

New columns on payment_intents:
  - deposit_address (String(42), unique, nullable, indexed)
  - chain (String(32), default "BASE")
  - matched_tx_hash (String(66), nullable, indexed)
  - matched_at (DateTime, nullable)

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Deposit address — indirizzo unico per intent ───────────
    op.add_column(
        "payment_intents",
        sa.Column("deposit_address", sa.String(42), nullable=True),
    )
    op.create_index(
        "ix_intent_deposit_address",
        "payment_intents",
        ["deposit_address"],
        unique=True,
    )

    # ── Chain — su quale chain accettare il pagamento ──────────
    op.add_column(
        "payment_intents",
        sa.Column("chain", sa.String(32), nullable=False, server_default="BASE"),
    )

    # ── Matching — TX hash e timestamp del match ───────────────
    op.add_column(
        "payment_intents",
        sa.Column("matched_tx_hash", sa.String(66), nullable=True),
    )
    op.create_index(
        "ix_intent_matched_tx_hash",
        "payment_intents",
        ["matched_tx_hash"],
    )

    op.add_column(
        "payment_intents",
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_intents", "matched_at")
    op.drop_index("ix_intent_matched_tx_hash", table_name="payment_intents")
    op.drop_column("payment_intents", "matched_tx_hash")
    op.drop_column("payment_intents", "chain")
    op.drop_index("ix_intent_deposit_address", table_name="payment_intents")
    op.drop_column("payment_intents", "deposit_address")
