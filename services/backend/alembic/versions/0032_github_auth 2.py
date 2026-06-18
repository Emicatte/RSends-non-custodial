"""Add GitHub OAuth fields to users.

Revision ID: 0032
Revises: 0031
Create Date: 2026-04-23

Additive: zero breaking changes. Mirror of google_sub nullable-unique pattern
established post-0031.

users (ALTER):
- github_sub: nullable TEXT, UNIQUE (multiple NULLs permitted on Postgres)
- github_username: nullable TEXT (display-only, non-unique)

No backfill: zero existing users have a GitHub identity yet.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("github_sub", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("github_username", sa.Text(), nullable=True))

    op.create_index(
        "ix_users_github_sub",
        "users",
        ["github_sub"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_github_sub", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("github_username")
        batch_op.drop_column("github_sub")
