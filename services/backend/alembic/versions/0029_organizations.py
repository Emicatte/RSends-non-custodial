"""Organizations + memberships + org_invites + users.active_org_id.

Fase 2 core — introduces first-class Organizations without migrating any
existing user-scoped resource. Prompt 11 will migrate api_keys + wallets
to org-scope; other user-scoped tables (routes, tx, contacts, notifications)
stay user-scoped forever.

Schema highlights
-----------------
- organizations: owner_user_id FK users.id ON DELETE RESTRICT (cannot delete
  a user that owns an org until ownership is transferred / org is deleted).
  slug unique, lowercase, URL-safe. `plan='free'` v1 (room for future plans).
  is_personal flag = auto-created org for each new user.
- memberships: many-to-many user↔org. Unique (user_id, org_id).
  role ∈ {admin, operator, viewer}. ON DELETE CASCADE on both sides.
  invited_by_user_id FK users.id ON DELETE SET NULL (preserve inviter trace
  when inviter's account is deleted).
- org_invites: magic-link invite flow. Token hashed SHA-256 (unique index).
  Partial unique index enforces at most one pending invite per (org, email).
  status ∈ {pending, accepted, declined, expired, revoked}. 7-day TTL.
- users.active_org_id: nullable FK ON DELETE SET NULL — lets user's "current"
  org survive the deletion of an org they have joined (they just land
  without an active org and re-pick at UI level).

Dual-mode (Postgres in prod, SQLite in tests): mirrors 0026/0027/0028.

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    is_pg = _is_postgres()

    uuid_col = lambda: postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    uuid_default = sa.text("gen_random_uuid()") if is_pg else None
    json_col = lambda: (
        postgresql.JSONB(astext_type=sa.Text()) if is_pg else sa.JSON()
    )
    empty_object_default = (
        sa.text("'{}'::jsonb") if is_pg else sa.text("'{}'")
    )

    # ═══ organizations ═══════════════════════════════════════════
    op.create_table(
        "organizations",
        sa.Column(
            "id",
            uuid_col(),
            primary_key=True,
            server_default=uuid_default,
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "owner_user_id",
            uuid_col(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_personal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "plan",
            sa.Text(),
            nullable=False,
            server_default="free",
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extra_metadata",
            json_col(),
            nullable=False,
            server_default=empty_object_default,
        ),
    )
    op.create_index(
        "ix_organizations_slug", "organizations", ["slug"], unique=True
    )
    op.create_index(
        "ix_organizations_owner", "organizations", ["owner_user_id"]
    )

    # ═══ memberships ═════════════════════════════════════════════
    op.create_table(
        "memberships",
        sa.Column(
            "id",
            uuid_col(),
            primary_key=True,
            server_default=uuid_default,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            uuid_col(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            uuid_col(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "invited_by_user_id",
            uuid_col(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "joined_at",
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
        sa.UniqueConstraint("user_id", "org_id", name="uq_memberships_user_org"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"])
    op.create_index("ix_memberships_org", "memberships", ["org_id"])

    # ═══ org_invites ═════════════════════════════════════════════
    op.create_table(
        "org_invites",
        sa.Column(
            "id",
            uuid_col(),
            primary_key=True,
            server_default=uuid_default,
            nullable=False,
        ),
        sa.Column(
            "org_id",
            uuid_col(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column(
            "invited_by_user_id",
            uuid_col(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "accepted_by_user_id",
            uuid_col(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_org_invites_token",
        "org_invites",
        ["token_hash"],
        unique=True,
    )
    op.create_index("ix_org_invites_org", "org_invites", ["org_id"])
    op.create_index(
        "ix_org_invites_email_active", "org_invites", ["email"]
    )

    # Partial unique: at most one pending invite per (org, email).
    op.create_index(
        "uq_org_invites_one_pending_per_email",
        "org_invites",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )

    # ═══ users.active_org_id ═════════════════════════════════════
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("active_org_id", uuid_col(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_users_active_org",
            "organizations",
            ["active_org_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_active_org", type_="foreignkey")
        batch_op.drop_column("active_org_id")

    op.drop_index(
        "uq_org_invites_one_pending_per_email", table_name="org_invites"
    )
    op.drop_index("ix_org_invites_email_active", table_name="org_invites")
    op.drop_index("ix_org_invites_org", table_name="org_invites")
    op.drop_index("ix_org_invites_token", table_name="org_invites")
    op.drop_table("org_invites")

    op.drop_index("ix_memberships_org", table_name="memberships")
    op.drop_index("ix_memberships_user", table_name="memberships")
    op.drop_table("memberships")

    op.drop_index("ix_organizations_owner", table_name="organizations")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
