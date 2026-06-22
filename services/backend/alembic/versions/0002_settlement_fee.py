"""add fee column to payment_settlements

Records the flat on-chain fee (paid payer -> feeCollector, on top of `amount`)
carried by the RSendsRouter.PaymentMade event. Additive + nullable, so it is
safe on a live database; no backfill is needed (settlements recorded before the
router emitted `fee` simply keep NULL).

Idempotent: the non-custodial baseline (0001) builds the schema from the live
ORM via Base.metadata.create_all, so a DB migrated *after* this column was added
to the model already has it. We therefore add the column only if it's missing,
so `alembic upgrade head` works both on fresh DBs and on databases that ran the
baseline before this column existed.

Revision ID: 0002_settlement_fee
Revises: 0001_noncustodial_baseline
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_settlement_fee"
down_revision = "0001_noncustodial_baseline"
branch_labels = None
depends_on = None

TABLE = "payment_settlements"
COLUMN = "fee"


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Numeric(78, 0), nullable=True))


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
