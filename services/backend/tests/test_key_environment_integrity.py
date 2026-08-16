"""The key environment cannot be forged, and cannot disagree with the prefix.

Two independent writes used to decide a key's environment: `generate_api_key`
derived the STRING prefix (rsend_test_ / rsend_live_), while each mint route
separately passed `environment=` to the ApiKey constructor for the COLUMN.
Nothing tied them — no CHECK constraint, no validator — so a row whose prefix
reads rsend_test_ but whose column says "live" is, to every consumer, a live
key. Verification reads the column (api_keys.py `_api_key_to_dict`); the
merchant reads the string. They agreed only by convention.

Worse, the prefix branch was `"rsend_test_" if environment == "test" else
"rsend_live_"`: ANY value that was not exactly "test" — a typo, a casing
variant, an empty string — silently produced a live-looking key.

`generate_api_key` is now the single source: it normalizes, validates, derives
the prefix, and returns the canonical value in its db_fields, so both mint
routes persist exactly what the prefix encodes.

Insert-side default and read-side fallback are deliberately ASYMMETRIC and both
are pinned here: a row created without an environment is the powerless one; a
key read back without one gets the strict gate.
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey, KeyEnvironment
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Organization
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key


@pytest_asyncio.fixture(autouse=True)
async def setup_db(monkeypatch):
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


def _fresh_wallet() -> str:
    return "0x" + secrets.token_hex(20)


# ── generate_api_key is the single source of the environment ──

@pytest.mark.parametrize("environment", ["test", "live"])
def test_returned_environment_matches_the_prefix(environment):
    plaintext, fields = generate_api_key(environment=environment)

    assert fields["environment"] == environment
    assert plaintext.startswith(f"rsend_{environment}_")
    assert fields["key_prefix"].startswith(f"rsend_{environment}_")


def test_environment_is_normalized():
    """Casing and surrounding whitespace resolve to the canonical value."""
    plaintext, fields = generate_api_key(environment="  TEST ")

    assert fields["environment"] == "test"
    assert plaintext.startswith("rsend_test_")


@pytest.mark.parametrize("bad", ["production", "sandbox", "", "tests", "LIVEE"])
def test_out_of_range_environment_is_rejected(bad):
    """Previously anything != "test" silently produced a live-looking key."""
    with pytest.raises(ValueError):
        generate_api_key(environment=bad)


def test_key_environment_enum_covers_the_accepted_values():
    """The enum stops being decorative: it is what the column accepts."""
    assert {e.value for e in KeyEnvironment} == {"test", "live"}


# ── The column cannot hold a forged value ────────────────────

def test_orm_rejects_an_environment_outside_the_enum():
    with pytest.raises(ValueError):
        ApiKey(
            owner_address="0x" + "1" * 40,
            org_id=str(uuid4()),
            key_hash="h", key_prefix="p", hash_version=2,
            environment="production",
        )


def test_orm_insert_default_is_test():
    """A row created without an explicit environment must be the powerless one."""
    key = ApiKey(
        owner_address="0x" + "1" * 40,
        org_id=str(uuid4()),
        key_hash="h", key_prefix="p", hash_version=2,
    )
    assert ApiKey.__table__.columns["environment"].default.arg == "test"
    assert key.environment is None or key.environment == "test"


# ── Both mint routes persist what the prefix encodes ─────────

@pytest.mark.asyncio
async def test_session_mint_row_agrees_with_its_prefix(session):
    from app.api.user_org_merchant_keys_routes import create_merchant_key, MerchantKeyCreateRequest

    user = User(
        id=str(uuid4()),
        email=f"{uuid4()}@example.com",
        password_hash="$2b$12$" + "x" * 53,
        email_verified=True,
        account_type="merchant",
    )
    org = Organization(
        id=str(uuid4()), name="Org", slug=f"org-{uuid4()}",
        owner_user_id=user.id, is_personal=False, plan="free",
        settlement_wallet=_fresh_wallet().lower(), extra_metadata={},
    )
    session.add_all([user, org])
    await session.commit()

    res = await create_merchant_key(
        payload=MerchantKeyCreateRequest(label="agreement"),
        request=SimpleNamespace(
            client=SimpleNamespace(host="1.2.3.4"), headers={"user-agent": "pytest"}
        ),
        ctx=(user.id, org.id, "admin"),
        db=session,
    )

    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.key_prefix.startswith(f"rsend_{row.environment}_")
    assert res.key.startswith(f"rsend_{row.environment}_")


@pytest.mark.asyncio
async def test_wallet_mint_row_agrees_with_its_prefix(session):
    from app.api.api_key_routes import GenerateKeyRequest, generate_key

    wallet = _fresh_wallet()
    user = User(
        id=str(uuid4()),
        email=f"{uuid4()}@example.com",
        password_hash="$2b$12$" + "x" * 53,
        email_verified=True,
        account_type="merchant",
    )
    org = Organization(
        id=str(uuid4()), name="Org", slug=f"org-{uuid4()}",
        owner_user_id=user.id, is_personal=False, plan="free",
        approval_status="approved", extra_metadata={},
    )
    session.add_all([user, org])
    await session.flush()
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=wallet.lower(),
        display_address=wallet, verified_chain_id=84532,
        chain_family="evm", is_primary=True,
    ))
    await session.commit()

    res = await generate_key.__wrapped__(
        request=SimpleNamespace(
            client=SimpleNamespace(host="1.2.3.4"), headers={"user-agent": "pytest"}
        ),
        req=GenerateKeyRequest(owner_address="ignored", environment="live"),
        db=session,
        wallet_address=wallet,
    )

    row = (
        await session.execute(select(ApiKey).where(ApiKey.id == res.id))
    ).scalar_one()
    assert row.environment == "live"
    assert row.key_prefix.startswith("rsend_live_")
    assert res.key.startswith("rsend_live_")


# ── Read-side fallbacks stay "live" (deliberate asymmetry) ───

def test_verification_fallback_for_a_missing_environment_is_live():
    """A key read back without an environment gets the STRICT gate, not the
    sandbox one. This is the mirror image of the insert default and must not be
    "aligned" with it."""
    from app.security.api_keys import _api_key_to_dict

    row = SimpleNamespace(
        owner_address="0x" + "1" * 40, org_id=None, label=None, id=1,
        scope=None, environment=None, rate_limit_rpm=None,
    )
    assert _api_key_to_dict(row)["environment"] == "live"


def test_merchant_route_environment_fallback_is_live():
    from app.api.merchant_routes import _get_environment

    assert _get_environment(SimpleNamespace(state=SimpleNamespace())) == "live"
    assert _get_environment(
        SimpleNamespace(state=SimpleNamespace(client={"client_id": "x"}))
    ) == "live"


# ── Migration 0016: pre-flight reports and stops ─────────────

def _load_0016():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "0016_api_keys_environment_constraint.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0016", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_0016_chains_onto_the_current_head():
    mod = _load_0016()
    assert mod.down_revision == "0015_backfill_onchain_invoice_id"
    assert mod.revision == "0016_api_keys_env_constraint"
    assert len(mod.revision) <= 32  # alembic_version.version_num is VARCHAR(32)


@pytest.mark.asyncio
async def test_migration_preflight_passes_on_clean_rows(session):
    mod = _load_0016()
    for env in ("test", "live"):
        _p, fields = generate_api_key(environment=env)
        session.add(ApiKey(
            owner_address=_fresh_wallet().lower(), org_id=str(uuid4()),
            **fields, label="clean", scope="write",
        ))
    await session.commit()

    conn = await session.connection()
    await conn.run_sync(lambda sync_conn: mod.check_environment_values(sync_conn))


@pytest.mark.asyncio
async def test_migration_preflight_reports_and_stops_on_a_bad_row(session):
    """A key with an unrecognised environment is an incident, not a value to
    overwrite: the migration must name it and refuse, never coerce or delete."""
    mod = _load_0016()

    # The pre-flight exists for databases that predate this migration, so
    # rebuild api_keys WITHOUT the CHECK the model now carries — otherwise the
    # constraint under test would reject the very row it is meant to catch.
    conn = await session.connection()

    def _pre_0016_api_keys(sync_conn):
        legacy_md = sa.MetaData()
        tbl = ApiKey.__table__.to_metadata(legacy_md)
        for c in list(tbl.constraints):
            if getattr(c, "name", None) == mod.CONSTRAINT_NAME:
                tbl.constraints.discard(c)
        ApiKey.__table__.drop(sync_conn)
        tbl.create(sync_conn)

    await conn.run_sync(_pre_0016_api_keys)

    _p, fields = generate_api_key(environment="live")
    # Bypass the ORM validator on purpose. The value must fit String(8) — the
    # column width alone already bounds how wrong a stored value can be.
    fields["environment"] = "sandbox"
    await session.execute(
        ApiKey.__table__.insert().values(
            owner_address=_fresh_wallet().lower(), org_id=str(uuid4()),
            label="forged", scope="write", **fields,
        )
    )

    with pytest.raises(RuntimeError) as exc:
        await conn.run_sync(lambda sync_conn: mod.check_environment_values(sync_conn))

    assert "sandbox" in str(exc.value)
    assert "never rewrites or deletes" in str(exc.value)

    # And it really did not touch the row.
    surviving = (
        await session.execute(
            select(ApiKey.environment).where(ApiKey.label == "forged")
        )
    ).scalar_one()
    assert surviving == "sandbox"
