"""The /api/v1/user/org/source-wallets surface — RED-first pins (Pair A).

A source wallet is the merchant wallet RSendsAutoSplit empties: the row is
the org<->wallet linkage plus the keeper's watch scope (chain + token) — the
policy itself (recipients/bps/minAmount) lives ON CHAIN and is never
mirrored. Registration is SIWE challenge/verify (Pair A: only the wallet's
key-holder can register — the merchant necessarily holds it, having to sign
setPolicy/approve on chain anyway), which is what makes the uniqueness index
GLOBAL-active safe: `uq_source_wallets_active` UNIQUE (chain, address,
token_symbol) WHERE disabled_at IS NULL, cross-org.

Pins here: registration row shape (org_id tenant key, address stored in its
chain's canonical form, environment stamped from chain), global-active
uniqueness with disable->re-register (fresh-row semantics), org isolation in
the SQL (cross-tenant disable -> 404, never 403), env scoping, the per-org
cap, require_org_approved wiring on every route (the GATED-list pattern from
test_approval_gate.py), and the ENDPOINT_LIMITS entries via _match_endpoint
(the test_rate_limit_matching discipline — first-startswith-wins, so the
subpath rows must sit ABOVE the bare GET).

CASE NORMALISATION IS PINNED HERE BECAUSE THE DATABASE NO LONGER PINS IT.
0024 dropped `ck_source_wallets_address_lower`: the table now holds base58check
addresses too, which that predicate would reject outright, and SQL cannot
verify a base58 checksum. Normalisation therefore lives entirely in the request
schemas, and `uq_source_wallets_active` is a PLAIN index over raw columns —
unlike `uq_users_email_lower`, which is FUNCTIONAL on lower(email) and so is
case-insensitive in the database itself. The consequence is specific: if the
schema ever stops folding, a case difference produces TWO ACCEPTED ROWS
SILENTLY, not an IntegrityError. So the tests below pin the PAIR (normalise ->
index) and assert the active-row count stays 1, and `_provoke_duplicate`
refuses to pass at all if the index has gone missing.

Imports of the not-yet-built modules happen INSIDE fixtures/tests so each
test fails RED with its own ModuleNotFoundError; the wiring and rate-limit
pins import existing modules and fail RED on assertions. SIWE is stubbed on
the route module (suite idiom), never signed.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Membership, Organization

# Registers source_wallets in Base.metadata BEFORE the autouse create_all.
# Without it the table is absent until some other import pulls the model in,
# so the FIRST test in the module runs against a database that has no
# source_wallets table — an ordering-dependent failure that looks like a bug
# in whatever test happens to run first. Imported for the side effect only.
import app.models.source_wallet_models  # noqa: F401,E402

ADDR = "0x" + "a" * 40
ADDR_2 = "0x" + "b" * 40
ADDR_3 = "0x" + "c" * 40
# EIP-55 checksum of ADDR ("0xaaa...a" checksums to mixed case) is computed
# by the implementation; tests only assert lower/display consistency.
AUTOSPLIT_ADDR = "0x" + "5" * 40
CHAIN = "base_sepolia"
BASE_PREFIX = "/api/v1/user/org/source-wallets"

# The mixed-case wire form of ADDR. Not merely "a different string": every
# EVM address arrives from a wallet in EIP-55 form, so this IS the normal
# input, and ADDR is what must reach the index.
ADDR_MIXED = "0x" + "Aa" * 20

# TRON. `tron_nile` is the watch-only TESTNET (environment "test", like
# base_sepolia), so the env assertions in this module stay uniform. The address
# is a real base58check wallet already used elsewhere in the suite — NOT a
# token contract, and NOT TRON_ZERO_ADDRESS (whose checksum is valid, so only
# an explicit comparison rejects it).
TRON_CHAIN = "tron_nile"
TRON_ADDR = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
TRON_TOKEN = "USDT"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """create_all + FK-ordered ROW wipe — no drop_all (shared-PG gotcha)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in (
            Membership.__table__,
            Organization.__table__,
            User.__table__,
        ):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


