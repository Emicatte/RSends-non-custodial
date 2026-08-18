"""Partial unique indexes on `user_wallets` — the org-scoped tenancy invariants.

Two partial unique indexes, created by the deleted migrations 0026/0030 and lost
when the chain was squashed into 0001 (which builds the schema from
`Base.metadata.create_all`, and the model carried no `__table_args__`):

  uq_user_wallets_active_org      UNIQUE (org_id, chain_family, address)
                                  WHERE unlinked_at IS NULL
  uq_user_wallets_one_primary_org UNIQUE (org_id, chain_family)
                                  WHERE is_primary AND unlinked_at IS NULL

Both predicates are load-bearing and are pinned here in BOTH directions — what
they must reject, and what they must keep allowing:

- the key is ORG-scoped, so the SAME address in two different orgs is legal and
  deliberately so (`user_wallets_routes.py:19-20`; four other test modules seed
  exactly that shape to exercise the ambiguity paths);
- `WHERE unlinked_at IS NULL` is what makes unlink→relink work: an org may hold
  a historical row and an active row for the same address;
- the one-primary index is partial on `is_primary` too, so an org may hold many
  active wallets as long as only one is primary.

Without the predicates these are not weaker constraints, they are wrong ones —
they would reject legitimate rows. That is what the over-broad check in the task
verifies, and tests 3/4/5 below are the ones that catch it.
"""

import importlib.util
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

import app.api.user_wallets_routes as wr
from app.api.user_wallets_routes import post_verify
from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Membership, Organization
from app.models.user_wallets_models import UserWallet
from app.models.user_wallets_schemas import WalletVerifyRequest

ADDR_A = "0x" + "a" * 40
ADDR_B = "0x" + "b" * 40
CHAIN_ID = 84532

INDEX_ACTIVE = "uq_user_wallets_active_org"
INDEX_PRIMARY = "uq_user_wallets_one_primary_org"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_org(session):
    """Org + owner user + admin membership. Returns (user_id, org_id)."""
    user = User(
        id=str(uuid4()),
        email=f"{secrets.token_hex(6)}@example.com",
        account_type="individual",
    )
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3),
        slug=secrets.token_hex(8),
        owner_user_id=user.id,
        is_personal=False,
        plan="free",
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    await session.commit()
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


def _verify_payload(address, label=None):
    return WalletVerifyRequest(
        chain_family="evm",
        address=address,
        chain_id=CHAIN_ID,
        nonce=secrets.token_hex(8),
        signature="0x" + "1" * 130,
        label=label,
    )


@pytest.fixture
def stub_siwe(monkeypatch):
    """The link route's only external dependency is SIWE verification and the
    best-effort audit write (its own session). Stub both so the test exercises
    the DB write path, which is what the index guards."""

    async def _ok(**kwargs):
        return "siwe-message"

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(wr, "verify_challenge", _ok)
    monkeypatch.setattr(wr, "record_auth_event", _noop)


# ── What the indexes must REJECT ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_org_duplicate_active_address_409(session, stub_siwe):
    """Linking an address THIS org already holds as active → 409
    wallet_already_linked, raised by the index via the IntegrityError handler.

    Note the task brief phrased this as "another org already holds"; under the
    recovered predicate the key is org-scoped, so the cross-org case is legal
    and is asserted as such in the next test. Same-org is the real rejection.
    """
    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, primary=True))
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await post_verify(
            payload=_verify_payload(ADDR_A),
            ctx=(user_id, org_id, "operator"),
            db=session,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "wallet_already_linked"


@pytest.mark.asyncio
async def test_second_active_primary_in_one_org_rejected(session):
    """A second active primary in the same (org, chain_family) violates
    uq_user_wallets_one_primary_org.

    Asserted at the DB level on purpose: `_promote_primary` clears every
    competing active primary before setting its own, so within a single
    transaction the route can never reach this state — only a cross-transaction
    race can, which is pinned in test_concurrency_postgres.py.
    """
    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, primary=True))
    await session.commit()

    session.add(_wallet(user_id, org_id, ADDR_B, primary=True))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# ── What the predicates must keep ALLOWING ─────────────────────────────────


