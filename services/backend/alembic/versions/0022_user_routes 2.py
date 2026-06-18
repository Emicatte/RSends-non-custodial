"""Create user_routes table for persistent saved routing configurations.

Additive — one new table, FK to users.id ON DELETE CASCADE.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "user_routes",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "route_config",
            postgresql.JSONB() if _is_postgres() else sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
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
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "use_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_index("idx_user_routes_user_id", "user_routes", ["user_id"])
    if _is_postgres():
        op.execute(
            "CREATE INDEX idx_user_routes_favorite "
            "ON user_routes(user_id, is_favorite) WHERE is_favorite"
        )
    else:
        op.create_index(
            "idx_user_routes_favorite",
            "user_routes",
            ["user_id", "is_favorite"],
        )


def downgrade() -> None:
    op.drop_index("idx_user_routes_favorite", table_name="user_routes")
    op.drop_index("idx_user_routes_user_id", table_name="user_routes")
    op.drop_table("user_routes")
