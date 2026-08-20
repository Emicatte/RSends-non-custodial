"""`_violated` on the driver production actually runs — asyncpg.

The two 409 handlers in `user_wallets_routes.py` depend on `_violated()`
recognising WHICH index an `IntegrityError` violated. It read the constraint
name from `exc.orig.diag.constraint_name`, which is the **psycopg2** shape.
asyncpg has no `.diag`, so the name was never found, control fell through to a
branch matching SQLite's `UNIQUE constraint failed` text (asyncpg says
`duplicate key value violates unique constraint`), `False` came back, the
original exception was re-raised and the caller got a **500 instead of a 409**.

Observed shape on this driver (asyncpg 0.29 + SQLAlchemy 2.0.35), which is what
these tests exist to pin:

    type(exc.orig)                 AsyncAdapt_asyncpg_dbapi.IntegrityError
    type(exc.orig.__cause__)       asyncpg.exceptions.UniqueViolationError
    exc.orig.constraint_name       <absent>
    exc.orig.__cause__.constraint_name  'uq_user_wallets_active_org'
    exc.orig.sqlstate/pgcode       '23505'
    hasattr(exc.orig, 'diag')      False

SQLAlchemy's asyncpg dialect re-raises with `raise translated_error from error`,
so the real asyncpg exception — the only object carrying the name — survives as
`__cause__`.

WHY A SEPARATE MODULE. `tests/test_user_wallets_uniqueness.py` uses the app's
global engine, whose dialect is decided by an ambient `DATABASE_URL` the test
does not control: locally that is Postgres (`.env`), but **CI sets
`DATABASE_URL=sqlite+aiosqlite://`**, so in CI that module silently exercises
the SQLite branch instead. This module pins Postgres explicitly so the asyncpg
path is covered in BOTH places:

  * locally — the app URL is already Postgres, so its engine is reused directly
    (no CREATE DATABASE: the dev role has no CREATEDB);
  * in CI — `WALLETS_PG_TEST_DATABASE_URL` names a DEDICATED database on the
    existing `postgres:16` service (dedicated so it cannot interfere with the
    Alembic and concurrency modules, per the rule in ci.yml);
  * otherwise — skipped, loudly, rather than passing on the wrong dialect.

`NullPool` so each session is its own connection, i.e. a real transaction.
"""

import os
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.api.user_wallets_routes as wr
from app.api.user_wallets_routes import (
    IDX_ACTIVE_ADDRESS,
    IDX_ONE_PRIMARY,
    patch_wallet,
    post_verify,
)
from app.config import get_settings
from app.db.session import Base
# Importing the app registers EVERY model module (19 tables → 35). Without it
# `user_api_keys` is absent from Base.metadata, so drop_all never drops its
# `fk_user_api_keys_org` (use_alter) and the teardown then fails to drop
# `organizations`. Noqa: imported for the metadata side effect only.
import app.main  # noqa: F401
from app.models.auth_models import User
from app.models.org_models import Membership, Organization
from app.models.user_wallets_models import UserWallet
from app.models.user_wallets_schemas import WalletPatchRequest, WalletVerifyRequest

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40
CHAIN_ID = 84532

_APP_URL = get_settings().database_url
_APP_IS_PG = _APP_URL.startswith("postgresql")
_CI_URL = os.getenv("WALLETS_PG_TEST_DATABASE_URL")
#: Local: the app's own Postgres. CI: the dedicated database. Never SQLite.
PG_URL = _APP_URL if _APP_IS_PG else _CI_URL

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason=(
        "asyncpg-pinned: needs a Postgres DATABASE_URL (local .env) or "
        "WALLETS_PG_TEST_DATABASE_URL (CI). Refuses to run on SQLite — that is "
        "the blind spot this module exists to close."
    ),
)


