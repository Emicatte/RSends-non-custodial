"""Add owner_address to split_contracts (additive, nullable, backfilled).

Phase B-splits step 1/3: prepara il terreno per il fix C2 (split mutations
unauthenticated). Aggiunge owner_address derivato da master_wallet su tutte
le row esistenti. Il campo resta nullable in questa migration; verrà reso
NOT NULL in una migration successiva dopo backfill verificato.

Step 2/3 (commit separato): @require_wallet_auth + _verify_split_owner.
Step 3/3 (sessione futura, FE+BE coordinata): wallet signing in
useSplitContracts.ts.

batch_alter_table per SQLite test compat (convenzione 0033/0034).

Revision ID: 0035
Revises: 0034
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("split_contracts") as batch_op:
        batch_op.add_column(
            sa.Column("owner_address", sa.String(length=42), nullable=True)
        )
        batch_op.create_index(
            "ix_split_contracts_owner_address",
            ["owner_address"],
        )

    # Backfill: ogni row esistente eredita owner dal master_wallet (lowercase).
    # No-op effettivo in dev (0 row), corretto per staging/prod.
    op.execute(
        "UPDATE split_contracts "
        "SET owner_address = LOWER(master_wallet) "
        "WHERE owner_address IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("split_contracts") as batch_op:
        batch_op.drop_index("ix_split_contracts_owner_address")
        batch_op.drop_column("owner_address")
