"""tx_intents — idempotenza a livello di broadcast on-chain.

Additiva, expand-phase: una sola NUOVA tabella, nessun drop/rename/alter di
tabelle esistenti → rolling-deploy safe (i worker vecchi la ignorano, i nuovi
la usano). Chiude la finestra crash-after-broadcast-before-commit per i path
di sweep (execute_single_sweep, sweep_deposit): l'intent viene persistito con
UNIQUE(idempotency_key) PRIMA di trasmettere; su retry il claim atomico
impedisce un secondo broadcast.

Revision ID: 0041
Revises: 0040
Create Date: 2026-06-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()
    uuid_col = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    uuid_default = sa.text("gen_random_uuid()") if is_pg else None

    op.create_table(
        "tx_intents",
        sa.Column("id", uuid_col, primary_key=True,
                  server_default=uuid_default, nullable=False),
        # Chiave deterministica: "<site>:<natural_id>" (es. standalone_sweep:42).
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("site", sa.String(32), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("from_address", sa.String(42), nullable=False),
        # Nonce pre-broadcast: àncora di riconciliazione contro la chain.
        sa.Column("nonce", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="broadcasting"),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("raw_tx", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_tx_intent_key"),
        sa.CheckConstraint(
            "status IN ('broadcasting','confirmed','failed')",
            name="ck_tx_intent_status",
        ),
    )
    op.create_index(
        "ix_tx_intent_status", "tx_intents", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_tx_intent_status", table_name="tx_intents")
    op.drop_table("tx_intents")
