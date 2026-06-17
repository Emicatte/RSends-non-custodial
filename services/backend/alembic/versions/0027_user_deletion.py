"""GDPR soft-delete columns on `users` + partial index for the cron scan.

Adds three nullable columns:
- deletion_requested_at: when the user first asked to delete
- deletion_scheduled_for: cutoff after which the cron hard-deletes
- deletion_reason: optional free-text reason (≤500 chars)

Plus a partial index on `deletion_scheduled_for WHERE IS NOT NULL` so the
daily cron can scan pending deletions in O(N_pending) rather than O(N_users).

Dual-mode (Postgres in prod, SQLite in tests): mirrors 0023/0024/0025/0026.
SQLite ≥3.8 supports partial indexes via `sqlite_where`.

Uses batch_alter_table for SQLite compat on add_column / drop_column.

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "deletion_requested_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "deletion_scheduled_for",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("deletion_reason", sa.Text(), nullable=True)
        )

    op.create_index(
        "idx_users_pending_deletion",
        "users",
        ["deletion_scheduled_for"],
        postgresql_where=sa.text("deletion_scheduled_for IS NOT NULL"),
        sqlite_where=sa.text("deletion_scheduled_for IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_users_pending_deletion", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("deletion_reason")
        batch_op.drop_column("deletion_scheduled_for")
        batch_op.drop_column("deletion_requested_at")