async def _make_org(session):
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


@pytest.fixture
def stub_siwe(monkeypatch):
    import app.api.source_wallet_routes as swr

    async def _ok(**kwargs):
        return "siwe-message"

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(swr, "verify_challenge", _ok)
    monkeypatch.setattr(swr, "record_auth_event", _noop)


@pytest.fixture
def open_autosplit(monkeypatch):
    """Every row-creating test needs the fail-closed AutoSplit gate open."""
    import app.services.source_wallet_service as svc

    monkeypatch.setattr(svc, "auto_split_address_for", lambda chain: AUTOSPLIT_ADDR)


async def _verify(session, ctx, *, address=ADDR, chain=CHAIN, token_symbol="USDC"):
    from app.api.source_wallet_routes import post_verify
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    return await post_verify(
        payload=SourceWalletVerifyRequest(
            chain=chain,
            token_symbol=token_symbol,
            address=address,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        ),
        ctx=ctx,
        db=session,
    )


async def _list(session, ctx, *, environment="test"):
    from app.api.source_wallet_routes import list_source_wallets

    return await list_source_wallets(ctx=ctx, environment=environment, db=session)


async def _disable(session, ctx, source_wallet_id):
    from app.api.source_wallet_routes import post_disable

    return await post_disable(
        source_wallet_id=source_wallet_id, ctx=ctx, db=session
    )


async def _rows(session):
    from app.models.source_wallet_models import SourceWallet

    return (await session.execute(select(SourceWallet))).scalars().all()


# ── Registration row shape ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_creates_row_with_org_tenancy_and_env(
    session, stub_siwe, open_autosplit
):
    """Happy path: the row is org_id-keyed (NEVER owner_address — the org_id
    re-key lesson), EVM address folded to lowercase with a checksummed display
    twin, environment stamped server-side from the chain (base_sepolia -> test),
    and the chain stored by NAME (0024 — TRON has no EVM chain id to key by)."""
    user_id, org_id = await _make_org(session)

    await _verify(session, (user_id, org_id, "admin"), address=ADDR_MIXED)

    rows = await _rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert str(row.org_id) == org_id
    assert row.address == ADDR  # lowercased at rest
    assert row.display_address.lower() == ADDR  # checksum twin, same wallet
    assert row.display_address != ADDR  # and actually checksummed, not copied
    assert row.environment == "test"
    assert row.token_symbol == "USDC"
    assert row.chain == CHAIN  # the NAME, not 84532
    assert row.disabled_at is None


# ── Global-active uniqueness (safe only because registration is SIWE) ─────


@pytest.mark.asyncio
async def test_second_org_same_tuple_409_then_free_after_disable(
    session, stub_siwe, open_autosplit
):
    """GLOBAL-active unique on (chain, address, token_symbol): a second
    org registering the same tuple gets 409 source_wallet_taken; after the
    holder disables, the tuple is registrable again (the partial
    `WHERE disabled_at IS NULL` predicate doing its job — fresh-row
    re-enable semantics, decision 4)."""
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)

    resp_a = await _verify(session, (user_a, org_a, "admin"))
    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_b, org_b, "admin"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "source_wallet_taken"

    await _disable(session, (user_a, org_a, "admin"), resp_a.id)
    await _verify(session, (user_b, org_b, "admin"))  # now succeeds

    rows = await _rows(session)
    active = [r for r in rows if r.disabled_at is None]
    assert len(active) == 1 and str(active[0].org_id) == org_b


@pytest.mark.asyncio
async def test_same_wallet_different_token_is_a_separate_registration(
    session, stub_siwe, open_autosplit
):
    """The uniqueness key mirrors the contract's (merchant, token) policy
    key: same wallet + different token is a distinct, legal row."""
    user_id, org_id = await _make_org(session)
    await _verify(session, (user_id, org_id, "admin"), token_symbol="USDC")
    await _verify(session, (user_id, org_id, "admin"), token_symbol="ETH")
    assert len(await _rows(session)) == 2


