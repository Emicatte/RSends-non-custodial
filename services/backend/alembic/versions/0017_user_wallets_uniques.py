"""Restore the two partial unique indexes on user_wallets.

They were created by migration 0026 (user-scoped) and re-scoped onto the org by
0030 Step 3.4. Both files were deleted when the chain was squashed into
0001_noncustodial_baseline, which builds the schema through
`Base.metadata.create_all` — and the UserWallet model carried no
`__table_args__`, so `create_all` never reproduced them. Confirmed against
production: `pg_indexes` for user_wallets holds only `user_wallets_pkey`,
`ix_user_wallets_org_id`, `ix_user_wallets_user_id`. The constraints are absent
from the live database, not merely from freshly provisioned ones.

  uq_user_wallets_active_org       UNIQUE (org_id, chain_family, address)
                                   WHERE unlinked_at IS NULL
  uq_user_wallets_one_primary_org  UNIQUE (org_id, chain_family)
                                   WHERE is_primary AND unlinked_at IS NULL

Definitions recovered verbatim from git history
(`git show 9a425616^:services/backend/alembic/versions/0030_org_scope_api_keys_wallets.py`),
not reconstructed from the names. The key is ORG-scoped: the same address in two
different orgs is legitimate and depended upon. The `WHERE unlinked_at IS NULL`
half is what makes unlink → relink work; the one-primary index is partial on
`is_primary` too, so an org still holds many active wallets.

Deliberate deviation: 0026/0030 also passed `postgresql_nulls_not_distinct=True`
on the one-primary index. It is a documented no-op today (both indexed columns
are NOT NULL) and renders DDL requiring PostgreSQL >= 15, so it is omitted
rather than pinning a server-version floor for no behavioural gain.

Why this matters beyond hygiene: with no constraint, one org can hold two active
primaries, and `owner_identity.resolve_owner_address` picks one with `.limit(1)`
and no ORDER BY — the tenant key a payment is attributed to becomes arbitrary
and may differ between requests. The `IntegrityError` → 409 handlers in
user_wallets_routes.py could never fire, so the application believed the
database was enforcing an invariant it was not.

PRE-FLIGHT: duplicate rows are REPORTED AND THE MIGRATION STOPS, following
0014/0016. Never delete, never merge, never coerce a wallet row — a duplicate
here is a tenancy incident to investigate by hand.

No CONCURRENTLY: env.py runs every migration inside one transaction
(MIGRATIONS.md:50-61), and the table is tiny.

Verify before running (both must return zero rows):
    SELECT org_id, chain_family, address, count(*) FROM user_wallets
    WHERE unlinked_at IS NULL
    GROUP BY org_id, chain_family, address HAVING count(*) > 1;

    SELECT org_id, chain_family, count(*) FROM user_wallets
    WHERE is_primary AND unlinked_at IS NULL
    GROUP BY org_id, chain_family HAVING count(*) > 1;
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(), matching 0014/0016: the
# project's local `alembic/` package shadows the installed library outside the
# alembic CLI runtime, and tests import this module for its pre-flight helper.

# revision identifiers, used by Alembic.
# NB: id kept <=32 chars — alembic_version.version_num is VARCHAR(32).
revision = "0017_user_wallets_uniques"
down_revision = "0016_api_keys_env_constraint"
branch_labels = None
depends_on = None

TABLE = "user_wallets"
INDEX_ACTIVE = "uq_user_wallets_active_org"
INDEX_PRIMARY = "uq_user_wallets_one_primary_org"


def check_wallet_duplicates(bind) -> None:
    """Raise unless both uniqueness predicates already hold on existing rows.

    Importable so tests can pin the exact behaviour without running alembic.
    Runs BEFORE any DDL, and reports the offending values so the operator can
    resolve them by hand.
    """
    problems: list[str] = []

    dup_active = bind.execute(
        sa.text(
            "SELECT org_id, chain_family, address, count(*) AS n "
            f"FROM {TABLE} WHERE unlinked_at IS NULL "
            "GROUP BY org_id, chain_family, address HAVING count(*) > 1 "
            "ORDER BY org_id"
        )
    ).fetchall()
    for org_id, chain_family, address, n in dup_active:
        problems.append(
            f"{INDEX_ACTIVE}: org={org_id} chain_family={chain_family} "
            f"address={address}: {n} active rows"
        )

    dup_primary = bind.execute(
        sa.text(
            "SELECT org_id, chain_family, count(*) AS n "
            f"FROM {TABLE} WHERE is_primary AND unlinked_at IS NULL "
            "GROUP BY org_id, chain_family HAVING count(*) > 1 "
            "ORDER BY org_id"
        )
    ).fetchall()
    for org_id, chain_family, n in dup_primary:
        problems.append(
            f"{INDEX_PRIMARY}: org={org_id} chain_family={chain_family}: "
            f"{n} active primary wallets"
        )

    if not problems:
        return

    raise RuntimeError(
        f"Cannot apply {revision}: {len(problems)} group(s) of user_wallets "
        "rows would violate the restored uniqueness. These indexes decide "
        "which org owns a wallet address, and that address is the tenant key "
        "for payments, webhooks and API keys — never merge or delete a row to "
        "make them fit. Investigate each group, unlink the rows that should "
        "not be active (set unlinked_at), or demote the extra primaries, then "
        "re-run `alembic upgrade head`. Details: " + "; ".join(problems)
    )


def _has_index(bind, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(bind).get_indexes(TABLE))


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    # Report and stop before any DDL.
    check_wallet_duplicates(bind)

    # Existence-guarded like 0011. Load-bearing, not just hygiene: 0001 is a
    # create_all of the CURRENT model, which now declares both indexes, so on a
    # from-scratch `upgrade head` they already exist by the time we get here.
    if not _has_index(bind, INDEX_ACTIVE):
        op.create_index(
            INDEX_ACTIVE,
            TABLE,
            ["org_id", "chain_family", "address"],
            unique=True,
            postgresql_where=sa.text("unlinked_at IS NULL"),
            sqlite_where=sa.text("unlinked_at IS NULL"),
        )

    if not _has_index(bind, INDEX_PRIMARY):
        op.create_index(
            INDEX_PRIMARY,
            TABLE,
            ["org_id", "chain_family"],
            unique=True,
            # Boolean literal differs per dialect: `is_primary = 1` is a type
            # error on Postgres, `= true` is not valid on SQLite.
            postgresql_where=sa.text("is_primary = true AND unlinked_at IS NULL"),
            sqlite_where=sa.text("is_primary = 1 AND unlinked_at IS NULL"),
        )


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if _has_index(bind, INDEX_PRIMARY):
        op.drop_index(INDEX_PRIMARY, table_name=TABLE)
    if _has_index(bind, INDEX_ACTIVE):
        op.drop_index(INDEX_ACTIVE, table_name=TABLE)

    # No data reversal: every row that satisfies the indexes also satisfies the
    # unconstrained schema.
