"""Create signing_audit_log table for oracle signature forensics.

Immutable append-only table — records every oracle signing request
(approved or denied) for compliance auditing and anomaly detection.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signing_audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Request context
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        # Signature parameters
        sa.Column("signer_address", sa.String(42), nullable=False),
        sa.Column("chain_id", sa.Integer, nullable=False),
        sa.Column("sender", sa.String(42), nullable=False),
        sa.Column("recipient", sa.String(42), nullable=False),
        sa.Column("token_in", sa.String(42), nullable=False),
        sa.Column("amount_in_wei", sa.String(78), nullable=False),
        sa.Column("nonce", sa.String(66), nullable=False),
        sa.Column("deadline", sa.BigInteger, nullable=False),
        # Result
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("denial_reason", sa.Text, nullable=True),
        sa.Column("risk_score", sa.Integer, nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
    )

    # Indexes for common query patterns
    op.create_index("ix_signing_audit_created_at", "signing_audit_log", ["created_at"])
    op.create_index("ix_signing_audit_sender", "signing_audit_log", ["sender"])
    op.create_index("ix_signing_audit_nonce", "signing_audit_log", ["nonce"], unique=True)
    op.create_index(
        "ix_signing_audit_chain_ts",
        "signing_audit_log",
        ["chain_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signing_audit_chain_ts", table_name="signing_audit_log")
    op.drop_index("ix_signing_audit_nonce", table_name="signing_audit_log")
    op.drop_index("ix_signing_audit_sender", table_name="signing_audit_log")
    op.drop_index("ix_signing_audit_created_at", table_name="signing_audit_log")
    op.drop_table("signing_audit_log")
