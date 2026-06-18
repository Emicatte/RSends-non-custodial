"""Create users, user_sessions, auth_audit_log for Google OAuth login.

Foundation for end-user authentication (separate from merchant API keys
and EIP-191 wallet auth). Additive only — touches no existing table.

- users: upsert keyed by google_sub (stable Google identifier)
- user_sessions: DB backup of Redis-authoritative sessions (audit/forensics)
- auth_audit_log: immutable append-only event stream (login/logout/refresh/
  rotation/reuse-detection/rate-limit-exceeded)
- On PostgreSQL a BEFORE UPDATE/DELETE trigger enforces audit_log
  immutability at the DB layer. Skipped on SQLite (test-only dialect).

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────
    if _is_postgres():
        op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()") if _is_postgres() else None,
            nullable=False,
        ),
        sa.Column("google_sub", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
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
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_login_ip",
            postgresql.INET() if _is_postgres() else sa.String(45),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column(
            "metadata_json",
            postgresql.JSONB() if _is_postgres() else sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb") if _is_postgres() else sa.text("'{}'"),
        ),
    )
    op.create_index("idx_users_google_sub", "users", ["google_sub"])
    op.create_index("idx_users_email", "users", ["email"])
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_users_status_non_active "
            "ON users(status) WHERE status != 'active'"
        )
    else:
        op.create_index("idx_users_status_non_active", "users", ["status"])

    # ── user_sessions ─────────────────────────────────────
    op.create_table(
        "user_sessions",
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
        sa.Column("session_id", sa.Text(), nullable=False, unique=True),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "ip_address",
            postgresql.INET() if _is_postgres() else sa.String(45),
            nullable=True,
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_fingerprint", sa.Text(), nullable=True),
    )
    op.create_index("idx_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("idx_sessions_session_id", "user_sessions", ["session_id"])
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_sessions_expires_at "
            "ON user_sessions(expires_at) WHERE revoked_at IS NULL"
        )
    else:
        op.create_index("idx_sessions_expires_at", "user_sessions", ["expires_at"])

    # ── auth_audit_log ────────────────────────────────────
    op.create_table(
        "auth_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            nullable=True,
        ),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column(
            "ip_address",
            postgresql.INET() if _is_postgres() else sa.String(45),
            nullable=True,
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("google_sub", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column(
            "details",
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
    )
    op.create_index("idx_audit_user_id", "auth_audit_log", ["user_id"])
    op.create_index("idx_audit_event_type", "auth_audit_log", ["event_type"])
    op.create_index(
        "idx_audit_created_at",
        "auth_audit_log",
        [sa.text("created_at DESC")],
    )
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_audit_ip ON auth_audit_log(ip_address) "
            "WHERE event_type IN ('login_failure','rate_limit_exceeded','refresh_reuse_detected')"
        )
    else:
        op.create_index("idx_audit_ip", "auth_audit_log", ["ip_address"])

    # ── Immutability trigger (PostgreSQL only) ────────────
    if _is_postgres():
        op.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_auth_audit_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'auth_audit_log is immutable';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER auth_audit_no_update
            BEFORE UPDATE ON auth_audit_log
            FOR EACH ROW EXECUTE FUNCTION prevent_auth_audit_modification();
            """
        )
        op.execute(
            """
            CREATE TRIGGER auth_audit_no_delete
            BEFORE DELETE ON auth_audit_log
            FOR EACH ROW EXECUTE FUNCTION prevent_auth_audit_modification();
            """
        )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS auth_audit_no_delete ON auth_audit_log")
        op.execute("DROP TRIGGER IF EXISTS auth_audit_no_update ON auth_audit_log")
        op.execute("DROP FUNCTION IF EXISTS prevent_auth_audit_modification()")

    op.drop_index("idx_audit_ip", table_name="auth_audit_log")
    op.drop_index("idx_audit_created_at", table_name="auth_audit_log")
    op.drop_index("idx_audit_event_type", table_name="auth_audit_log")
    op.drop_index("idx_audit_user_id", table_name="auth_audit_log")
    op.drop_table("auth_audit_log")

    op.drop_index("idx_sessions_expires_at", table_name="user_sessions")
    op.drop_index("idx_sessions_session_id", table_name="user_sessions")
    op.drop_index("idx_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("idx_users_status_non_active", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_index("idx_users_google_sub", table_name="users")
    op.drop_table("users")
