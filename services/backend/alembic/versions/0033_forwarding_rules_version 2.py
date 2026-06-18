"""Add optimistic-locking version column to forwarding_rules.

The SQLAlchemy model has carried ``version = Column(Integer, default=1,
nullable=False)`` since the ForwardingRule v2 refactor, but no migration
was ever generated, so prod raises UndefinedColumnError on GET
/api/v1/forwarding/rules.

Additive, single column. server_default='1' is required because NOT NULL
on an existing (possibly non-empty) table needs a default at ALTER time;
the model-side default=1 only fires on Python INSERTs.

batch_alter_table is used for SQLite compat, matching the convention of
recent migrations (0027, 0032).

Revision ID: 0033
Revises: 0032
Create Date: 2026-04-24
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("forwarding_rules") as batch_op:
        batch_op.add_column(
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("forwarding_rules") as batch_op:
        batch_op.drop_column("version")
