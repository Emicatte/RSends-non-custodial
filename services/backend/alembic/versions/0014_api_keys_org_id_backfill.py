"""api_keys.org_id: backfill legacy keys + NOT NULL — org is the key's tenant.

Merchant login is email+password only and the wallet-auth web surface is
retired; 0011 added `org_id` (nullable) for session-minted keys but every
wallet-minted key still has org_id NULL and resolves purely via
`owner_address`. This migration completes the key-surface slice of the
"re-key tenancy on org_id" follow-up: every api_key row gets its org, and the
column becomes NOT NULL so a NULL-org key can never exist again (the legacy
generate route now stamps org_id fail-closed in the same change).

Backfill mapping mirrors the owner-identity precedence:
  1. active `user_wallets` link (lower(address), unlinked_at IS NULL) → org;
  2. else `organizations.settlement_wallet` (lower-matched) → org.

Safe on populated databases (0007 pattern): if ANY key maps to zero or to
more than one org, REPORT AND STOP before writing anything — never guess key
ownership (a wrong org would silently re-tenant a live credential). Resolve
the listed keys manually, then re-run. Take a DB dump before applying.

Downgrade drops only the NOT NULL — backfilled org values are correct data
and stay.

Revision ID: 0014_api_keys_org_id_backfill
Revises: 0013_intent_split_recipients
Create Date: 2026-07-18
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(): tests import this
# module for `backfill_org_ids`, and the project's local `alembic/` package
# shadows the installed library outside the alembic CLI runtime.

# revision identifiers, used by Alembic.
revision = "0014_api_keys_org_id_backfill"
down_revision = "0013_intent_split_recipients"
branch_labels = None
depends_on = None


def _candidate_orgs(bind, owner: str) -> list[str]:
    """Distinct org ids the owner wallet maps to, resolver precedence:
    active user_wallets link first; settlement_wallet only as fallback."""
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT CAST(org_id AS VARCHAR) FROM user_wallets "
            "WHERE lower(address) = :owner AND unlinked_at IS NULL"
        ),
        {"owner": owner},
    ).fetchall()
    if rows:
        return [r[0] for r in rows]
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT CAST(id AS VARCHAR) FROM organizations "
            "WHERE lower(settlement_wallet) = :owner"
        ),
        {"owner": owner},
    ).fetchall()
    return [r[0] for r in rows]


def backfill_org_ids(bind) -> None:
    """Assign an org to every api_key with org_id NULL, or raise before
    writing anything. Importable so tests can pin the exact behavior."""
    null_keys = bind.execute(
        sa.text(
            "SELECT id, lower(owner_address) FROM api_keys "
            "WHERE org_id IS NULL ORDER BY id"
        )
    ).fetchall()
    if not null_keys:
        return

    resolved: list[tuple[int, str]] = []
    problems: list[str] = []
    for key_id, owner in null_keys:
        candidates = _candidate_orgs(bind, owner)
        if len(candidates) == 1:
            resolved.append((key_id, candidates[0]))
        elif not candidates:
            problems.append(f"api_key id={key_id} owner={owner}: no org found")
        else:
            problems.append(
                f"api_key id={key_id} owner={owner}: ambiguous "
                f"({', '.join(sorted(candidates))})"
            )

    if problems:
        raise RuntimeError(
            f"Cannot apply {revision}: {len(problems)} api_key row(s) cannot "
            "be mapped to exactly one organization — never guess key "
            "ownership. Fix manually (set api_keys.org_id or revoke+delete "
            "the row), then re-run `alembic upgrade head`. Details: "
            + "; ".join(problems)
        )

    for key_id, org_id in resolved:
        bind.execute(
            sa.text("UPDATE api_keys SET org_id = :org WHERE id = :id"),
            {"org": org_id, "id": key_id},
        )


def _org_id_nullable(bind) -> bool:
    cols = sa.inspect(bind).get_columns("api_keys")
    return next(c for c in cols if c["name"] == "org_id")["nullable"]


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()
    backfill_org_ids(bind)

    if _org_id_nullable(bind):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.alter_column(
                    "org_id", existing_type=sa.String(36), nullable=False
                )
        else:
            op.alter_column(
                "api_keys", "org_id", existing_type=sa.String(36), nullable=False
            )


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()
    if not _org_id_nullable(bind):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.alter_column(
                    "org_id", existing_type=sa.String(36), nullable=True
                )
        else:
            op.alter_column(
                "api_keys", "org_id", existing_type=sa.String(36), nullable=True
            )
    # No data reversal: backfilled org linkage is correct in both schemas.
