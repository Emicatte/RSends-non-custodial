"""Make audit_logs.rule_id nullable with ON DELETE SET NULL.

Bug exposed by Phase A frontend refactor: deleting a forwarding_rule
that has audit_logs (e.g. from prior pause/resume/update) raises
ForeignKeyViolationError because the FK was created in 0002 without
ondelete (defaults to RESTRICT) and the column was NOT NULL.

DAC8 compliance requires audit retention, so SET NULL is preferred
over CASCADE: audit rows survive the parent delete with rule_id=NULL
and `old_values` JSON preserves the rule identity.

batch_alter_table for SQLite test compat (matches 0030/0033 pattern).

Revision ID: 0034
Revises: 0033
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.alter_column("rule_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint("audit_logs_rule_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "audit_logs_rule_id_fkey",
            "forwarding_rules",
            ["rule_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_constraint("audit_logs_rule_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key(
            "audit_logs_rule_id_fkey",
            "forwarding_rules",
            ["rule_id"],
            ["id"],
        )
        batch_op.alter_column("rule_id", existing_type=sa.Integer(), nullable=False)
