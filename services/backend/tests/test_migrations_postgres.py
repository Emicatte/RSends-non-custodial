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

HEAD = "0009_onboarding"
# Alembic's hardcoded alembic_version.version_num width.
_VERSION_NUM_MAX = 32

PG_URL = os.getenv("ALEMBIC_TEST_DATABASE_URL")
_needs_pg = pytest.mark.skipif(
    not PG_URL,
    reason="ALEMBIC_TEST_DATABASE_URL not set (Postgres-backed migration test)",
)

_REVISION_RE = re.compile(r'^revision\s*=\s*"([^"]+)"', re.MULTILINE)


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
def test_upgrade_head_reaches_0009_on_postgres(clean_schema):
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
