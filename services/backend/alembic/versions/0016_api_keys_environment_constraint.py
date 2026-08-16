"""Constrain api_keys.environment to {'test','live'} and default it to 'test'.

The column has been NOT NULL since the 0001 baseline (which created the table
from Base.metadata, so no migration ever declared it), but nothing bounded its
VALUES: it is a plain String(8) with no CHECK and no SQL enum, and the
KeyEnvironment enum in the model was declared and referenced nowhere. A row
could therefore hold any short string — including one that contradicts the
prefix baked into the key itself, which is what verification reads.

Two changes, both verifiable against existing rows before they are applied:

  server_default 'test'  — the column has NO server_default today, so a raw
                           INSERT that omits it fails outright. Where a default
                           does apply, it must be the POWERLESS environment.
                           (The read-side fallbacks stay "live" on purpose, so
                           an unstamped key meets the STRICT gate — that is a
                           different question and lives in application code.)

  CHECK ck_api_keys_environment — environment IN ('test','live').

PRE-FLIGHT: rows outside the allowed set are REPORTED AND THE MIGRATION STOPS,
following 0014. Never coerce and never delete a key row: a key with an
unexpected environment is an incident to investigate, not a value to overwrite.

Verify before running:
    SELECT environment, count(*) FROM api_keys GROUP BY environment;
"""

import sqlalchemy as sa

# `op` is imported lazily inside upgrade()/downgrade(), matching 0014: the
# project's local `alembic/` package shadows the installed library outside the
# alembic CLI runtime, and tests import this module for its pre-flight helper.

# revision identifiers, used by Alembic.
# NB: id kept <=32 chars — Alembic hardcodes alembic_version.version_num as
# VARCHAR(32); the full "0016_api_keys_environment_constraint" (36) would
# truncate on Postgres, same as issue #17. Filename is unchanged; Alembic keys
# off this string. Pinned by test_migrations_postgres.
revision = "0016_api_keys_env_constraint"
down_revision = "0015_backfill_onchain_invoice_id"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_api_keys_environment"
ALLOWED = ("test", "live")


def check_environment_values(bind) -> None:
    """Raise unless every api_keys.environment is in ALLOWED.

    Importable so tests can pin the exact behaviour without running alembic.
    """
    rows = bind.execute(
        sa.text(
            "SELECT environment, count(*) AS n FROM api_keys "
            "WHERE environment IS NULL OR environment NOT IN ('test', 'live') "
            "GROUP BY environment ORDER BY environment"
        )
    ).fetchall()
    if not rows:
        return

    details = "; ".join(f"{r[0]!r}: {r[1]} row(s)" for r in rows)
    raise RuntimeError(
        f"Cannot apply {revision}: api_keys.environment holds value(s) outside "
        f"{list(ALLOWED)} — {details}. A key whose environment is unrecognised "
        "may be authenticating against the wrong network; investigate and fix "
        "each row by hand (correct the value, or revoke the key), then re-run "
        "`alembic upgrade head`. This migration never rewrites or deletes a key."
    )


def _has_constraint(bind, name: str) -> bool:
    try:
        existing = sa.inspect(bind).get_check_constraints("api_keys")
    except NotImplementedError:  # older SQLite dialects
        return False
    return any(c.get("name") == name for c in existing)


def _server_default(bind) -> str | None:
    cols = sa.inspect(bind).get_columns("api_keys")
    col = next((c for c in cols if c["name"] == "environment"), None)
    return None if col is None else col.get("default")


def upgrade() -> None:
    from alembic import op

    bind = op.get_bind()
    check_environment_values(bind)

    if _server_default(bind) is None:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.alter_column(
                    "environment",
                    existing_type=sa.String(8),
                    existing_nullable=False,
                    server_default="test",
                )
        else:
            op.alter_column(
                "api_keys",
                "environment",
                existing_type=sa.String(8),
                existing_nullable=False,
                server_default="test",
            )

    if not _has_constraint(bind, CONSTRAINT_NAME):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.create_check_constraint(
                    CONSTRAINT_NAME, "environment IN ('test', 'live')"
                )
        else:
            op.create_check_constraint(
                CONSTRAINT_NAME, "api_keys", "environment IN ('test', 'live')"
            )


def downgrade() -> None:
    from alembic import op

    bind = op.get_bind()

    if _has_constraint(bind, CONSTRAINT_NAME):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        else:
            op.drop_constraint(CONSTRAINT_NAME, "api_keys", type_="check")

    if _server_default(bind) is not None:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("api_keys") as batch:
                batch.alter_column(
                    "environment",
                    existing_type=sa.String(8),
                    existing_nullable=False,
                    server_default=None,
                )
        else:
            op.alter_column(
                "api_keys",
                "environment",
                existing_type=sa.String(8),
                existing_nullable=False,
                server_default=None,
            )
    # No data reversal: every value is valid under both schemas.
