"""Per-chain indexer block cursor — Postgres as source of truth.

The payment indexer's cursor previously lived only in Redis
(`indexer:last_block:{chain_id}`): a flush or restart re-initialized the
indexer at the current chain head, permanently skipping the gap — silent
payment loss. This table makes Postgres authoritative; the indexer adopts a
legacy Redis cursor into it on first read after deploy (no init-at-head skip
at rollout), and Redis stays as a hot cache only.

Idempotent, existence-guarded like 0010/0011. Downgrade drops the table —
after a downgrade the indexer falls back to the legacy Redis-only behavior.

Revision ID: 0012_indexer_cursors
Revises: 0011_api_keys_org_id
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0012_indexer_cursors"
down_revision = "0011_api_keys_org_id"
branch_labels = None
depends_on = None

_TABLE = "indexer_cursors"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("chain_id", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("last_block", sa.BigInteger(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
