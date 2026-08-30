"""TRON Nile testnet — the environment boundary.

Nile exists so the TRON money path can be exercised before real money moves on
it. That is only worth anything if the two networks cannot be confused, so what
this module pins is the boundary rather than the feature:

  - a `tron_nile` intent is `test`, and a LIVE key cannot create one;
  - a `tron` intent is still `live`, and a TEST key still cannot create one
    (the regression half — the whole point is that Nile did not soften mainnet);
  - EVERY chain the registry supports sits in exactly one of
    `_TESTNET_CHAINS` / `_MAINNET_CHAINS`. That check is the load-bearing one:
    the env gate is an allowlist-of-the-OPPOSITE, so a chain in neither set
    passes BOTH branches and is creatable on test AND live keys. Adding
    `tron_nile` to the registry without adding it to a set is not a no-op, it
    is an env-crossing hole, and this test is what makes that impossible to
    ship again for any future chain;
  - Nile classifies as a testnet WITHOUT its chain id entering the EVM
    namespace. 3448148188 in `TESTNET_CHAIN_IDS` would make the boot guard send
    `eth_chainId` to a TRON node and SystemExit the backend.

Direct-handler tests (no live server), same pattern as
test_tron_watchonly_intent.py: fake `request.state.client`, real SQLite.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_nile.py -q
"""

import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.merchant_routes import create_payment_intent
from app.db.session import async_session, engine
from app.models.api_key_models import ApiKey
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import CreatePaymentIntentRequest, PaymentIntent
from app.models.org_models import Membership, Organization
from app.models.user_wallets_models import UserWallet
from app.security.api_keys import generate_api_key

NILE_USDT = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"
TRON_PAYEE = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
SETTLE = "0x1111111111111111111111111111111111111111"


def _fresh_owner() -> str:
    return "0x" + secrets.token_hex(20)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    except Exception:
        pass


@pytest_asyncio.fixture
async def session():
    async with async_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _quiet_audit(monkeypatch):
    import app.api.merchant_routes as mr

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "log_event", _no_log)


def _req(environment: str, *, owner: str, key_id=None):
    client = {"client_id": owner, "environment": environment}
    if key_id is not None:
        client["key_id"] = key_id
    return SimpleNamespace(state=SimpleNamespace(client=client))


async def _org_and_key(session, *, owner: str, environment: str, activation_status="not_started"):
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
        settlement_wallet=SETTLE,
        activation_status=activation_status,
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(
        UserWallet(
            user_id=user.id, org_id=org.id, address=owner, display_address=owner,
            verified_chain_id=84532, is_primary=True, chain_family="evm",
        )
    )
    await session.flush()
    _plaintext, fields = generate_api_key(environment=environment)
    key = ApiKey(
        owner_address=owner, org_id=str(org.id), **fields,
        label="tron-nile", scope="write",
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return org, key


def _payload(chain: str, **kw):
    d = dict(amount=10.0, currency="USDT", chain=chain, recipient=TRON_PAYEE)
    d.update(kw)
    return CreatePaymentIntentRequest(**d)


async def _intent_count(session) -> int:
    return (await session.execute(select(func.count(PaymentIntent.id)))).scalar() or 0


# ═══════════════════════════════════════════════════════════════
#  The environment boundary
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_nile_intent_on_a_test_key_is_stamped_test(session):
    """The affirmative half. `environment` is what every downstream read,
    webhook dispatch and key filter is scoped by, so the stamp IS the isolation."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, environment="test")

    result = await create_payment_intent(
        _payload("tron_nile"), _req("test", owner=owner, key_id=key.id), db=session
    )

    row = (await session.execute(select(PaymentIntent))).scalars().one()
    assert row.environment == "test"
    assert row.chain == "tron_nile"
    # Watch-only: the payer sends straight to the recipient, there is no router.
    assert result.onchain is None
    # base58 is case-SENSITIVE — lowercasing it produces an undecodable string.
    assert row.recipient == TRON_PAYEE


@pytest.mark.asyncio
async def test_a_live_key_cannot_create_a_nile_intent(session):
    """The refusal half, and the one the goal is stated in terms of. Not a
    404-shaped afterthought: the same MAINNET_ONLY envelope base_sepolia gets."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, environment="live")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("tron_nile"), _req("live", owner=owner, key_id=key.id), db=session
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "MAINNET_ONLY"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_tron_mainnet_is_still_live_only(session):
    """REGRESSION PIN. Nile must not have softened mainnet: a test key still
    cannot reach `tron`, and the refusal is still TESTNET_ONLY."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(session, owner=owner, environment="test")

    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("tron"), _req("test", owner=owner, key_id=key.id), db=session
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "TESTNET_ONLY"
    assert await _intent_count(session) == 0


@pytest.mark.asyncio
async def test_a_live_key_still_creates_a_tron_mainnet_intent_stamped_live(session):
    """The other half of the regression pin: mainnet TRON still works, and is
    still `live`. An activated org, because mainnet still requires activation
    and Nile deliberately does not."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(
        session, owner=owner, environment="live", activation_status="active"
    )

    await create_payment_intent(
        _payload("tron"), _req("live", owner=owner, key_id=key.id), db=session
    )

    row = (await session.execute(select(PaymentIntent))).scalars().one()
    assert row.environment == "live"
    assert row.chain == "tron"


