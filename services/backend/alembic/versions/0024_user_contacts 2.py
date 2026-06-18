"""Create user_contacts table for server-side address book.

Additive — one new table, FK to users.id ON DELETE CASCADE. Idempotent inserts
via UNIQUE(user_id, address) tolerate duplicate emits (event-bus listener,
bulk-import replays on login).

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_contacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()") if _is_postgres() else None,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tx_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB() if _is_postgres() else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "address", name="uq_user_contact_address"
        ),
    )
    op.create_index(
        "idx_user_contacts_user_id", "user_contacts", ["user_id"]
    )
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_user_contacts_last_used "
            "ON user_contacts(user_id, last_used_at DESC NULLS LAST)"
        )
    else:
        op.create_index(
            "idx_user_contacts_last_used",
            "user_contacts",
            ["user_id", "last_used_at"],
        )
    op.create_index(
        "idx_user_contacts_label",
        "user_contacts",
        ["user_id", "label"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_contacts_label", table_name="user_contacts")
    op.drop_index("idx_user_contacts_last_used", table_name="user_contacts")
    op.drop_index("idx_user_contacts_user_id", table_name="user_contacts")
    op.drop_table("user_contacts")
