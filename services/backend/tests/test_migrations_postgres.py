"""Alembic migration regression tests for issue #17 (revision-id length).

Alembic hardcodes ``alembic_version.version_num`` as ``VARCHAR(32)`` (see
``alembic.runtime.migration`` — it is NOT configurable via ``context.configure``).
A revision id longer than 32 chars therefore truncates the moment Alembic writes
it, raising ``StringDataRightTruncationError`` on Postgres. This bit us with
``0006_merchant_webhook_environment`` (33 chars); the fix shortened that id to
``0006_merchant_webhook_env``.

Two layers of protection:
  * ``test_all_revision_ids_fit_version_column`` — a fast, backend-independent
    invariant that runs in the normal (SQLite) suite: every revision id ≤ 32 chars.
  * the Postgres-gated tests — run the real chain end-to-end so the truncation
    can never hide again (SQLite cannot reproduce it).

The Postgres tests are gated on ``ALEMBIC_TEST_DATABASE_URL`` (async form,
``postgresql+asyncpg://.../db``): skipped locally when unset, run in CI where a
``postgres`` service provides it. Alembic is driven through its **console script**
(subprocess) — the local ``services/backend/alembic/`` script package shadows the
installed distribution whenever cwd is on ``sys.path`` (``-m`` / top-level import),
and the console-script path is exactly what production's pre-deploy runs.
"""

import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

# services/backend — where alembic.ini + the alembic/ script dir live.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_VERSIONS_DIR = _BACKEND_ROOT / "alembic" / "versions"

# Alembic's hardcoded alembic_version.version_num width.
_VERSION_NUM_MAX = 32

PG_URL = os.getenv("ALEMBIC_TEST_DATABASE_URL")
_needs_pg = pytest.mark.skipif(
    not PG_URL,
    reason="ALEMBIC_TEST_DATABASE_URL not set (Postgres-backed migration test)",
)

_REVISION_RE = re.compile(r'^revision\s*=\s*"([^"]+)"', re.MULTILINE)
_DOWN_REVISION_RE = re.compile(r'^down_revision\s*=\s*"([^"]+)"', re.MULTILINE)


def _compute_head() -> str:
    """The repo's single migration head, derived from the version files' chain
    topology (the revision no other file lists as its down_revision) — a
    hardcoded HEAD went stale every time a migration landed. Never imports the
    alembic library (the local alembic/ script dir shadows it, see module
    docstring). The single-head assert also catches an accidentally BRANCHED
    chain (two parallel migrations off the same parent), which filename
    sorting would silently miss. The root's ``down_revision = None`` is
    unquoted, so it correctly doesn't match the regex."""
    revisions: dict[str, str | None] = {}
    for path in _VERSIONS_DIR.glob("[0-9]*.py"):
        text = path.read_text()
        m = _REVISION_RE.search(text)
        if not m:
            continue
        down = _DOWN_REVISION_RE.search(text)
        revisions[m.group(1)] = down.group(1) if down else None
    assert revisions, "no migration files found"
    downs = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in downs]
    assert len(heads) == 1, f"expected exactly one migration head, got: {heads}"
    return heads[0]


HEAD = _compute_head()


def _all_revision_ids() -> dict[str, str]:
    """Map each migration filename → its declared revision id."""
    ids: dict[str, str] = {}
    for path in _VERSIONS_DIR.glob("[0-9]*.py"):
        m = _REVISION_RE.search(path.read_text())
        if m:
            ids[path.name] = m.group(1)
    return ids


def test_all_revision_ids_fit_version_column():
    """No revision id may exceed Alembic's VARCHAR(32) version_num (issue #17)."""
    ids = _all_revision_ids()
    assert ids, "no migration revision ids found"
    too_long = {name: rid for name, rid in ids.items() if len(rid) > _VERSION_NUM_MAX}
    assert not too_long, (
        f"revision id(s) exceed VARCHAR({_VERSION_NUM_MAX}) and will truncate on "
        f"Postgres: { {n: f'{r} ({len(r)})' for n, r in too_long.items()} }"
    )