# ═══════════════════════════════════════════════════════════════
#  The gate that made the hole possible
# ═══════════════════════════════════════════════════════════════

def test_every_supported_chain_is_in_exactly_one_environment_set():
    """The env check is an allowlist-of-the-OPPOSITE:

        if environment == "test"  and chain in _MAINNET_CHAINS: refuse
        if environment == "live"  and chain in _TESTNET_CHAINS: refuse

    so a chain in NEITHER set is refused by neither branch and is creatable on
    a test key AND a live key. Nothing else in `create_intent` closes that —
    `chain_is_supported` opens it, which is precisely the trap: adding a chain
    to the registry is what arms it.

    This is asserted over every registry chain rather than over `tron_nile`,
    because the next person to add a chain will not read this file."""
    from app.services import intent_service as isvc
    from app.services.router_registry import TOKEN_REGISTRY

    for chain in sorted(TOKEN_REGISTRY):
        in_test = chain in isvc._TESTNET_CHAINS
        in_main = chain in isvc._MAINNET_CHAINS
        assert in_test != in_main, (
            f"{chain!r}: testnet={in_test} mainnet={in_main} — a supported chain "
            f"in neither set passes both branches of the env gate; one in both "
            f"is unreachable on every key"
        )


def test_the_two_testnet_tables_cannot_drift_apart():
    """`_TESTNET_CHAINS` gates key↔chain binding; `WATCH_ONLY_TESTNET_CHAINS`
    gates the KYB activation requirement and the settlement environment stamp.
    A chain in the second but not the first would skip mainnet activation while
    still being creatable on a live key — the worst of both."""
    from app.services import intent_service as isvc
    from app.services.chain_access import WATCH_ONLY_TESTNET_CHAINS
    from app.services.router_registry import chain_is_supported, is_watch_only_chain

    assert WATCH_ONLY_TESTNET_CHAINS  # not vacuous
    for chain in WATCH_ONLY_TESTNET_CHAINS:
        assert chain == chain.lower(), chain
        assert chain in isvc._TESTNET_CHAINS, chain
        assert chain_is_supported(chain), chain
        assert is_watch_only_chain(chain), chain


# ═══════════════════════════════════════════════════════════════
#  Testnet WITHOUT entering the EVM id namespace
# ═══════════════════════════════════════════════════════════════

def test_nile_is_a_testnet_but_has_no_evm_chain_id():
    """`is_testnet_chain` classifies against an EVM frozenset and is fail-closed
    to mainnet, which is exactly right for it and exactly wrong for Nile. Nile's
    testnet-ness is therefore carried by NAME, and the id-keyed classifier is
    left untouched."""
    from app.services.chain_access import is_testnet_chain, is_watch_only_testnet
    from app.services.router_registry import chain_id_for

    assert chain_id_for("tron_nile") is None, "no synthetic EVM id"
    assert is_testnet_chain(chain_id_for("tron_nile")) is False, "fail-closed, unchanged"
    assert is_watch_only_testnet("tron_nile") is True
    # ...and the name classifier is fail-closed too.
    assert is_watch_only_testnet("tron") is False
    assert is_watch_only_testnet(None) is False
    assert is_watch_only_testnet("base_sepolia") is False, "an EVM testnet is not this"


