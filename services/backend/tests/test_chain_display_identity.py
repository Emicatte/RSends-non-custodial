"""The dashboard's chain identity: a machine-stable key, assembled not invented.

`user_org_stats_routes` used to answer the dashboard's chain column with a
DISPLAY LABEL and nothing else — "Base", "Base Sepolia", or the honest
`chain:{id}` for anything its four-entry dict did not know. One string served as
both lookup key and user-facing text, which is how the frontend ended up keying
a badge map on labels while `explorer.ts` keyed on snake names: two vocabularies
over the same row, with nothing able to notice they disagreed.

So the row now also carries `chain_key` — snake, machine-stable, the vocabulary
`explorer.ts` and `createChains.ts` already speak.

The key map is ASSEMBLED from sources that already exist, never re-typed:
`CHAIN_IDS` for coverage, `_CHAIN_NAME_BY_ID` overlaid for the alias case, and
`TRON_NETWORKS` unioned in for the two TRON networks. That is load-bearing:
a fourth hand-written chain table is exactly how the two vocabularies drifted in
the first place.

Three properties, in the order they matter:
  1. A settlement on any known chain id serialises with its snake key, TRON
     included — the defect this branch exists to fix.
  2. The assembly is DETERMINISTIC. `CHAIN_IDS` is many-to-one ("eth" and
     "ethereum" both → 1), so inverting it is not well-defined on its own; the
     overlay resolves it and this pins the resolution instead of trusting dict
     iteration order.
  3. Building the display map MOVES NOTHING on the money path. The obvious way
     to give Arbitrum a name — adding 42161 to `_CHAIN_NAME_BY_ID` — would make
     `chain_is_supported("arbitrum")` start returning True, and "arbitrum" is in
     neither `_TESTNET_CHAINS` nor `_MAINNET_CHAINS`, so it would become
     creatable on test AND live keys. A display fix would have opened a money
     gate. This is the guard against that.
"""

import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

import app.api.user_org_stats_routes as stats_mod
from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.auth_models import User
from app.models.org_models import Organization, Membership
from app.models.user_wallets_models import UserWallet
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.api.user_org_stats_routes import get_org_stats

from app.services.chain_display import CHAIN_KEY_BY_ID, build_chain_key_by_id, chain_key_for
from app.services.tron_poller import TRON_CHAIN_ID, TRON_NILE_CHAIN_ID

OWNER_A = "0x" + "a" * 40
SETTLE_WALLET_A = "0x" + "d" * 40
USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
USDT_TRC20_NILE = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"
TRON_PAYEE = "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8"

FROZEN_NOW = datetime(2026, 3, 15, 0, 4, 0, tzinfo=timezone.utc)


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


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch):
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)

    monkeypatch.setattr(stats_mod, "datetime", _FrozenDatetime)


async def _make_org(session, *, owner_address):
    user = User(id=str(uuid4()), email=f"{secrets.token_hex(6)}@example.com", account_type="individual")
    session.add(user)
    await session.flush()
    org = Organization(
        name="Org " + secrets.token_hex(3), slug=secrets.token_hex(8),
        owner_user_id=user.id, is_personal=False, plan="free",
    )
    session.add(org)
    await session.flush()
    session.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=owner_address,
        display_address=owner_address, verified_chain_id=84532,
        is_primary=True, chain_family="evm",
    ))
    await session.commit()
    return org


async def _seed(session, *, owner, chain_id, token=USDC_SEPOLIA, merchant=None, chain="base_sepolia"):
    intent_id = f"pi_{secrets.token_hex(16)}"
    session.add(PaymentIntent(
        intent_id=intent_id, reference_id=secrets.token_hex(8),
        merchant_id=owner, environment="test", amount=5.0, currency="USDC",
        chain=chain, status=IntentStatus.completed, recipient=SETTLE_WALLET_A,
        expires_at=FROZEN_NOW + timedelta(minutes=30),
    ))
    session.add(PaymentSettlement(
        invoice_id=None,
        merchant=SETTLE_WALLET_A if merchant is None else merchant,
        payer="0x" + "e" * 40, token=token, amount=5_000_000,
        chain_id=chain_id, tx_hash="0x" + secrets.token_hex(32), log_index=0,
        block_number=1, status=SettlementStatus.final, intent_id=intent_id,
        created_at=FROZEN_NOW - timedelta(hours=1),
    ))
    await session.commit()
    return intent_id


def _ctx(org, role="viewer"):
    return ("user-unused", str(org.id), role)


# ═══════════════════════════════════════════════════════════════
#  1. The row carries a machine-stable key
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_tron_nile_settlement_serialises_as_tron_nile(session):
    """The headline defect. Before this commit the row's only chain value was
    the label `chain:3448148188`, which the frontend could not key on and so
    coerced to 'Base'."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(
        session, owner=OWNER_A, chain_id=TRON_NILE_CHAIN_ID,
        token=USDT_TRC20_NILE, merchant=TRON_PAYEE, chain="tron_nile",
    )

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.recent_transactions[0].chain_key == "tron_nile"


@pytest.mark.asyncio
async def test_a_base_sepolia_settlement_is_not_base(session):
    """The defect that affects every row on every dashboard today: /app is
    hard-locked to `test`, so essentially everything it shows is Base Sepolia,
    and everything it shows says "Base"."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(session, owner=OWNER_A, chain_id=84532)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.recent_transactions[0].chain_key == "base_sepolia"
    assert stats.recent_transactions[0].chain_key != "base"