async def _ensure_database() -> None:
    """CI only: create the dedicated database if it is missing.

    Skipped when we are pointed at the app's own database (local), where it
    already exists and the dev role has no CREATEDB anyway.
    """
    if _APP_IS_PG:
        return
    raw = PG_URL.replace("postgresql+asyncpg://", "postgresql://")
    base, _, dbname = raw.rpartition("/")
    conn = await asyncpg.connect(dsn=f"{base}/postgres")
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if not exists:
            # Name comes from an operator-supplied env var, not user input.
            await conn.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def pg():
    """Sessionmaker over a fresh schema on Postgres, one connection per session.

    Uses the house create_all/drop_all pattern rather than
    `DROP SCHEMA public CASCADE` (which the concurrency module can afford
    because CI runs it as superuser) so this is safe against the local dev
    database too.
    """
    await _ensure_database()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield sm
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def stub_siwe(monkeypatch):
    """The link route's only external dependencies: SIWE verification and the
    best-effort audit write. Stub both so the DB write path is what runs."""

    async def _ok(**kwargs):
        return "siwe-message"

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(wr, "verify_challenge", _ok)
    monkeypatch.setattr(wr, "record_auth_event", _noop)


async def _make_org(db):
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
    )
    db.add(user)
    await db.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
    )
    db.add(org)
    await db.flush()
    db.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    await db.commit()
    return str(user.id), str(org.id)


def _wallet(user_id, org_id, address, *, primary=False, unlinked=False):
    return UserWallet(
        user_id=user_id,
        org_id=org_id,
        address=address,
        display_address=address,
        verified_chain_id=CHAIN_ID,
        chain_family="evm",
        is_primary=primary,
        unlinked_at=datetime.now(timezone.utc) if unlinked else None,
    )


def _verify_payload(address):
    return WalletVerifyRequest(
        chain_family="evm",
        address=address,
        chain_id=CHAIN_ID,
        nonce=secrets.token_hex(8),
        signature="0x" + "1" * 130,
        label=None,
    )


async def _capture(sm, *, primary_clash: bool) -> IntegrityError:
    """Provoke a REAL violation on this driver and hand back the exception.

    `primary_clash=True` violates uq_user_wallets_one_primary_org (two active
    primaries in one org), otherwise uq_user_wallets_active_org (the same
    active address twice in one org).
    """
    async with sm() as db:
        user_id, org_id = await _make_org(db)
        if primary_clash:
            db.add(_wallet(user_id, org_id, ADDR_A, primary=True))
            await db.commit()
            db.add(_wallet(user_id, org_id, ADDR_B, primary=True))
        else:
            db.add(_wallet(user_id, org_id, ADDR_A))
            await db.commit()
            db.add(_wallet(user_id, org_id, ADDR_A))
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            return exc
    raise AssertionError(
        "no IntegrityError — the partial unique index is missing on this "
        "database, so this module cannot test what it claims to"
    )


# ── 1. the reported defect: duplicate active address ───────────────────────


@pytest.mark.asyncio
async def test_duplicate_active_address_returns_409_not_500(pg, stub_siwe):
    """Linking an address the org already holds active → 409, not a raw
    UniqueViolationError escaping as a 500. This is the end-to-end route path."""
    async with pg() as db:
        user_id, org_id = await _make_org(db)
        db.add(_wallet(user_id, org_id, ADDR_A))
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await post_verify(
                payload=_verify_payload(ADDR_A),
                ctx=(user_id, org_id, "operator"),
                db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"code": "wallet_already_linked"}


# ── 2. the promote path: both guarded call sites ───────────────────────────