@pytest.mark.asyncio
async def test_same_address_in_two_orgs_allowed(session, stub_siwe):
    """The key is org-scoped: another org holding the address is not a conflict.

    Guards against a too-broad key. Four other modules depend on this shape
    (test_recipient_gate, test_api_keys_org_id, test_owner_identity_fallback).
    """
    user_a, org_a = await _make_org(session)
    session.add(_wallet(user_a, org_a, ADDR_A, primary=True))
    await session.commit()

    user_b, org_b = await _make_org(session)
    created = await post_verify(
        payload=_verify_payload(ADDR_A),
        ctx=(user_b, org_b, "operator"),
        db=session,
    )
    assert created.address == ADDR_A
    assert created.is_primary is True  # first wallet in ITS org

    rows = (
        await session.execute(
            select(UserWallet).where(UserWallet.address == ADDR_A)
        )
    ).scalars().all()
    assert {str(r.org_id) for r in rows} == {org_a, org_b}


@pytest.mark.asyncio
async def test_unlinked_then_relink_same_address_allowed(session, stub_siwe):
    """`WHERE unlinked_at IS NULL` is what makes unlink → relink work: the
    historical row is preserved for audit and the address is linked again."""
    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, unlinked=True))
    await session.commit()

    created = await post_verify(
        payload=_verify_payload(ADDR_A),
        ctx=(user_id, org_id, "operator"),
        db=session,
    )
    assert created.address == ADDR_A

    rows = (
        await session.execute(
            select(UserWallet).where(
                UserWallet.org_id == org_id, UserWallet.address == ADDR_A
            )
        )
    ).scalars().all()
    assert len(rows) == 2  # audit row kept alongside the live one
    assert sum(1 for r in rows if r.unlinked_at is None) == 1


@pytest.mark.asyncio
async def test_two_orgs_each_with_unlinked_row_same_address_allowed(session):
    """Historical rows for the same address in two different orgs — neither
    predicate nor scope makes these collide."""
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    session.add(_wallet(user_a, org_a, ADDR_A, unlinked=True))
    session.add(_wallet(user_b, org_b, ADDR_A, unlinked=True))
    await session.commit()

    count = (
        await session.execute(
            select(UserWallet).where(UserWallet.address == ADDR_A)
        )
    ).scalars().all()
    assert len(count) == 2


@pytest.mark.asyncio
async def test_org_may_hold_active_primary_plus_active_non_primary(session):
    """The one-primary index is partial on `is_primary` as well: an org holds
    many active wallets, exactly one of them primary. Without that half of the
    predicate an org could never hold a second wallet at all."""
    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, primary=True))
    session.add(_wallet(user_id, org_id, ADDR_B, primary=False))
    await session.commit()

    rows = (
        await session.execute(
            select(UserWallet).where(UserWallet.org_id == org_id)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert sum(1 for r in rows if r.is_primary) == 1


# ── The promote path can actually see a violation ──────────────────────────


@pytest.mark.asyncio
async def test_promote_primary_flushes_inside_the_guarded_block(session):
    """`_promote_primary` must leave nothing pending.

    `patch_wallet` wraps it in try/except IntegrityError, but the ORM UPDATE for
    `is_primary` is only sent at `db.commit()` — which sits OUTSIDE that try. If
    the promote does not flush, a one-primary violation escapes the handler and
    the caller gets a 500 instead of the retry-then-409 the code was written to
    do. Pinned here because the cross-transaction proof needs real Postgres
    (test_concurrency_postgres.py) and cannot run on the suite's shared-
    connection SQLite engine.
    """
    user_id, org_id = await _make_org(session)
    first = _wallet(user_id, org_id, ADDR_A, primary=True)
    second = _wallet(user_id, org_id, ADDR_B, primary=False)
    session.add_all([first, second])
    await session.commit()

    await wr._promote_primary(session, second)

    assert second not in session.dirty, (
        "_promote_primary left is_primary pending — a violation would surface "
        "at commit(), outside patch_wallet's IntegrityError handler"
    )


# ── The indexes actually exist, with their predicates ──────────────────────


@pytest.mark.asyncio
async def test_create_all_produces_both_partial_indexes(session):
    """Asserted against the database catalogue, not the model — the whole defect
    was that the model and the database disagreed. Dialect-aware: the suite runs
    SQLite, production runs Postgres, and a `postgresql_where`-only index would
    silently degrade to a FULL unique index on SQLite.
    """
    dialect = session.bind.dialect.name

    if dialect == "sqlite":
        rows = (
            await session.execute(
                text(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='index' AND tbl_name='user_wallets'"
                )
            )
        ).fetchall()
        ddl = {r[0]: (r[1] or "") for r in rows}
    else:
        rows = (
            await session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'user_wallets'"
                )
            )
        ).fetchall()
        ddl = {r[0]: r[1] for r in rows}

    assert INDEX_ACTIVE in ddl, f"missing {INDEX_ACTIVE}; have {sorted(ddl)}"
    assert INDEX_PRIMARY in ddl, f"missing {INDEX_PRIMARY}; have {sorted(ddl)}"

    active = ddl[INDEX_ACTIVE].lower()
    assert "unique" in active
    for col in ("org_id", "chain_family", "address"):
        assert col in active
    assert "where" in active and "unlinked_at is null" in active

    primary = ddl[INDEX_PRIMARY].lower()
    assert "unique" in primary
    assert "org_id" in primary and "chain_family" in primary
    assert "where" in primary and "unlinked_at is null" in primary
    assert "is_primary" in primary