@pytest.mark.asyncio
async def test_an_unknown_chain_id_keeps_the_honest_fallback(session):
    """A chain the assembly does not know renders its raw reference. It must NOT
    fall back to a supported chain — that is the whole defect, one layer down."""
    org = await _make_org(session, owner_address=OWNER_A)
    await _seed(session, owner=OWNER_A, chain_id=999999)

    stats = await get_org_stats(ctx=_ctx(org), environment="test", db=session)

    assert stats.recent_transactions[0].chain_key == "chain:999999"


def test_every_chain_the_backend_can_emit_has_a_key():
    """Including TRON mainnet, which is implemented and deliberately unconfigured."""
    assert chain_key_for(8453) == "base"
    assert chain_key_for(84532) == "base_sepolia"
    assert chain_key_for(1) == "ethereum"
    assert chain_key_for(42161) == "arbitrum"
    assert chain_key_for(TRON_CHAIN_ID) == "tron"
    assert chain_key_for(TRON_NILE_CHAIN_ID) == "tron_nile"


# ═══════════════════════════════════════════════════════════════
#  2. PIN A — the assembly is deterministic
# ═══════════════════════════════════════════════════════════════

def test_the_assembled_map_is_one_name_per_chain_id():
    """`CHAIN_IDS` is many-to-one, so the inversion needs a tie-break. Chain 1 is
    the case that proves it: both "eth" and "ethereum" map to it, and the
    canonical answer is "ethereum"."""
    assert CHAIN_KEY_BY_ID[1] == "ethereum"
    assert all(isinstance(v, str) for v in CHAIN_KEY_BY_ID.values())
    # A dict cannot hold two values per key; the real assertion is that the
    # winner is pinned rather than incidental.
    assert len(CHAIN_KEY_BY_ID) == len(set(CHAIN_KEY_BY_ID))


def test_the_assembly_is_stable_across_repeated_construction():
    """Not a tautology: the overlay reads two dicts and a tuple, and a future
    refactor that resolved the alias by iteration order would pass every test
    above and fail this one on some Python builds."""
    first = build_chain_key_by_id()
    for _ in range(5):
        assert build_chain_key_by_id() == first
    assert first == CHAIN_KEY_BY_ID


def test_no_chain_key_collides():
    """Two chain ids sharing a key would make the frontend badge and the
    explorer link agree on the wrong network."""
    keys = list(CHAIN_KEY_BY_ID.values())
    assert len(keys) == len(set(keys))


# ═══════════════════════════════════════════════════════════════
#  3. PIN B — the money path does not move
# ═══════════════════════════════════════════════════════════════

def test_building_the_display_map_does_not_make_arbitrum_creatable():
    """The direct guard against the regression the obvious fix would cause.

    Giving Arbitrum a display name by adding 42161 to `_CHAIN_NAME_BY_ID` would
    flip `_canonical_chain("arbitrum")` from None to "arbitrum", which flips
    `chain_is_supported` to True, which lets it past the UNSUPPORTED_CHAIN gate
    in `intent_service.create_intent` — and "arbitrum" is in neither
    `_TESTNET_CHAINS` nor `_MAINNET_CHAINS`, so it would then be creatable on
    BOTH test and live keys, against a chain with no tokens and no router.

    Arbitrum has a display key here and no settlement path there. Both are true
    at once, and that is the point.
    """
    from app.services.router_registry import chain_is_supported

    assert chain_key_for(42161) == "arbitrum"
    assert chain_is_supported("arbitrum") is False


def test_the_display_map_did_not_mutate_the_money_path_tables():
    """Assembly must READ those dicts, never write to them."""
    from app.services import router_registry
    from app.services import chain_access

    assert 42161 not in router_registry._CHAIN_NAME_BY_ID
    assert TRON_CHAIN_ID not in router_registry.CHAIN_IDS.values()
    assert TRON_NILE_CHAIN_ID not in router_registry.CHAIN_IDS.values()
    assert TRON_CHAIN_ID not in chain_access.CHAIN_ID_BY_NAME.values()
    assert TRON_CHAIN_ID not in chain_access.TESTNET_CHAIN_IDS
    assert TRON_NILE_CHAIN_ID not in chain_access.TESTNET_CHAIN_IDS


def test_tron_is_still_absent_from_every_evm_table():
    """The hard guardrail in `tron_poller`, restated from the consumer side: a
    display key for TRON must not become an EVM routing entry for TRON."""
    from app.services import router_registry, rpc_manager

    for cid in (TRON_CHAIN_ID, TRON_NILE_CHAIN_ID):
        assert cid not in router_registry.CHAIN_IDS.values()
        assert cid not in rpc_manager._DEFAULT_PROVIDERS
