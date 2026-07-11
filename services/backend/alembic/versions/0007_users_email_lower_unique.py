"""one account per email: unique index on lower(users.email)

Account-linking audit, case (b): Google login could create a second account
for an email already registered via password/GitHub. The application-level
guards (409 block-and-guide on every entry path) are the fix; this index is
the DB backstop so "one account per case-insensitive email" holds BY
CONSTRUCTION against any future bug or race.

Safe on populated databases, in three ordered steps:
  1. Check for pre-existing case-insensitive duplicate emails. If any exist,
     REPORT AND STOP — never auto-merge user accounts (that would be silent
     account merging, which the block-and-guide decision explicitly forbids)
     and never let the index build crash mid-apply. Resolve the listed
     duplicates manually, then re-run.
  2. Normalize existing rows to lower(trim(email)) — every ingest path now
     normalizes, legacy rows must match.
  3. Create the unique expression index (idempotent: fresh DBs — and all
     test DBs — already have it from the User model's __table_args__ via
     Base.metadata.create_all in the 0001 baseline).

Revision ID: 0007_users_email_lower_unique
Revises: 0006_merchant_webhook_env
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0007_users_email_lower_unique"
down_revision = "0006_merchant_webhook_env"
branch_labels = None
depends_on = None

TABLE = "users"
INDEX = "uq_users_email_lower"


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _find_case_insensitive_duplicates(bind) -> list[tuple[str, int]]:
    rows = bind.execute(
        sa.text(
            "SELECT lower(trim(email)) AS e, COUNT(*) AS n "
            "FROM users GROUP BY lower(trim(email)) HAVING COUNT(*) > 1"
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Report-and-stop on pre-existing duplicates (never auto-merge users).
    dupes = _find_case_insensitive_duplicates(bind)
    if dupes:
        listing = ", ".join(f"{email} (x{n})" for email, n in dupes)
        raise RuntimeError(
            f"Cannot apply {revision}: {len(dupes)} case-insensitive duplicate "
            f"email(s) exist in `users`: {listing}. Resolve them manually "
            "(decide which account keeps each address — do NOT auto-merge), "
            "then re-run `alembic upgrade head`."
        )

    # 2. Normalize legacy rows (no-op on already-lowercase data).
    bind.execute(
        sa.text(
            "UPDATE users SET email = lower(trim(email)) "
            "WHERE email <> lower(trim(email))"
        )
    )

    # 3. The backstop index (idempotent; fresh DBs have it from the model).
    if not _has_index(TABLE, INDEX):
        op.create_index(
            INDEX, TABLE, [sa.text("lower(email)")], unique=True,
        )


def downgrade() -> None:
    if _has_index(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    # Deliberately no email de-normalization: lowercase data stays valid.
