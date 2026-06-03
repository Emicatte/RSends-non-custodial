"""Unique constraint on split_executions (contract_id, source_tx_hash).

C1a — split double-pay idempotency gate. Concurrent webhook deliveries for the
same (contract, source TX) could each INSERT a SplitExecution and send a second
set of on-chain transfers (double payout). This unique constraint makes the
INSERT the atomic point of no return: the 2nd delivery fails with IntegrityError
BEFORE any TX is sent (handled in split_executor.execute() ->
DuplicateSplitExecution, returned as an idempotent duplicate by
split_webhook_bridge.maybe_execute_split).

Pre-dedup: drop any pre-existing duplicate rows (keep the lowest id per group)
so the constraint can be built. No-op on a clean dev DB (0 rows).

batch_alter_table per SQLite test compat (convenzione 0033-0035).

Revision ID: 0036
Revises: 0035
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pre-dedup so the unique index can be created. Keep the earliest id per
    # (contract_id, source_tx_hash). Portable across SQLite and PostgreSQL.
    op.execute(
        "DELETE FROM split_executions "
        "WHERE id NOT IN ("
        "  SELECT MIN(id) FROM split_executions "
        "  GROUP BY contract_id, source_tx_hash"
        ")"
    )
    with op.batch_alter_table("split_executions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_split_exec_contract_srctx",
            ["contract_id", "source_tx_hash"],
        )


def downgrade() -> None:
    with op.batch_alter_table("split_executions") as batch_op:
        batch_op.drop_constraint("uq_split_exec_contract_srctx", type_="unique")
