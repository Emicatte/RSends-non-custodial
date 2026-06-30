"""add environment binding to payment_intents

Audit finding #1 (env binding on reads). `payment_intents.merchant_id` is the
key owner's address, which is IDENTICAL across that owner's test and live keys.
Without an environment dimension a `rsend_test_` key could read the owner's LIVE
intents. This adds the column that every merchant read/mutate now filters on
(app/api/merchant_routes.py) so test and live data are isolated server-side.

Added NOT NULL with server_default='live' so existing rows backfill to live
(legacy intents stay reachable only by live keys — the safe default). Idempotent:
the non-custodial baseline (0001) builds the schema from the live ORM via
Base.metadata.create_all, so a DB created after the column was added to the model
already has it; we add it only if missing.

Revision ID: 0005_payment_intent_environment
Revises: 0004_settlement_reversal_fired
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_payment_intent_environment"
down_revision = "0004_settlement_reversal_fired"
branch_labels = None
depends_on = None

TABLE = "payment_intents"
COLUMN = "environment"


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN, sa.String(8), nullable=False, server_default="live",
            ),
        )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
