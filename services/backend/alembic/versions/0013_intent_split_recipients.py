"""Split recipients child table + settlement split legs (non-custodial split).

A split intent fans the principal out to 2..20 recipients by basis points
(sum EXACTLY 10000) in ONE payer transaction via the ownerless, fee-less
RSendsSplitRouter. The legs live in `payment_intent_recipients` (position 0 =
primary, receives the integer remainder); the parent `payment_intents.recipient`
stays NULL for splits. `payment_settlements.split_legs` records the validated
per-leg breakdown on the (single, aggregate) settlement row — added here so the
indexer phase needs no second migration.

Idempotent, existence-guarded like 0011/0012. Downgrade drops both.

Revision ID: 0013_intent_split_recipients
Revises: 0012_indexer_cursors
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0013_intent_split_recipients"
down_revision = "0012_indexer_cursors"
branch_labels = None
depends_on = None

_TABLE = "payment_intent_recipients"
_SETTLEMENTS = "payment_settlements"
_LEGS_COL = "split_legs"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "intent_id",
                sa.String(64),
                sa.ForeignKey("payment_intents.intent_id"),
                nullable=False,
                index=True,
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("address", sa.String(42), nullable=False),
            sa.Column("share_bps", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(64), nullable=True),
            sa.UniqueConstraint(
                "intent_id", "position", name="uq_intent_recipient_position"
            ),
            sa.UniqueConstraint(
                "intent_id", "address", name="uq_intent_recipient_address"
            ),
            sa.CheckConstraint(
                "share_bps >= 1 AND share_bps <= 10000",
                name="ck_intent_recipient_bps",
            ),
        )

    if not _has_column(_SETTLEMENTS, _LEGS_COL):
        op.add_column(_SETTLEMENTS, sa.Column(_LEGS_COL, sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column(_SETTLEMENTS, _LEGS_COL):
        op.drop_column(_SETTLEMENTS, _LEGS_COL)
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
