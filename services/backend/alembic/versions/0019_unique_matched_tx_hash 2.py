"""Partial unique index on matched_tx_hash to prevent double-matching.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-17
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_intents_matched_tx_hash "
        "ON payment_intents (matched_tx_hash) WHERE matched_tx_hash IS NOT NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_payment_intents_matched_tx_hash")
