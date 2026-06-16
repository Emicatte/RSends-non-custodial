"""merchant_profiles — anagrafica di fatturazione B2B (Step 1/3).

Additiva, expand-phase: nuova tabella, nessun drop/rename, backward-compatible.
Ancora = owner_address (wallet 42-char), chiave di join verso payment_intents.merchant_id.

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: Union[str, None] = "0038"
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
        "merchant_profiles",
        sa.Column("id", uuid_col, primary_key=True,
                  server_default=uuid_default, nullable=False),
        sa.Column("owner_address", sa.String(42), nullable=False),
        sa.Column("billing_legal_name", sa.Text(), nullable=True),
        sa.Column("billing_vat_number", sa.Text(), nullable=True),
        sa.Column("billing_tax_code", sa.Text(), nullable=True),
        sa.Column("billing_address_line", sa.Text(), nullable=True),
        sa.Column("billing_city", sa.Text(), nullable=True),
        sa.Column("billing_postal_code", sa.Text(), nullable=True),
        sa.Column("billing_country", sa.Text(), nullable=True),
        sa.Column("billing_email", sa.Text(), nullable=True),
        sa.Column("billing_pec", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("metadata", json_col, nullable=True),
    )
    op.create_index(
        "ix_merchant_profiles_owner_address",
        "merchant_profiles",
        ["owner_address"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_profiles_owner_address", table_name="merchant_profiles")
    op.drop_table("merchant_profiles")
