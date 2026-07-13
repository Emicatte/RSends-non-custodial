"""Merchant approval state on organizations + drop orphan OAuth columns.

Two pieces:

1. organizations.approval_status ('pending_approval' | 'approved' | 'declined')
   plus decision metadata (requested/decided timestamps, decided_by, decline
   reason). The column is added with server_default='approved' — that IS the
   backfill: every PRE-EXISTING org keeps working (grandfathering; nobody
   already live is locked out by the new gate) — and the default is then
   DROPPED so the migrated schema matches a from-scratch create_all build
   (env.py runs compare_server_default=True; the ORM carries a Python-side
   default only, and org_service stamps fresh orgs 'pending_approval'
   explicitly).

2. Drop users.google_sub / github_sub / github_username — orphans of the
   social-login removal (PR #25). They were only ever materialized by
   create_all (no migration created them), so every DROP is existence-guarded:
   on a database built from migrations after the model change they simply
   don't exist. Production verified: zero rows with either sub set.

Idempotent: each piece is applied only if missing/present, mirroring 0009.

Revision ID: 0010_org_approval
Revises: 0009_onboarding
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0010_org_approval"
down_revision = "0009_onboarding"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return any(col["name"] == column for col in _inspector().get_columns(table))


def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in _inspector().get_indexes(table))


_OAUTH_COLUMNS = ("google_sub", "github_sub", "github_username")
_OAUTH_INDEXES = {
    "google_sub": "ix_users_google_sub",
    "github_sub": "ix_users_github_sub",
}


def upgrade() -> None:
    # ── 1. Approval state ─────────────────────────────────────────
    if not _has_column("organizations", "approval_status"):
        # server_default 'approved' IS the backfill for existing rows…
        op.add_column(
            "organizations",
            sa.Column(
                "approval_status",
                sa.Text(),
                nullable=False,
                server_default="approved",
            ),
        )
        # …then drop it: fresh rows get 'pending_approval' from the ORM, and
        # non-ORM inserts must choose explicitly. batch_alter_table: plain
        # ALTER on Postgres, table-recreate on SQLite.
        with op.batch_alter_table("organizations") as batch:
            batch.alter_column(
                "approval_status",
                server_default=None,
                existing_type=sa.Text(),
                existing_nullable=False,
            )
    for name, coltype in (
        ("approval_requested_at", sa.DateTime(timezone=True)),
        ("approval_decided_at", sa.DateTime(timezone=True)),
        ("approval_decided_by", sa.Text()),
        ("decline_reason", sa.Text()),
    ):
        if not _has_column("organizations", name):
            op.add_column("organizations", sa.Column(name, coltype, nullable=True))

    # ── 2. Orphan OAuth columns ───────────────────────────────────
    for column in _OAUTH_COLUMNS:
        index_name = _OAUTH_INDEXES.get(column)
        if index_name and _has_index("users", index_name):
            op.drop_index(index_name, table_name="users")
        if _has_column("users", column):
            op.drop_column("users", column)


def downgrade() -> None:
    for column in _OAUTH_COLUMNS:
        if not _has_column("users", column):
            op.add_column("users", sa.Column(column, sa.Text(), nullable=True))
            index_name = _OAUTH_INDEXES.get(column)
            if index_name:
                op.create_index(index_name, "users", [column], unique=True)

    for column in (
        "decline_reason",
        "approval_decided_by",
        "approval_decided_at",
        "approval_requested_at",
        "approval_status",
    ):
        if _has_column("organizations", column):
            op.drop_column("organizations", column)
