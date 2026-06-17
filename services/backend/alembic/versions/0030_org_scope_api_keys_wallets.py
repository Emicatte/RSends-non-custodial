"""Migrate user_api_keys + user_wallets to org-scope (Fase 2 closeout).

Prompt 10 introduced `organizations`, `memberships`, and `users.active_org_id`.
This migration wires existing resources to the org layer:

Step 1 — Backfill personal orgs for any user that lacks `active_org_id` (can
         happen for pre-Prompt-10 users). Inline raw SQL, idempotent, slug-
         collision-safe.
Step 2 — `user_api_keys`: add `created_by_user_id` (nullable), populate
         `org_id` + `created_by_user_id` from `users.active_org_id`/`user_id`,
         verify no NULL org_id, add FKs, flip `org_id` to NOT NULL, rebuild
         the "active per {user → org}" partial index.
Step 3 — `user_wallets`: add `org_id` (nullable) + `created_by_user_id`
         (nullable), populate both, verify no NULL org_id, add FKs, flip
         `org_id` to NOT NULL, rescope partial unique indexes from user to
         org for `(chain_family, address)` and one-primary-per-(chain_family).

IDEMPOTENT: re-running is safe. Every step checks the current state.

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-22
"""

from __future__ import annotations

import logging
import re
import secrets
import uuid as uuid_module
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger(__name__)

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _slugify(text: str) -> str:
    base = _SLUG_UNSAFE.sub("-", (text or "").lower()).strip("-")
    return base[:50] or "workspace"


def _backfill_personal_orgs(conn) -> None:
    """For every non-deleted user without active_org_id, create a personal
    org + admin membership + set active_org_id. Idempotent: re-run safe.
    """
    is_pg = _is_postgres()

    rows = conn.execute(
        sa.text(
            """
            SELECT id, email, display_name
            FROM users
            WHERE active_org_id IS NULL
              AND deletion_scheduled_for IS NULL
            """
        )
    ).fetchall()

    for row in rows:
        user_id = str(row[0])
        email = row[1] or ""
        display = row[2] or (email.split("@")[0] if email else "My")

        # Already has personal org but active_org_id unset? Just wire it.
        existing = conn.execute(
            sa.text(
                """
                SELECT id FROM organizations
                WHERE owner_user_id = :uid
                  AND is_personal = TRUE
                  AND deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"uid": user_id},
        ).fetchone()

        if existing:
            org_id = str(existing[0])
        else:
            name = f"{display}'s workspace"[:100]
            slug_base = _slugify(display)
            slug = slug_base
            for _ in range(5):
                clash = conn.execute(
                    sa.text(
                        "SELECT 1 FROM organizations WHERE slug = :s LIMIT 1"
                    ),
                    {"s": slug},
                ).fetchone()
                if not clash:
                    break
                suffix = (
                    secrets.token_urlsafe(4)
                    .replace("_", "")
                    .replace("-", "")[:5]
                    .lower()
                )
                slug = f"{slug_base}-{suffix}" if suffix else f"{slug_base}-{secrets.token_hex(3)}"

            if is_pg:
                res = conn.execute(
                    sa.text(
                        """
                        INSERT INTO organizations (name, slug, owner_user_id, is_personal, plan)
                        VALUES (:n, :s, :uid, TRUE, 'free')
                        RETURNING id
                        """
                    ),
                    {"n": name, "s": slug, "uid": user_id},
                )
                org_id = str(res.fetchone()[0])
            else:
                org_id = str(uuid_module.uuid4())
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO organizations (id, name, slug, owner_user_id, is_personal, plan)
                        VALUES (:oid, :n, :s, :uid, 1, 'free')
                        """
                    ),
                    {"oid": org_id, "n": name, "s": slug, "uid": user_id},
                )

            # Admin membership
            if is_pg:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO memberships (user_id, org_id, role)
                        VALUES (:uid, :oid, 'admin')
                        """
                    ),
                    {"uid": user_id, "oid": org_id},
                )
            else:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO memberships (id, user_id, org_id, role)
                        VALUES (:mid, :uid, :oid, 'admin')
                        """
                    ),
                    {
                        "mid": str(uuid_module.uuid4()),
                        "uid": user_id,
                        "oid": org_id,
                    },
                )

        conn.execute(
            sa.text("UPDATE users SET active_org_id = :oid WHERE id = :uid"),
            {"oid": org_id, "uid": user_id},
        )
        log.info(
            "[0030] backfilled personal org %s for user %s", org_id, user_id
        )


