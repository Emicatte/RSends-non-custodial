"""add reorg-safe lifecycle fields to payment_settlements

Adds the columns the hardened indexer needs to mark invoices paid only after a
settlement is FINAL with a still-canonical block hash, and to reverse the effect
if a reorg is later detected:

  - block_hash       : canonical block hash the log was observed in (reorg key)
  - status           : pending / final / reorged / rejected lifecycle
  - finalized_at     : when the row reached `final`
  - webhook_fired_at : "fire payment.completed exactly once" guard

All additive + nullable (status carries a server_default), so it is safe on a
live database with no backfill. Idempotent — the non-custodial baseline (0001)
builds the schema from the live ORM via Base.metadata.create_all, so a DB
migrated *after* these columns were added to the model already has them; we add
each column only if it's missing.

Revision ID: 0003_settlement_reorg_fields
Revises: 0002_settlement_fee
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_settlement_reorg_fields"
down_revision = "0002_settlement_fee"
branch_labels = None
depends_on = None

TABLE = "payment_settlements"


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, "block_hash"):
        op.add_column(TABLE, sa.Column("block_hash", sa.String(66), nullable=True))
    if not _has_column(TABLE, "status"):
        # SAEnum maps to VARCHAR on SQLite and a native enum on Postgres; using a
        # plain String here keeps the migration portable (the ORM enum still
        # validates values at the application layer). server_default keeps the
        # column NOT NULL for any existing rows.
        op.add_column(
            TABLE,
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="pending",
            ),
        )
        op.create_index("ix_settlement_chain_status", TABLE, ["chain_id", "status"])
    if not _has_column(TABLE, "finalized_at"):
        op.add_column(TABLE, sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(TABLE, "webhook_fired_at"):
        op.add_column(TABLE, sa.Column("webhook_fired_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if _has_column(TABLE, "webhook_fired_at"):
        op.drop_column(TABLE, "webhook_fired_at")
    if _has_column(TABLE, "finalized_at"):
        op.drop_column(TABLE, "finalized_at")
    if _has_column(TABLE, "status"):
        try:
            op.drop_index("ix_settlement_chain_status", table_name=TABLE)
        except Exception:
            pass
        op.drop_column(TABLE, "status")
    if _has_column(TABLE, "block_hash"):
        op.drop_column(TABLE, "block_hash")