# ── Migration 0017: chains correctly, reports and stops ────────────────────


_MIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0017_user_wallets_uniques.py"
)


def _load_0017():
    spec = importlib.util.spec_from_file_location("mig_0017", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0017_chains_onto_the_current_head():
    mod = _load_0017()
    assert mod.down_revision == "0016_api_keys_env_constraint"
    assert mod.revision == "0017_user_wallets_uniques"
    assert len(mod.revision) <= 32  # alembic_version.version_num is VARCHAR(32)
    assert mod.INDEX_ACTIVE == INDEX_ACTIVE
    assert mod.INDEX_PRIMARY == INDEX_PRIMARY


async def _drop_the_indexes(session, mod):
    """Rebuild user_wallets WITHOUT the two indexes, so violating rows can be
    seeded — the pre-flight exists precisely for databases that predate them.

    Drop/create on the LIVE Table (flags restored immediately) rather than a
    `to_metadata()` copy as tests/test_key_environment_integrity.py does for
    api_keys: user_wallets carries FKs to users/organizations, which a detached
    copy cannot resolve when rendering CREATE. Nothing FK-references
    user_wallets, so dropping it is safe.
    """
    table = UserWallet.__table__

    def _rebuild(sync_conn):
        removed = [
            ix
            for ix in table.indexes
            if ix.name in (mod.INDEX_ACTIVE, mod.INDEX_PRIMARY)
        ]
        table.drop(sync_conn)
        for ix in removed:
            table.indexes.discard(ix)
        try:
            table.create(sync_conn)
        finally:
            for ix in removed:
                table.indexes.add(ix)

    await (await session.connection()).run_sync(_rebuild)


@pytest.mark.asyncio
async def test_migration_preflight_passes_on_clean_rows(session):
    mod = _load_0017()
    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, primary=True))
    session.add(_wallet(user_id, org_id, ADDR_B, primary=False))
    session.add(_wallet(user_id, org_id, ADDR_A, unlinked=True))
    await session.commit()

    conn = await session.connection()
    await conn.run_sync(lambda sync: mod.check_wallet_duplicates(sync))


@pytest.mark.asyncio
async def test_migration_preflight_reports_and_stops_on_duplicates(session):
    """Duplicate tenancy rows are an incident to investigate, not data to
    rewrite: the migration must name them and refuse, never merge or delete."""
    mod = _load_0017()
    await _drop_the_indexes(session, mod)

    user_id, org_id = await _make_org(session)
    session.add(_wallet(user_id, org_id, ADDR_A, primary=True))
    session.add(_wallet(user_id, org_id, ADDR_A, primary=False))  # dup address
    session.add(_wallet(user_id, org_id, ADDR_B, primary=True))  # dup primary
    await session.commit()

    conn = await session.connection()
    with pytest.raises(RuntimeError) as exc:
        await conn.run_sync(lambda sync: mod.check_wallet_duplicates(sync))

    message = str(exc.value)
    assert mod.INDEX_ACTIVE in message and mod.INDEX_PRIMARY in message
    assert org_id in message
    assert "never merge or delete" in message

    # And it really did not touch the rows.
    rows = (
        await session.execute(
            select(UserWallet).where(UserWallet.org_id == org_id)
        )
    ).scalars().all()
    assert len(rows) == 3
