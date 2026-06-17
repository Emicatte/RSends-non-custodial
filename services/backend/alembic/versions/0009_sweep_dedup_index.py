"""Add composite index for sweep dedup (trigger_tx_hash + rule_id).

Prevents duplicate sweep_logs for the same incoming TX + rule combination.
Used by process_incoming_tx DB-level dedup check.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_sweep_trigger_rule",
        "sweep_logs",
        ["trigger_tx_hash", "rule_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sweep_trigger_rule", table_name="sweep_logs")
