"""Add users.account_type ('individual' | 'merchant').

Required field, no application-level default — every new signup must supply
one of the two allowed values (enforced by the Pydantic schema + a DB CHECK
constraint). The migration adds the column with a temporary server_default so
existing rows backfill to 'individual', then DROPS the server_default so the
column carries no default going forward (matches "required, no default").

batch_alter_table per SQLite test compat (convention 0033-0036).

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the column NOT NULL with a temporary server_default so existing rows
    # backfill to 'individual'. Add a CHECK constraint restricting the value to
    # the two allowed account types (portable across PostgreSQL and SQLite).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "account_type",
                sa.String(20),
                nullable=False,
                server_default="individual",
            )
        )
        batch_op.create_check_constraint(
            "ck_users_account_type",
            "account_type IN ('individual', 'merchant')",
        )

    # Drop the server_default: future inserts must supply account_type
    # explicitly (the app always does). Existing rows keep their backfilled
    # value. Uses batch mode so SQLite rebuilds the table without the default.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("account_type", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_account_type", type_="check")
        batch_op.drop_column("account_type")