def upgrade() -> None:
    conn = op.get_bind()
    is_pg = _is_postgres()
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)

    # ═══ Step 1: backfill personal orgs ═══════════════════════════════
    _backfill_personal_orgs(conn)

    # ═══ Step 2: user_api_keys ════════════════════════════════════════

    # 2.1 — add created_by_user_id (nullable for backfill)
    with op.batch_alter_table("user_api_keys") as batch_op:
        batch_op.add_column(
            sa.Column("created_by_user_id", uuid_type, nullable=True)
        )

    # 2.2 — populate org_id + created_by_user_id from users.active_org_id / user_id
    if is_pg:
        conn.execute(
            sa.text(
                """
                UPDATE user_api_keys AS k
                SET org_id = u.active_org_id,
                    created_by_user_id = u.id
                FROM users AS u
                WHERE k.user_id = u.id
                  AND (k.org_id IS NULL OR k.created_by_user_id IS NULL)
                """
            )
        )
    else:
        conn.execute(
            sa.text(
                """
                UPDATE user_api_keys
                SET org_id = (
                        SELECT active_org_id FROM users
                        WHERE users.id = user_api_keys.user_id
                    ),
                    created_by_user_id = user_api_keys.user_id
                WHERE org_id IS NULL OR created_by_user_id IS NULL
                """
            )
        )

    # 2.3 — sanity: no row left with NULL org_id
    remaining = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM user_api_keys WHERE org_id IS NULL"
        )
    ).scalar()
    if remaining and int(remaining) > 0:
        raise RuntimeError(
            f"[0030] {remaining} user_api_keys still have NULL org_id after backfill"
        )

    # 2.4 — flip NOT NULL + add FKs
    with op.batch_alter_table("user_api_keys") as batch_op:
        batch_op.alter_column("org_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_user_api_keys_org",
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_user_api_keys_created_by",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 2.5 — rescope "active-per-user" → "active-per-org" partial index
    op.drop_index(
        "idx_user_api_keys_active_per_user", table_name="user_api_keys"
    )
    op.create_index(
        "idx_user_api_keys_active_per_org",
        "user_api_keys",
        ["org_id"],
        postgresql_where=sa.text("is_active = true AND revoked_at IS NULL"),
        sqlite_where=sa.text("is_active = 1 AND revoked_at IS NULL"),
    )

    # ═══ Step 3: user_wallets ═════════════════════════════════════════

    # 3.1 — add org_id + created_by_user_id, both nullable for backfill
    with op.batch_alter_table("user_wallets") as batch_op:
        batch_op.add_column(sa.Column("org_id", uuid_type, nullable=True))
        batch_op.add_column(
            sa.Column("created_by_user_id", uuid_type, nullable=True)
        )

    # 3.2 — populate
    if is_pg:
        conn.execute(
            sa.text(
                """
                UPDATE user_wallets AS w
                SET org_id = u.active_org_id,
                    created_by_user_id = u.id
                FROM users AS u
                WHERE w.user_id = u.id
                  AND (w.org_id IS NULL OR w.created_by_user_id IS NULL)
                """
            )
        )
    else:
        conn.execute(
            sa.text(
                """
                UPDATE user_wallets
                SET org_id = (
                        SELECT active_org_id FROM users
                        WHERE users.id = user_wallets.user_id
                    ),
                    created_by_user_id = user_wallets.user_id
                WHERE org_id IS NULL OR created_by_user_id IS NULL
                """
            )
        )

    remaining = conn.execute(
        sa.text("SELECT COUNT(*) FROM user_wallets WHERE org_id IS NULL")
    ).scalar()
    if remaining and int(remaining) > 0:
        raise RuntimeError(
            f"[0030] {remaining} user_wallets still have NULL org_id after backfill"
        )

    # 3.3 — flip org_id NOT NULL + add FKs + index for org_id
    with op.batch_alter_table("user_wallets") as batch_op:
        batch_op.alter_column("org_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_user_wallets_org",
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_user_wallets_created_by",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        "idx_user_wallets_org_id", "user_wallets", ["org_id"]
    )

    # 3.4 — rescope uniqueness from user to org
    op.drop_index("uq_user_wallets_active", table_name="user_wallets")
    op.create_index(
        "uq_user_wallets_active_org",
        "user_wallets",
        ["org_id", "chain_family", "address"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
        sqlite_where=sa.text("unlinked_at IS NULL"),
    )

    op.drop_index(
        "uq_user_wallets_one_primary", table_name="user_wallets"
    )
    primary_kwargs = {
        "unique": True,
        "postgresql_where": sa.text(
            "is_primary = true AND unlinked_at IS NULL"
        ),
        "sqlite_where": sa.text("is_primary = 1 AND unlinked_at IS NULL"),
    }
    try:
        op.create_index(
            "uq_user_wallets_one_primary_org",
            "user_wallets",
            ["org_id", "chain_family"],
            postgresql_nulls_not_distinct=True,
            **primary_kwargs,
        )
    except TypeError:
        op.create_index(
            "uq_user_wallets_one_primary_org",
            "user_wallets",
            ["org_id", "chain_family"],
            **primary_kwargs,
        )

    # 3.5 — per-org "active lookup" (partial, for list queries scoped to org)
    op.create_index(
        "idx_user_wallets_active_per_org",
        "user_wallets",
        ["org_id"],
        postgresql_where=sa.text("unlinked_at IS NULL"),
        sqlite_where=sa.text("unlinked_at IS NULL"),
    )

    log.info("[0030] org-scope migration complete")


def downgrade() -> None:
    is_pg = _is_postgres()

    # ═══ user_wallets ═════════════════════════════════════════════════
    op.drop_index(
        "idx_user_wallets_active_per_org", table_name="user_wallets"
    )
    op.drop_index(
        "uq_user_wallets_one_primary_org", table_name="user_wallets"
    )
    op.drop_index("uq_user_wallets_active_org", table_name="user_wallets")
    op.drop_index("idx_user_wallets_org_id", table_name="user_wallets")

    # restore old user-scoped indexes
    op.create_index(
        "uq_user_wallets_active",
        "user_wallets",
        ["user_id", "chain_family", "address"],
        unique=True,
        postgresql_where=sa.text("unlinked_at IS NULL"),
        sqlite_where=sa.text("unlinked_at IS NULL"),
    )
    primary_kwargs = {
        "unique": True,
        "postgresql_where": sa.text(
            "is_primary = true AND unlinked_at IS NULL"
        ),
        "sqlite_where": sa.text("is_primary = 1 AND unlinked_at IS NULL"),
    }
    try:
        op.create_index(
            "uq_user_wallets_one_primary",
            "user_wallets",
            ["user_id", "chain_family"],
            postgresql_nulls_not_distinct=True,
            **primary_kwargs,
        )
    except TypeError:
        op.create_index(
            "uq_user_wallets_one_primary",
            "user_wallets",
            ["user_id", "chain_family"],
            **primary_kwargs,
        )

    with op.batch_alter_table("user_wallets") as batch_op:
        batch_op.drop_constraint(
            "fk_user_wallets_created_by", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_user_wallets_org", type_="foreignkey")
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("org_id")

    # ═══ user_api_keys ════════════════════════════════════════════════
    op.drop_index(
        "idx_user_api_keys_active_per_org", table_name="user_api_keys"
    )
    op.create_index(
        "idx_user_api_keys_active_per_user",
        "user_api_keys",
        ["user_id"],
        postgresql_where=sa.text("is_active = true AND revoked_at IS NULL"),
        sqlite_where=sa.text("is_active = 1 AND revoked_at IS NULL"),
    )

    with op.batch_alter_table("user_api_keys") as batch_op:
        batch_op.drop_constraint(
            "fk_user_api_keys_created_by", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_user_api_keys_org", type_="foreignkey")
        batch_op.drop_column("created_by_user_id")
        # Keep `org_id` column in place — it predates 0030 (added in 0028 as
        # nullable without FK). Revert it to that original state: drop NOT NULL.
        batch_op.alter_column("org_id", nullable=True)

    # Personal orgs backfilled in upgrade() are NOT reverted — they are
    # legitimate data after 0029 introduced Organizations. Nothing to undo.
