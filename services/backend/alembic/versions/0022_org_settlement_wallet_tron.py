"""add settlement_wallet_tron to organizations

    settlement_wallet_tron  TEXT NULL

TRON payouts need their own column; they cannot share `settlement_wallet`
(0008). That column is EVM: validated against `^0x[a-fA-F0-9]{40}$` and STORED
LOWERCASE. A TRON address is base58check — a 34-character string over an
alphabet that deliberately excludes `0 O I l` — so lowercasing one does not
merely change it, it can produce a string that is not valid base58 at all, and
the checksum stops verifying. Reusing the column would therefore either corrupt
every TRON address written through the existing normalisation, or force that
normalisation to branch on a guess about which chain the value is for. Two
columns, two validators, no guessing.

`settlement_wallet` REMAINS THE PRIMARY payout address and is unchanged by this
migration. This column is TRON-only.

NULLABLE with NO server_default and NO backfill, exactly like 0008 and for the
same reason: there is no safe value to derive (an EVM address is not a TRON
address, and deriving a payout address from anything is forbidden). NULL means
"this org has not set a TRON payout address", which is the correct and honest
state for every existing row — no org has set one, because until now there was
nowhere to put it. Nothing changes behaviour when this lands: the recipient gate
already fails closed (422 SETTLEMENT_WALLET_MISSING) when no recipient resolves,
so a NULL here can only produce the same refusal that exists today, never a
broken /pay link or a payment to an arbitrary payee.

Split payments stay EVM-only and are untouched: splits execute through the
immutable fee router, and TRON has no router deployment — a watch-only chain has
no contract to carry legs. See `PaymentIntentRecipient` (0013).

Existence-guarded like 0008/0011/0021: 0001 is a create_all of the CURRENT ORM,
which now declares this column, so on a from-scratch `upgrade head` it already
exists by the time this runs. Load-bearing, not hygiene —
test_migrations_postgres::test_stamp_then_upgrade_is_noop enforces it.

Downgrade drops the column, guarded. Genuinely reversible in the sense that
matters: no other row's meaning depends on it, and an org that had set a TRON
payout address simply reads back as one that has not. Nothing is corrupted and
no EVM settlement is affected.

Verify after running (one row, nullable, no default; and no org has one set):
    SELECT column_name, data_type, is_nullable, column_default
    FROM information_schema.columns
    WHERE table_name = 'organizations'
      AND column_name = 'settlement_wallet_tron';

    SELECT count(*) FROM organizations WHERE settlement_wallet_tron IS NOT NULL;

Revision ID: 0022_org_settlement_wallet_tron
Revises: 0021_webhook_auto_disable
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# NB: id is 31 chars — alembic_version.version_num is VARCHAR(32), so this fits
# with one to spare. Pinned by test_migrations_postgres.
revision = "0022_org_settlement_wallet_tron"
down_revision = "0021_webhook_auto_disable"
branch_labels = None
depends_on = None

TABLE = "organizations"
COLUMN = "settlement_wallet_tron"


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
