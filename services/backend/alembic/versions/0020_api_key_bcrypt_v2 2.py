"""Add bcrypt v2 hashing columns alongside v1 SHA-256 for API keys.
Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "api_keys",
        sa.Column("display_prefix", sa.String(32), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("key_hash_v2", sa.String(128), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column("hash_version", sa.SmallInteger, nullable=False, server_default="1"),
    )
    # Backfill display_prefix from existing key_prefix (which stores "rsend_live_xxx...")
    op.execute("UPDATE api_keys SET display_prefix = key_prefix")
    # Widen key_prefix to hold raw 24-char lookup prefix for v2 keys.
    # SQLite does not enforce VARCHAR length and doesn't support ALTER COLUMN TYPE:
    # the widen is a no-op in SQLite, so we only run it on other dialects (Postgres prod).
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column(
            "api_keys",
            "key_prefix",
            type_=sa.String(32),
            existing_type=sa.String(24),
            existing_nullable=False,
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        op.alter_column(
            "api_keys",
            "key_prefix",
            type_=sa.String(24),
            existing_type=sa.String(32),
            existing_nullable=False,
        )
    op.drop_column("api_keys", "hash_version")
    op.drop_column("api_keys", "key_hash_v2")
    op.drop_column("api_keys", "display_prefix")