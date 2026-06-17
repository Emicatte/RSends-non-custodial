"""Create kms_audit_log table.

Additive migration — does not touch existing tables.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kms_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("key_id", sa.String(256), nullable=False),
        sa.Column("operation", sa.String(50), nullable=False),
        sa.Column("chain_id", sa.Integer, nullable=True),
        sa.Column("context", sa.JSON, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_kms_audit_created_at", "kms_audit_log", ["created_at"])
    op.create_index("ix_kms_audit_key_id", "kms_audit_log", ["key_id"])


def downgrade() -> None:
    op.drop_index("ix_kms_audit_key_id", table_name="kms_audit_log")
    op.drop_index("ix_kms_audit_created_at", table_name="kms_audit_log")
    op.drop_table("kms_audit_log")
