"""add settlement_wallet to organizations

Phase B (settlement wallet + recipient gate). Adds the org-level settlement
address — the wallet where an org receives on-chain payments, shared across team
members and set explicitly by an admin in Settings (never auto-derived).

NULLABLE with NO server_default and NO backfill (unlike 0005/0006): there is no
safe value to derive (deriving from a wallet is forbidden), and NULL is safe
because the recipient gate blocks intent creation when no recipient resolves —
it never mints a broken /pay link. Existing orgs read back NULL and see a
"set your settlement wallet" prompt until an admin sets one.

Idempotent: the non-custodial baseline builds the schema from the live ORM via
Base.metadata.create_all, so a DB created after the column was added to the model
already has it; we add it only if missing.

Revision ID: 0008_org_settlement_wallet
Revises: 0007_users_email_lower_unique
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0008_org_settlement_wallet"
down_revision = "0007_users_email_lower_unique"
branch_labels = None
depends_on = None

TABLE = "organizations"
COLUMN = "settlement_wallet"


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Text(), nullable=True),
        )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