# ── Case normalisation: the invariant the dropped CHECK used to hold ──────
#
# 0024 removed ck_source_wallets_address_lower. Everything below is what pays
# for that removal. Read the module docstring first if this section looks
# redundant with the uniqueness tests above — it is not: those pin that the
# INDEX rejects an identical tuple, these pin that two DIFFERENT input strings
# for the same wallet are folded into one tuple before the index ever sees them.


async def _provoke_duplicate(session, org_ctx, *, chain, address, token_symbol):
    """Insert the same (chain, address, token_symbol) twice, ORM-direct, and
    hand back the IntegrityError the index raises.

    Deliberately NOT through the route: the route's pre-check SELECT would
    reject the second row first, so a green result would say nothing about
    whether the index exists. This writes straight at the table, which is the
    only way to put `uq_source_wallets_active` itself under test.

    The fall-through is the whole point, and it is copied from
    `test_user_wallets_violated_asyncpg.py:201-225`: if no IntegrityError
    arrives, the index is gone and every duplicate assertion in this module has
    silently become vacuous. The module says so rather than passing.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.source_wallet_models import SourceWallet

    user_id, org_id = org_ctx

    def _row():
        return SourceWallet(
            id=str(uuid4()),
            org_id=org_id,
            created_by_user_id=user_id,
            chain=chain,
            environment="test",
            address=address,
            display_address=address,
            token_symbol=token_symbol,
        )

    session.add(_row())
    await session.commit()
    session.add(_row())
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        return exc

    await session.rollback()
    raise AssertionError(
        "no IntegrityError — uq_source_wallets_active is missing on this "
        "database, so this module cannot test what it claims to"
    )


@pytest.mark.asyncio
async def test_the_active_index_exists_and_bites(session):
    """The premise every duplicate assertion in this module rests on.

    Trivial-looking on purpose: its value is that `_provoke_duplicate` raises
    a NAMED failure when the index is absent, instead of this suite going
    green against a table with no duplicate protection at all.
    """
    ctx = await _make_org(session)

    exc = await _provoke_duplicate(
        session, ctx, chain=CHAIN, address=ADDR, token_symbol="USDC"
    )

    assert exc is not None


@pytest.mark.asyncio
async def test_the_active_index_survives_with_its_partial_predicate(session):
    """0024 removed a CheckConstraint; this pins that it removed nothing else.

    Dialect-aware because SQLAlchemy silently DROPS a mismatched `*_where`: a
    `postgresql_where`-only index degrades to a FULL unique index on the SQLite
    engine CI runs, which would forbid legitimate disable->re-register rather
    than merely under-enforce — a failure invisible on Postgres.
    """
    from sqlalchemy import text

    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        rows = (await session.execute(text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='source_wallets'"))).fetchall()
        ddl = {r[0]: (r[1] or "") for r in rows}
    else:
        rows = (await session.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'source_wallets'"))).fetchall()
        ddl = {r[0]: r[1] for r in rows}

    assert "uq_source_wallets_active" in ddl, f"missing; have {sorted(ddl)}"
    definition = ddl["uq_source_wallets_active"].lower()
    assert "unique" in definition
    for col in ("chain", "address", "token_symbol"):
        assert col in definition
    assert "where" in definition and "disabled_at is null" in definition
    assert "chain_id" not in definition, "the numeric key survived the re-key"


@pytest.mark.asyncio
async def test_same_evm_wallet_in_different_case_cannot_enter_twice(
    session, stub_siwe, open_autosplit
):
    """EIP-55 in, lowercase at rest — so the second form collides with the first.

    The common path: the route's pre-check SELECT sees the already-folded
    address and 409s. What it proves is that folding happens BEFORE the
    comparison. Without it the two forms are different strings, both are
    accepted, and the same wallet is registered twice.
    """
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)

    await _verify(session, (user_a, org_a, "admin"), address=ADDR_MIXED)
    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_b, org_b, "admin"), address=ADDR)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "source_wallet_taken"
    active = [r for r in await _rows(session) if r.disabled_at is None]
    assert len(active) == 1, "a case difference created a second active row"


@pytest.mark.asyncio
async def test_evm_case_collision_still_caught_when_the_pre_check_misses(
    session, stub_siwe, open_autosplit, monkeypatch
):
    """With the pre-check blinded, the INDEX rejects the case variant.

    The pre-check and the index state the same rule twice, and two concurrent
    registrations both see an empty pre-check. Blinding it reproduces that race
    for the case-difference input specifically — which is the half the dropped
    CheckConstraint used to backstop. Note what failure looks like here: not an
    unhandled IntegrityError but a SECOND ACCEPTED ROW, because
    `uq_source_wallets_active` is a plain index over raw columns and cannot see
    two spellings as one address on its own.
    """
    import app.api.source_wallet_routes as swr

    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    await _verify(session, (user_a, org_a, "admin"), address=ADDR_MIXED)

    async def _blind(*args, **kwargs):
        return None

    monkeypatch.setattr(swr, "_active_holder", _blind)

    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_b, org_b, "admin"), address=ADDR)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "source_wallet_taken"
    active = [r for r in await _rows(session) if r.disabled_at is None]
    assert len(active) == 1, "a case difference survived the unique index"


@pytest.mark.asyncio
async def test_tron_address_round_trips_byte_identical(
    session, stub_siwe, open_autosplit
):
    """base58check is case-SENSITIVE, so the stored value must be untouched.

    Byte-identical, not "equal ignoring case". base58 excludes 0 O I l, so
    folding a T-address does not show a different address — it shows a string
    that no longer decodes and whose checksum no longer verifies. The
    `!= .lower()` assertion is what catches a future writer who "helpfully"
    adds a fold; `== TRON_ADDR` alone would not, if the fold were added to a
    path this test does not cover.
    """
    user_id, org_id = await _make_org(session)

    await _verify(
        session,
        (user_id, org_id, "admin"),
        address=TRON_ADDR,
        chain=TRON_CHAIN,
        token_symbol=TRON_TOKEN,
    )

    row = (await _rows(session))[0]
    assert row.address == TRON_ADDR, "case must survive the round trip"
    assert row.address != TRON_ADDR.lower(), "a fold would have destroyed it"
    assert row.display_address == TRON_ADDR, "no EIP-55 twin exists on base58"
    assert row.chain == TRON_CHAIN
    assert row.environment == "test", "tron_nile is the TESTNET"


def test_lowercasing_a_tron_address_destroys_it():
    """The premise the validator rests on, stated independently of any route."""
    from app.security.input_validator import is_tron_address

    assert is_tron_address(TRON_ADDR) is True
    assert is_tron_address(TRON_ADDR.lower()) is False


@pytest.mark.asyncio
async def test_case_mangled_tron_address_is_rejected_at_parse(session):
    """…so it can never reach the index as a second row.

    This is why the base58 half needs no duplicate test to mirror the EVM one:
    a case variant of a T-address is not the same address in another form, it
    is an INVALID string, and the schema refuses it before any row exists. The
    EVM fold and this rejection are the two halves of one guarantee.

    The positive control is load-bearing. Without it this test passes even when
    the schema is EVM-only and rejects EVERY T-address — proving nothing about
    case at all. Accepting the correctly-cased form in the same breath is what
    makes the rejection attributable to the case difference.
    """
    from pydantic import ValidationError

    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    def _build(address):
        return SourceWalletVerifyRequest(
            chain=TRON_CHAIN,
            token_symbol=TRON_TOKEN,
            address=address,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        )

    # Control: the correctly-cased address parses, and parses UNCHANGED.
    assert _build(TRON_ADDR).address == TRON_ADDR

    with pytest.raises(ValidationError):
        _build(TRON_ADDR.lower())

    assert await _rows(session) == []


def test_the_route_never_folds_an_address():
    """The schema is the SINGLE normalisation point; the route must not add one.

    Reads code, not prose (`code_without_prose`), so the docstrings that warn
    about folding are not themselves flagged as the violation.
    """
    import app.api.source_wallet_routes as swr
    from tests._source_helpers import code_without_prose

    code = code_without_prose(swr)

    assert ".lower()" not in code, (
        "the route folded an address; base58check is case-SENSITIVE and the "
        "request schema is the only place normalisation belongs"
    )
    assert "to_checksum_address" not in code, (
        "to_checksum_address raises on a base58check address — use "
        "display_address_for_chain, which dispatches on the address family "
        "(NOT input_validator.display_payment_address: that one lowercases an "
        "EVM address, which would collapse display_address onto address)"
    )


# ── Org isolation + environment scoping (in the SQL, 404 not 403) ─────────


@pytest.mark.asyncio
async def test_list_is_org_isolated_and_env_scoped(session, stub_siwe, open_autosplit):
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    await _verify(session, (user_a, org_a, "admin"))

    listed_b = await _list(session, (user_b, org_b, "viewer"))
    assert listed_b.source_wallets == []

    listed_a_live = await _list(session, (user_a, org_a, "viewer"), environment="live")
    assert listed_a_live.source_wallets == []

    listed_a = await _list(session, (user_a, org_a, "viewer"))
    assert len(listed_a.source_wallets) == 1
    assert listed_a.source_wallets[0].address == ADDR


@pytest.mark.asyncio
async def test_disable_cross_tenant_404_and_idempotent(
    session, stub_siwe, open_autosplit
):
    """Tenant scope (id, org_id) IN the query: another org disabling my row
    gets 404 (existence never leaks as 403). Repeat disable by the owner is
    idempotent, and the row count never changes."""
    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    resp = await _verify(session, (user_a, org_a, "admin"))

    with pytest.raises(HTTPException) as exc:
        await _disable(session, (user_b, org_b, "admin"), resp.id)
    assert exc.value.status_code == 404

    await _disable(session, (user_a, org_a, "admin"), resp.id)
    await _disable(session, (user_a, org_a, "admin"), resp.id)  # idempotent

    rows = await _rows(session)
    assert len(rows) == 1
    assert rows[0].disabled_at is not None


# ── Per-org cap (bounds keeper gas exposure) ──────────────────────────────


@pytest.mark.asyncio
async def test_cap_reached_409(session, stub_siwe, open_autosplit, monkeypatch):
    """MAX_SOURCE_WALLETS_PER_ORG counts ACTIVE rows only. Pinned via a
    monkeypatched cap of 2 on the route module (the MAX_WALLETS_PER_ORG
    import style of user_wallets_routes)."""
    import app.api.source_wallet_routes as swr

    monkeypatch.setattr(swr, "MAX_SOURCE_WALLETS_PER_ORG", 2)
    user_id, org_id = await _make_org(session)
    await _verify(session, (user_id, org_id, "admin"), address=ADDR)
    await _verify(session, (user_id, org_id, "admin"), address=ADDR_2)

    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_id, org_id, "admin"), address=ADDR_3)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "max_source_wallets_reached"
    assert len(await _rows(session)) == 2


# ── Route wiring: every route gated by require_org_approved ───────────────

SOURCE_WALLET_ROUTES = [
    ("GET", BASE_PREFIX),
    ("POST", BASE_PREFIX + "/challenge"),
    ("POST", BASE_PREFIX + "/verify"),
    ("POST", BASE_PREFIX + "/{source_wallet_id}/disable"),
    ("GET", BASE_PREFIX + "/{source_wallet_id}/onchain"),
]


def _route_dep_names(app, method: str, path: str) -> set[str]:
    from fastapi.routing import APIRoute

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            names = set()

            def _walk(dependant):
                for sub in dependant.dependencies:
                    if sub.call is not None:
                        names.add(getattr(sub.call, "__qualname__", ""))
                    _walk(sub)

            _walk(route.dependant)
            return names
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.parametrize("method,path", SOURCE_WALLET_ROUTES)
def test_source_wallet_routes_wired_and_approval_gated(method, path):
    """The five routes exist under the JWT-exempt /api/v1/user/ prefix and
    every one carries require_org_approved (the operational-route dep) —
    the GATED-list discipline of test_approval_gate.py."""
    from app.main import app

    names = _route_dep_names(app, method, path)
    assert any("require_org_approved" in n for n in names), (
        f"{method} {path} is NOT gated by require_org_approved: {names}"
    )


# ── Rate limits: behavioral pins through _match_endpoint ──────────────────


def test_rate_limit_subpath_writes_matched():
    """POST subpath rule (10/60 ip) covers challenge/verify/disable and must
    sit ABOVE the bare GET row — _match_endpoint is first-startswith-wins,
    so misordering silently turns the stricter rule into dead code."""
    from app.middleware.rate_limit import _match_endpoint

    assert _match_endpoint("POST", BASE_PREFIX + "/challenge") == (10, 60, "ip")
    assert _match_endpoint("POST", BASE_PREFIX + "/verify") == (10, 60, "ip")
    assert _match_endpoint("POST", BASE_PREFIX + "/some-id/disable") == (10, 60, "ip")


def test_rate_limit_bare_get_matched():
    from app.middleware.rate_limit import _match_endpoint

    assert _match_endpoint("GET", BASE_PREFIX) == (120, 60, "ip")


# ── The index is the real backstop; the pre-check is only the fast path ───


@pytest.mark.asyncio
async def test_index_violation_surfaces_as_409_not_500(
    session, stub_siwe, open_autosplit, monkeypatch
):
    """When the pre-check misses and the INDEX is what rejects, the client
    still gets 409 source_wallet_taken — never a 500.

    The pre-check SELECT and `uq_source_wallets_active` state the same rule in
    two places, and between the two there is a window: two orgs verifying the
    same wallet concurrently both see an empty pre-check, and only one insert
    survives. The loser must not be handed an unhandled IntegrityError. This
    blinds the pre-check (returning None, exactly what the racing transaction
    would have seen) so the insert reaches the index for real.
    """
    import app.api.source_wallet_routes as swr

    user_a, org_a = await _make_org(session)
    user_b, org_b = await _make_org(session)
    await _verify(session, (user_a, org_a, "admin"))

    async def _blind(*args, **kwargs):
        return None

    monkeypatch.setattr(swr, "_active_holder", _blind)

    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_b, org_b, "admin"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "source_wallet_taken"

    rows = await _rows(session)
    assert len([r for r in rows if r.disabled_at is None]) == 1


@pytest.mark.asyncio
async def test_unrelated_integrity_error_is_not_mislabelled_as_409(
    session, stub_siwe, open_autosplit, monkeypatch
):
    """A DIFFERENT constraint must not be reported as source_wallet_taken.

    `_violated` discriminates by constraint name (Postgres) or column set
    (SQLite) and returns False for anything it does not recognise, so the
    error re-raises as a 500 — ugly but honest. Blaming the uniqueness index
    for a foreign-key violation would tell the merchant their address is
    taken when the real fault is elsewhere. Here the org_id is a well-formed
    uuid that no organization row owns, so the insert trips the FK.

    SQLite needs `PRAGMA foreign_keys=ON` said explicitly — it is OFF by
    default, per connection, so without this the orphan insert SUCCEEDS and
    this test passes while proving nothing. (It did exactly that until the
    chain re-key made the route reach the database at all: the assertion was
    satisfied by an AttributeError raised long before any SQL ran.) Postgres
    enforces the FK unconditionally, so the pragma is a no-op there.
    """
    from sqlalchemy import text

    if session.bind.dialect.name == "sqlite":
        await session.execute(text("PRAGMA foreign_keys=ON"))

    user_id, _org_id = await _make_org(session)
    orphan_org = str(uuid4())

    with pytest.raises(Exception) as exc:
        await _verify(session, (user_id, orphan_org, "admin"))

    # Explicitly NOT an HTTPException 409: the FK violation propagates.
    assert not (
        isinstance(exc.value, HTTPException)
        and exc.value.status_code == 409
    ), "an unrelated IntegrityError was mislabelled as source_wallet_taken"
    assert await _rows(session) == []