@pytest.mark.asyncio
async def test_primary_race_returns_409_not_500(pg, monkeypatch):
    """When both the first promote AND the retry lose, the caller gets 409
    `primary_race`.

    The exception injected is a GENUINE asyncpg IntegrityError captured from
    this database, so `_violated` is handed exactly what production hands it —
    only the timing is made deterministic. It drives both guarded call sites:
    the retry arm (which must recognise the violation to retry at all) and the
    inner arm that produces the 409.
    """
    captured = await _capture(pg, primary_clash=True)

    async def _always_clashes(db, wallet):
        raise captured

    monkeypatch.setattr(wr, "_promote_primary", _always_clashes)

    async with pg() as db:
        user_id, org_id = await _make_org(db)
        target = _wallet(user_id, org_id, ADDR_B)
        db.add(target)
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await patch_wallet(
                wallet_id=str(target.id),
                payload=WalletPatchRequest(is_primary=True),
                ctx=(user_id, org_id, "admin"),
                db=db,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"code": "primary_race"}


# ── 3. discrimination: nothing gets mislabeled ─────────────────────────────


@pytest.mark.asyncio
async def test_violated_discriminates_between_the_two_indexes(pg):
    """One real exception, checked both ways.

    A violation of the one-primary index must NOT be reported as the
    duplicate-address index. Getting this wrong would tell the caller something
    false about what went wrong — the reason `_violated` discriminates at all
    instead of mapping every IntegrityError to a 409.
    """
    primary_exc = await _capture(pg, primary_clash=True)
    address_exc = await _capture(pg, primary_clash=False)

    assert wr._violated(primary_exc, IDX_ONE_PRIMARY) is True
    assert wr._violated(primary_exc, IDX_ACTIVE_ADDRESS) is False

    assert wr._violated(address_exc, IDX_ACTIVE_ADDRESS) is True
    assert wr._violated(address_exc, IDX_ONE_PRIMARY) is False


@pytest.mark.asyncio
async def test_constraint_name_is_read_from_the_asyncpg_cause(pg):
    """Pins the attribute path itself, so a driver/SQLAlchemy upgrade that moves
    it fails here with a clear reason rather than silently reverting every 409
    to a 500 in production."""
    exc = await _capture(pg, primary_clash=False)

    cause = exc.orig.__cause__
    assert isinstance(cause, asyncpg.exceptions.UniqueViolationError)
    assert cause.constraint_name == IDX_ACTIVE_ADDRESS[0]
    assert exc.orig.sqlstate == "23505"
    # The shape the old code looked for does not exist on this driver.
    assert not hasattr(exc.orig, "diag")


# ── 4. unknown shapes stay honest ──────────────────────────────────────────


def test_unrecognised_shape_returns_false_and_warns(caplog):
    """An exception shape `_violated` cannot identify must NOT become a 409.

    Returning False re-raises the original error and yields a 500 — ugly but
    honest. The warning is the point: the absence of any signal is why this
    defect survived undetected.
    """
    mystery = IntegrityError("stmt", {}, Exception("something else entirely"))

    with caplog.at_level("WARNING"):
        assert wr._violated(mystery, IDX_ACTIVE_ADDRESS) is False

    assert any(r.levelname == "WARNING" for r in caplog.records), caplog.records
    logged = " ".join(r.getMessage() for r in caplog.records)
    # The driver message can carry the offending VALUE (Postgres appends
    # `DETAIL: Key (...)=(0x...) already exists`), and this module logs wallet
    # address prefixes only. The warning must name the shape, not the data.
    assert "0x" not in logged


def test_known_but_different_constraint_does_not_warn(pg_url_unused=None):
    """A recognised name that simply is not ours returns False WITHOUT warning —
    that shape was understood fine, so it is not a blind spot."""

    class _Cause(Exception):
        constraint_name = "uq_some_other_table_thing"

    exc = IntegrityError("stmt", {}, Exception("wrapped"))
    exc.orig.__cause__ = _Cause()

    import logging

    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Collect()
    wr.log.addHandler(handler)
    try:
        assert wr._violated(exc, IDX_ACTIVE_ADDRESS) is False
    finally:
        wr.log.removeHandler(handler)

    assert [r for r in records if r.levelno >= logging.WARNING] == []
