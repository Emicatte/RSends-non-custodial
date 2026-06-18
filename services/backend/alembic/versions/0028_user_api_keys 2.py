"""User-scoped API keys (separate system from merchant api_keys).

Coexists with the merchant-scoped `api_keys` table (owner_address EVM) — zero
dependency, zero merge. `user_api_keys` authenticates user-session-owned
programmatic access; `org_id` is prepared nullable so Prompt 11 can migrate
these rows to org-scope once Organizations (Prompt 10) land.

Schema highlights
- user_id FK users.id ON DELETE CASCADE — mirrors every migration 0021-0027.
- key_prefix indexed for fast O(log n) lookup before bcrypt verify.
- key_hash unique — bcrypt v1 (cost=12), hash_version reserved for migrations.
- scopes stored as JSONB/JSON array; v1 scopes live in the Pydantic schema.
- Partial index `idx_user_api_keys_active_per_user` WHERE is_active AND
  revoked_at IS NULL — supports the server-enforced MAX_KEYS_PER_USER=5 cap
  in O(count-active) without scanning revoked rows.
- org_id indexed (Prompt 11 prep) but no FK — orgs table doesn't exist yet.

Dual-mode (Postgres in prod, SQLite in tests): mirrors 0026/0027.

Revision ID: 0028
Revises: 0027
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()

    op.create_table(
        "user_api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()") if is_pg else None,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Prompt 11 prep: no FK yet (orgs table doesn't exist).
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True) if is_pg else sa.String(36),
            nullable=True,
        ),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_prefix", sa.String(32), nullable=False),
        sa.Column("display_prefix", sa.String(48), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False),
        sa.Column(
            "hash_version",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "environment",
            sa.String(8),
            nullable=False,
            server_default="live",
        ),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb") if is_pg else sa.text("'[]'"),
        ),
        sa.Column(
            "rate_limit_rpm",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
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
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_ip", sa.String(45), nullable=True),
        sa.Column(
            "total_requests",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "extra_metadata",
            postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'"),
        ),
    )

    # Fast prefix lookup before bcrypt verify in verify_request_key.
    op.create_index(
        "ix_user_api_keys_prefix",
        "user_api_keys",
        ["key_prefix"],
    )

    # Defensive: two keys colliding on prefix is fine (bcrypt still disambiguates),
    # but two identical bcrypt hashes would be a catastrophic generator bug.
    # Using a unique index (not constraint) for SQLite compat — functionally
    # equivalent on Postgres.
    op.create_index(
        "uq_user_api_keys_hash",
        "user_api_keys",
        ["key_hash"],
        unique=True,
    )

    # "List my keys" query path.
    op.create_index(
        "idx_user_api_keys_user_id",
        "user_api_keys",
        ["user_id"],
    )

    # Prompt 11 prep — org-scoped lookups will need this.
    op.create_index(
        "idx_user_api_keys_org_id",
        "user_api_keys",
        ["org_id"],
    )

    # Server-enforce MAX_KEYS_PER_USER=5: scan only active rows per user.
    op.create_index(
        "idx_user_api_keys_active_per_user",
        "user_api_keys",
        ["user_id"],
        postgresql_where=sa.text("is_active = true AND revoked_at IS NULL"),
        sqlite_where=sa.text("is_active = 1 AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_api_keys_active_per_user", table_name="user_api_keys"
    )
    op.drop_index("idx_user_api_keys_org_id", table_name="user_api_keys")
    op.drop_index("idx_user_api_keys_user_id", table_name="user_api_keys")
    op.drop_index("uq_user_api_keys_hash", table_name="user_api_keys")
    op.drop_index("ix_user_api_keys_prefix", table_name="user_api_keys")
    op.drop_table("user_api_keys")
