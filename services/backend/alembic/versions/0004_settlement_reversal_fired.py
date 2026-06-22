"""add reversal_fired_at guard to payment_settlements

The reorg-after-finalize path (payment_indexer._reverse_settlement) sends a
`payment.reversed` webhook when a settlement that already fired `payment.completed`
is reorged out. This adds the per-settlement guard that makes that reversal send
fire-once even under concurrent reconciles, claimed via an atomic conditional
UPDATE (NULL→now) just like `webhook_fired_at` does for the paid path.

Additive + nullable, so it is safe on a live database with no backfill.
Idempotent — the non-custodial baseline (0001) builds the schema from the live
ORM via Base.metadata.create_all, so a DB migrated *after* this column was added
to the model already has it; we add it only if missing.

Revision ID: 0004_settlement_reversal_fired
Revises: 0003_settlement_reorg_fields
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_settlement_reversal_fired"
down_revision = "0003_settlement_reorg_fields"
branch_labels = None
depends_on = None

TABLE = "payment_settlements"


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, "reversal_fired_at"):
        op.add_column(
            TABLE,
            sa.Column("reversal_fired_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_column(TABLE, "reversal_fired_at"):
        op.drop_column(TABLE, "reversal_fired_at")
