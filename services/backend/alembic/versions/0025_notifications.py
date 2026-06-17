"""Notification preferences + known devices.

Adds two user-scoped tables:
- notification_preferences: opt-in flags per user; used today for the
  "login from new device" email (others are reserved for future Telegram
  migration and stay silent until wired up).
- known_devices: stores (user_id, fingerprint) pairs so the auth service
  can tell first-time logins from repeat ones. Fingerprint = sha256 of
  UA family + IP /24 subnet + user_id (computed in services/device_fingerprint).

Dual-mode migration (Postgres in prod, SQLite in tests): mirrors the
structure of 0023/0024.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True) if _is_postgres() else sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "email_login_new_device",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "telegram_tx_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "telegram_tx_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "telegram_price_alerts",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("telegram_chat_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "known_devices",
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
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("user_agent_snippet", sa.Text(), nullable=True),
        sa.Column("ip_first_seen", sa.Text(), nullable=True),
        sa.Column("ip_last_seen", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "login_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.UniqueConstraint(
            "user_id", "fingerprint", name="uq_known_devices_user_fp"
        ),
    )
    op.create_index(
        "idx_known_devices_user_id", "known_devices", ["user_id"]
    )
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_known_devices_last_seen "
            "ON known_devices(user_id, last_seen_at DESC NULLS LAST)"
        )
    else:
        op.create_index(
            "idx_known_devices_last_seen",
            "known_devices",
            ["user_id", "last_seen_at"],
        )


def downgrade() -> None:
    op.drop_index("idx_known_devices_last_seen", table_name="known_devices")
    op.drop_index("idx_known_devices_user_id", table_name="known_devices")
    op.drop_table("known_devices")
    op.drop_table("notification_preferences")
