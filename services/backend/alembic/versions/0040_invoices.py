"""invoices + invoice_counters — fattura aggregata commissioni (Step 3/3).

Additiva, expand-phase: due nuove tabelle, nessun drop/rename, backward-compatible.
- invoices: fattura emessa, ancorata a owner_address (== payment_intents.merchant_id).
- invoice_counters: contatore progressivo per-anno per la numerazione FAT-{anno}-{seq:06d}
  (progressività atomica gap-free garantita nel service via SELECT ... FOR UPDATE).

Revision ID: 0040
Revises: 0039
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()
    uuid_col = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    uuid_default = sa.text("gen_random_uuid()") if is_pg else None
    json_col = postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()

    op.create_table(
        "invoices",
        sa.Column("id", uuid_col, primary_key=True,
                  server_default=uuid_default, nullable=False),
        # NULL finché draft: numero assegnato solo all'emissione (vedi invoice_service).
        sa.Column("invoice_number", sa.String(32), nullable=True),
        sa.Column("owner_address", sa.String(42), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tx_count", sa.Integer(), nullable=False),
        sa.Column("unit_price_eur", sa.Numeric(28, 18), nullable=False),
        sa.Column("subtotal_eur", sa.Numeric(28, 18), nullable=False),
        # Blocco IVA/regime PARAMETRICO (nullable).
        sa.Column("tax_regime", sa.String(64), nullable=True),
        sa.Column("tax_rate", sa.Numeric(9, 6), nullable=True),
        sa.Column("tax_amount_eur", sa.Numeric(28, 18), nullable=True),
        sa.Column("tax_note", sa.Text(), nullable=True),
        sa.Column("total_eur", sa.Numeric(28, 18), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("snapshot_issuer", json_col, nullable=True),
        sa.Column("snapshot_client", json_col, nullable=True),
        sa.UniqueConstraint(
            "owner_address", "period_start", "period_end",
            name="uq_invoices_owner_period",
        ),
    )
    op.create_index(
        "ix_invoices_number", "invoices", ["invoice_number"], unique=True
    )
    op.create_index(
        "ix_invoices_owner_address", "invoices", ["owner_address"]
    )
    op.create_index(
        "ix_invoices_owner_created", "invoices", ["owner_address", "created_at"]
    )

    op.create_table(
        "invoice_counters",
        sa.Column("year", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("invoice_counters")
    op.drop_index("ix_invoices_owner_created", table_name="invoices")
    op.drop_index("ix_invoices_owner_address", table_name="invoices")
    op.drop_index("ix_invoices_number", table_name="invoices")
    op.drop_table("invoices")
