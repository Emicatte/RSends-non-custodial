"""add environment binding to merchant_webhooks

Audit follow-up (webhook environment dimension). `merchant_webhooks.merchant_id`
is the key owner's address, IDENTICAL across that owner's test and live keys.
Without an environment dimension a `rsend_test_` key could register/test the
owner's LIVE webhooks, and outbound dispatch fanned out by merchant_id alone —
delivering live events to test endpoints and vice versa. This adds the column
that webhook lookup and dispatch now filter on (app/api/merchant_routes.py,
app/services/webhook_service.py).

Added NOT NULL with server_default='live' so existing rows backfill to live
(legacy webhooks keep receiving live events only — the safe default). Idempotent:
the non-custodial baseline (0001) builds the schema from the live ORM via
Base.metadata.create_all, so a DB created after the column was added to the model
already has it; we add it only if missing.

Revision ID: 0006_merchant_webhook_env
Revises: 0005_payment_intent_environment
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# NB: id kept ≤32 chars — Alembic hardcodes alembic_version.version_num as
# VARCHAR(32); the original "0006_merchant_webhook_environment" (33) truncated on
# Postgres (issue #17). Filename is unchanged; Alembic keys off this string.
revision = "0006_merchant_webhook_env"
down_revision = "0005_payment_intent_environment"
branch_labels = None
depends_on = None

TABLE = "merchant_webhooks"
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
