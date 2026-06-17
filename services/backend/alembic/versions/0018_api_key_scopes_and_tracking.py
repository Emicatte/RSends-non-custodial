"""Add scope, environment, rate limits, and usage tracking to api_keys.

Additive migration — adds nullable columns with server defaults, then backfills.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("scope", sa.String(16), nullable=True, server_default="write"))
    op.add_column("api_keys", sa.Column("environment", sa.String(8), nullable=True, server_default="live"))
    op.add_column("api_keys", sa.Column("rate_limit_rpm", sa.Integer(), nullable=True, server_default="100"))
    op.add_column("api_keys", sa.Column("total_requests", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("api_keys", sa.Column("total_intents_created", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("api_keys", sa.Column("total_volume_usd", sa.String(32), nullable=True, server_default="0"))
    op.add_column("api_keys", sa.Column("monthly_intent_limit", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("api_keys", sa.Column("monthly_volume_limit_usd", sa.String(32), nullable=True, server_default="0"))

    # Backfill existing keys: admin scope, live environment
    op.execute("UPDATE api_keys SET scope = 'admin' WHERE scope IS NULL")
    op.execute("UPDATE api_keys SET environment = 'live' WHERE environment IS NULL")
    op.execute("UPDATE api_keys SET rate_limit_rpm = 100 WHERE rate_limit_rpm IS NULL")
    op.execute("UPDATE api_keys SET total_requests = 0 WHERE total_requests IS NULL")
    op.execute("UPDATE api_keys SET total_intents_created = 0 WHERE total_intents_created IS NULL")
    op.execute("UPDATE api_keys SET total_volume_usd = '0' WHERE total_volume_usd IS NULL")
    op.execute("UPDATE api_keys SET monthly_intent_limit = 0 WHERE monthly_intent_limit IS NULL")
    op.execute("UPDATE api_keys SET monthly_volume_limit_usd = '0' WHERE monthly_volume_limit_usd IS NULL")

    op.create_index("ix_api_keys_env", "api_keys", ["environment"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_env", table_name="api_keys")
    op.drop_column("api_keys", "monthly_volume_limit_usd")
    op.drop_column("api_keys", "monthly_intent_limit")
    op.drop_column("api_keys", "total_volume_usd")
    op.drop_column("api_keys", "total_intents_created")
    op.drop_column("api_keys", "total_requests")
    op.drop_column("api_keys", "rate_limit_rpm")
    op.drop_column("api_keys", "environment")
    op.drop_column("api_keys", "scope")
