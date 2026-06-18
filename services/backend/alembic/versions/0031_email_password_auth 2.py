"""Add email+password auth fields + verification/reset tokens tables.

Revision ID: 0031
Revises: 0030
Create Date: 2026-04-22

Additive: zero breaking changes to Google OAuth flow.

users (ALTER):
- password_hash, password_set_at, email_verified_at  (NEW — nullable)
- google_sub  (ALTER: NOT NULL -> NULL so email-only signups are possible;
  the UNIQUE constraint stays — PostgreSQL UNIQUE allows multiple NULLs)
- email_verified already exists from migration 0021 — we only backfill TRUE
  for users with google_sub (implicit verification from Google).

New tables:
- email_verification_tokens  (24h TTL)
- password_reset_tokens      (1h TTL)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36)
    uuid_default = sa.text("gen_random_uuid()") if _is_postgres() else None

    # ===== users: 3 new columns + relax google_sub NOT NULL =====
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(128), nullable=True))
        batch_op.add_column(sa.Column("password_set_at", sa.TIMESTAMP(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("email_verified_at", sa.TIMESTAMP(timezone=True), nullable=True))
        batch_op.alter_column("google_sub", existing_type=sa.Text(), nullable=True)

    # Backfill: existing users with google_sub are implicitly verified.
    # Idempotent: only promotes rows that were false.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE users
            SET email_verified = TRUE,
                email_verified_at = COALESCE(created_at, NOW())
            WHERE google_sub IS NOT NULL
              AND email_verified = FALSE
            """
        )
    )

    # ===== email_verification_tokens =====
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", uuid_type, server_default=uuid_default, primary_key=True),
        sa.Column(
            "user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("email_at_issue", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ip_at_issue", sa.String(45), nullable=True),
    )
    op.create_index(
        "uq_email_verification_tokens_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_email_verification_tokens_user",
        "email_verification_tokens",
        ["user_id"],
    )
    if _is_postgres():
        op.create_index(
            "ix_email_verification_tokens_active",
            "email_verification_tokens",
            ["user_id"],
            postgresql_where=sa.text("used_at IS NULL"),
        )
    else:
        op.create_index(
            "ix_email_verification_tokens_active",
            "email_verification_tokens",
            ["user_id"],
            sqlite_where=sa.text("used_at IS NULL"),
        )

    # ===== password_reset_tokens =====
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", uuid_type, server_default=uuid_default, primary_key=True),
        sa.Column(
            "user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ip_at_issue", sa.String(45), nullable=True),
        sa.Column("ip_at_use", sa.String(45), nullable=True),
    )
    op.create_index(
        "uq_password_reset_tokens_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_password_reset_tokens_user",
        "password_reset_tokens",
        ["user_id"],
    )


def downgrade() -> None:
    # Drop token tables first (FK to users).
    op.drop_index("ix_password_reset_tokens_user", table_name="password_reset_tokens")
    op.drop_index("uq_password_reset_tokens_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    try:
        op.drop_index("ix_email_verification_tokens_active", table_name="email_verification_tokens")
    except Exception:
        pass
    op.drop_index("ix_email_verification_tokens_user", table_name="email_verification_tokens")
    op.drop_index("uq_email_verification_tokens_hash", table_name="email_verification_tokens")
    op.drop_table("email_verification_tokens")

    # Restore users columns + re-tighten google_sub.
    # Safety: cannot set NOT NULL if any email-only users exist. We check first.
    conn = op.get_bind()
    null_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE google_sub IS NULL")
    ).scalar_one()

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email_verified_at")
        batch_op.drop_column("password_set_at")
        batch_op.drop_column("password_hash")
        if null_count == 0:
            batch_op.alter_column("google_sub", existing_type=sa.Text(), nullable=False)
        # else: leave google_sub nullable; downgrading with email-only users
        # present would otherwise violate NOT NULL. Manual cleanup required
        # before a true rollback to the pre-0031 schema.