# ── Postgres-gated end-to-end tests ────────────────────────────────────────

# The alembic console script (resolves the installed pkg irrespective of cwd,
# unlike ``python -m alembic`` which the local alembic/ script dir shadows).
_ALEMBIC_BIN = shutil.which("alembic") or str(Path(sys.executable).parent / "alembic")


def _raw_dsn() -> str:
    """asyncpg wants a plain ``postgresql://`` DSN (no ``+asyncpg`` driver tag)."""
    return PG_URL.replace("postgresql+asyncpg://", "postgresql://")


def _alembic(*args: str) -> subprocess.CompletedProcess:
    """Run ``alembic ...`` from services/backend with DATABASE_URL=PG."""
    env = {**os.environ, "DATABASE_URL": PG_URL}
    return subprocess.run(
        [_ALEMBIC_BIN, *args],
        cwd=_BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


async def _exec(*statements: str):
    conn = await asyncpg.connect(dsn=_raw_dsn())
    try:
        for stmt in statements:
            await conn.execute(stmt)
    finally:
        await conn.close()


async def _fetchval(query: str):
    conn = await asyncpg.connect(dsn=_raw_dsn())
    try:
        return await conn.fetchval(query)
    finally:
        await conn.close()


@pytest.fixture
def clean_schema():
    """Hand each test a fresh, empty public schema (drops any prior run + alembic_version)."""
    asyncio.run(_exec("DROP SCHEMA IF EXISTS public CASCADE", "CREATE SCHEMA public"))
    yield


@_needs_pg
def test_upgrade_head_reaches_head_on_postgres(clean_schema):
    """A from-scratch ``upgrade head`` runs the whole chain on Postgres.

    Before the id fix, writing 0006's 33-char id to ``alembic_version`` raised
    ``StringDataRightTruncationError`` here and the CLI exited non-zero.
    """
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, (
        f"alembic upgrade head failed (issue #17?):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    version = asyncio.run(_fetchval("SELECT version_num FROM alembic_version"))
    assert version == HEAD


@_needs_pg
def test_stamp_then_upgrade_is_noop(clean_schema):
    """Mimic production: full schema present, no ``alembic_version`` → stamp → upgrade is a no-op.

    Proves the post-stamp production deploy's pre-deploy ``alembic upgrade head``
    finds nothing to do.
    """
    # 1. Build the full head schema, then drop alembic_version so the DB looks
    #    like production: all tables present, but unversioned.
    assert _alembic("upgrade", "head").returncode == 0
    asyncio.run(_exec("DROP TABLE alembic_version"))

    def _table_count() -> int:
        return asyncio.run(
            _fetchval(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )

    before = _table_count()

    # 2. Stamp at head, then upgrade: every guarded migration must see its
    #    columns/tables already present and change nothing.
    assert _alembic("stamp", HEAD).returncode == 0
    upgrade = _alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    version = asyncio.run(_fetchval("SELECT version_num FROM alembic_version"))
    assert version == HEAD
    # +1 for the freshly (re)created alembic_version table; no schema tables added.
    assert _table_count() == before + 1


@_needs_pg
def test_0010_backfills_existing_orgs_and_drops_oauth_columns(clean_schema):
    """Migration 0010 on a legacy (0009) DB with data:

    * every pre-existing org is backfilled approval_status='approved' (nobody
      already live gets locked out by the new gate);
    * the column carries NO lingering server default afterwards (create_all
      parity — env.py compares server defaults, see the 0009 reconciliation);
    * the orphan OAuth columns are dropped from users;
    * downgrade -1 reverses: approval columns gone, OAuth columns back nullable.

    Pinned to 0010 on BOTH bounds (upgrade target and downgrade) so later
    migrations don't shift what `downgrade -1` unwinds — when 0011 landed,
    `upgrade head` + `downgrade -1` silently started testing 0011's reversal
    instead of 0010's.
    """
    assert _alembic("upgrade", "0009_onboarding").returncode == 0
    # 0001 is a create_all of the CURRENT ORM, so "at 0009" the schema already
    # carries the 0010 columns (and lacks the dropped OAuth ones). Reshape it
    # into the true legacy state production had before 0010 ran.
    asyncio.run(
        _exec(
            "ALTER TABLE organizations DROP COLUMN approval_status",
            "ALTER TABLE organizations DROP COLUMN approval_requested_at",
            "ALTER TABLE organizations DROP COLUMN approval_decided_at",
            "ALTER TABLE organizations DROP COLUMN approval_decided_by",
            "ALTER TABLE organizations DROP COLUMN decline_reason",
            "ALTER TABLE users ADD COLUMN google_sub text",
            "ALTER TABLE users ADD COLUMN github_sub text",
            "ALTER TABLE users ADD COLUMN github_username text",
            "CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub)",
            "CREATE UNIQUE INDEX ix_users_github_sub ON users (github_sub)",
        )
    )
    asyncio.run(
        _exec(
            "INSERT INTO users (id, email, email_verified, created_at, updated_at,"
            " status, account_type, metadata_json, age_attested)"
            " VALUES ('11111111-1111-1111-1111-111111111111', 'pre@example.com',"
            " true, now(), now(), 'active', 'merchant', '{}', false)",
            "INSERT INTO organizations (id, name, slug, owner_user_id, is_personal,"
            " plan, extra_metadata, onboarding_status, activation_status)"
            " VALUES ('22222222-2222-2222-2222-222222222222', 'Pre', 'pre0010',"
            " '11111111-1111-1111-1111-111111111111', true, 'free', '{}',"
            " 'company_submitted', 'not_started')",
        )
    )

    upgrade = _alembic("upgrade", "0010_org_approval")
    assert upgrade.returncode == 0, upgrade.stderr

    assert (
        asyncio.run(
            _fetchval(
                "SELECT approval_status FROM organizations WHERE slug = 'pre0010'"
            )
        )
        == "approved"
    )
    assert (
        asyncio.run(
            _fetchval(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_name = 'organizations'"
                " AND column_name = 'approval_status'"
            )
        )
        is None
    )
    assert (
        asyncio.run(
            _fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'users' AND column_name IN"
                " ('google_sub', 'github_sub', 'github_username')"
            )
        )
        == 0
    )

    downgrade = _alembic("downgrade", "-1")
    assert downgrade.returncode == 0, downgrade.stderr
    assert (
        asyncio.run(
            _fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'organizations'"
                " AND column_name LIKE 'approval%'"
            )
        )
        == 0
    )
    assert (
        asyncio.run(
            _fetchval(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'users' AND column_name IN"
                " ('google_sub', 'github_sub', 'github_username')"
                " AND is_nullable = 'YES'"
            )
        )
        == 3
    )


@_needs_pg
def test_0012_downgrade_reverses_cursor_table(clean_schema):
    """Migration 0012 is genuinely reversible. Bounds are PINNED (downgrade to
    0011 explicitly, not -1) so later migrations can't shift what this test
    unwinds — the exact failure mode the 0010 test hit when 0011 landed."""

    def _has_cursor_table() -> bool:
        return (
            asyncio.run(
                _fetchval(
                    "SELECT count(*) FROM information_schema.tables"
                    " WHERE table_schema = 'public'"
                    " AND table_name = 'indexer_cursors'"
                )
            )
            == 1
        )

    assert _alembic("upgrade", "head").returncode == 0
    assert _has_cursor_table()

    down = _alembic("downgrade", "0011_api_keys_org_id")
    assert down.returncode == 0, down.stderr
    assert not _has_cursor_table()
    version = asyncio.run(_fetchval("SELECT version_num FROM alembic_version"))
    assert version == "0011_api_keys_org_id"

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert _has_cursor_table()
