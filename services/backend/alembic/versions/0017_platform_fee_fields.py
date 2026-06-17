"""Add platform fee tracking columns to payment_intents.

Additive migration — adds nullable columns only.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_intents", sa.Column("fee_bps", sa.Integer(), nullable=True))
    op.add_column("payment_intents", sa.Column("fee_amount", sa.String(32), nullable=True))
    op.add_column("payment_intents", sa.Column("fee_tx_hash", sa.String(130), nullable=True))
    op.add_column("payment_intents", sa.Column("fee_swept_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_intents", sa.Column("merchant_sweep_amount", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("payment_intents", "merchant_sweep_amount")
    op.drop_column("payment_intents", "fee_swept_at")
    op.drop_column("payment_intents", "fee_tx_hash")
    op.drop_column("payment_intents", "fee_amount")
    op.drop_column("payment_intents", "fee_bps")