def test_nile_chain_id_is_in_no_evm_chain_table():
    """3448148188 in any of these starts a PaymentWatcher, which makes
    `verify_chain_identity_for_boot` send `eth_chainId` to a TRON node and
    SystemExit the backend. Mirrors the mainnet guardrail in test_tron_poller."""
    from app.config import get_settings
    from app.services import chain_access, router_registry, rpc_manager
    from app.services.tron_poller import TRON_NILE_CHAIN_ID

    assert TRON_NILE_CHAIN_ID == 3448148188
    assert TRON_NILE_CHAIN_ID not in router_registry.CHAIN_IDS.values()
    assert TRON_NILE_CHAIN_ID not in chain_access.TESTNET_CHAIN_IDS
    assert TRON_NILE_CHAIN_ID not in chain_access.CHAIN_ID_BY_NAME.values()
    assert TRON_NILE_CHAIN_ID not in rpc_manager._DEFAULT_PROVIDERS

    s = get_settings()
    for m in (
        getattr(s, "rsends_router_addresses", {}) or {},
        getattr(s, "rsends_router_v2_addresses", {}) or {},
        getattr(s, "split_router_addresses", {}) or {},
    ):
        assert str(TRON_NILE_CHAIN_ID) not in {str(k) for k in m}


def test_the_nile_chain_id_derives_from_the_pinned_genesis():
    """Derived, not invented — the same cross-check mainnet's id gets."""
    from app.services.tron_chain_identity import TRON_NILE_GENESIS_BLOCK_ID
    from app.services.tron_poller import TRON_NILE_CHAIN_ID

    assert int(TRON_NILE_GENESIS_BLOCK_ID[-8:], 16) == TRON_NILE_CHAIN_ID


# ═══════════════════════════════════════════════════════════════
#  Activation: a testnet is not gated on business verification
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_nile_does_not_require_mainnet_activation_but_tron_still_does(session):
    """The KYB gate keys on testnet-ness, and Nile only reaches the right answer
    through the name classifier. Both halves in one test so the contrast is the
    assertion: the same unactivated org, the same key, two chains."""
    owner = _fresh_owner()
    _org, key = await _org_and_key(
        session, owner=owner, environment="test", activation_status="not_started"
    )

    await create_payment_intent(
        _payload("tron_nile"), _req("test", owner=owner, key_id=key.id), db=session
    )
    assert await _intent_count(session) == 1

    live_owner = _fresh_owner()
    _org2, live_key = await _org_and_key(
        session, owner=live_owner, environment="live", activation_status="not_started"
    )
    with pytest.raises(HTTPException) as exc:
        await create_payment_intent(
            _payload("tron"), _req("live", owner=live_owner, key_id=live_key.id),
            db=session,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "mainnet_activation_required"}


# ═══════════════════════════════════════════════════════════════
#  Registry
# ═══════════════════════════════════════════════════════════════

def test_nile_usdt_is_registered_enabled_and_watch_only():
    from app.services.router_registry import (
        chain_has_settlement_router,
        chain_is_supported,
        is_watch_only_chain,
        token_for,
        token_is_enabled,
    )

    assert chain_is_supported("tron_nile") is True
    assert is_watch_only_chain("tron_nile") is True
    assert chain_has_settlement_router("tron_nile") is False

    assert token_is_enabled("tron_nile", "USDT") is True
    tok = token_for("tron_nile", "USDT")
    assert tok is not None
    address, decimals = tok
    assert decimals == 6
    # Byte-identical: base58check is case-sensitive, so a fold is a corruption.
    assert address == NILE_USDT


def test_nile_and_mainnet_watch_different_contracts():
    """A copy-pasted mainnet USDT would validate perfectly and point the Nile
    poller at a contract that does not exist on Nile — it would simply observe
    nothing, forever, silently."""
    from app.services.router_registry import token_for

    assert token_for("tron_nile", "USDT") != token_for("tron", "USDT")
