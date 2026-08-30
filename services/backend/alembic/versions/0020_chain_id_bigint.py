"""Widen the two chain_id columns to BIGINT — a TRON testnet id does not fit.

A chain id is not always small. TRON derives its chain id from the low 4 bytes
of the network's genesis block hash, read as UNSIGNED: mainnet's 728126428
happens to fit a 4-byte SIGNED integer, and Nile's 3448148188 (0xcd8690dc) does
not — Postgres INTEGER tops out at 2147483647.

Two columns are affected, and both are on the TRON write path:
  * indexer_cursors.chain_id     (primary key; the poller's per-network cursor)
  * payment_settlements.chain_id (indexed, part of uq_settlement_onchain_log)

Why this is a migration and not a model tweak: the test suite CANNOT catch the
overflow. Tests and CI run on sqlite+aiosqlite, which is dynamically typed and
stores 3448148188 in an INTEGER column without complaint, so the models, the
whole suite and the CI job all go green while production raises
NumericValueOutOfRange on the very first Nile cursor write. The regression test
that can see it is Postgres-gated:
test_migrations_postgres.py::test_a_tron_testnet_chain_id_fits_after_0020.

Widening is safe and does not rewrite semantics: every existing value is a small
positive integer that means the same thing in bigint. On Postgres this is an
ALTER COLUMN TYPE, which rebuilds the table's indexes and the unique constraint
along with it — brief, and these tables are small.

Existence-guarded like 0010/0011/0012, so it is a no-op against a database that
never had the tables.

Downgrade REFUSES rather than truncating. Narrowing a column that holds
3448148188 would either error mid-statement or, worse on a backend that
silently wraps, corrupt a settlement's chain identity into a negative number
that matches nothing. If you genuinely need to go back, delete the offending
rows deliberately first — a downgrade must not decide that for you.

Revision ID: 0020_chain_id_bigint
Revises: 0019_intent_pending_unique
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0020_chain_id_bigint"
down_revision = "0019_intent_pending_unique"
branch_labels = None
depends_on = None

_INT32_MAX = 2147483647

# (table, column, nullable) — nullability is restated because alter_column
# needs existing_nullable to leave the constraint untouched.
_COLUMNS = (
    ("indexer_cursors", "chain_id", False),
    ("payment_settlements", "chain_id", False),
)


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    for table, column, nullable in _COLUMNS:
        if not _has_table(table):
            continue
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column, nullable in _COLUMNS:
        if not _has_table(table):
            continue
        oversized = bind.execute(
            sa.text(
                f"SELECT count(*) FROM {table} WHERE {column} > :ceiling"  # noqa: S608
            ),
            {"ceiling": _INT32_MAX},
        ).scalar()
        if oversized:
            raise RuntimeError(
                f"refusing to narrow {table}.{column} to INTEGER: {oversized} "
                f"row(s) hold a chain id above {_INT32_MAX} (TRON Nile is "
                f"3448148188). Narrowing would corrupt or drop their chain "
                f"identity. Remove those rows deliberately, then downgrade."
            )
        op.alter_column(
            table,
            column,
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=nullable,
        )
