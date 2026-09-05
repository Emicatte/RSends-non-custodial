"""The source-wallet registration gates — RED-first pins for RSendsAutoSplit.

RSendsAutoSplit is ownerless: no on-chain token whitelist, no owner surface
(`packages/contracts/src/RSendsAutoSplit.sol`, header lines 37-45 delegate
token enforcement to the backend explicitly). The ONLY things preventing a
keeper watch row from being born on a weird token or an impossible chain are
the gates in `source_wallet_service.register_source_wallet`, in this order:

  chain_is_supported      -> 400 UNSUPPORTED_CHAIN
  auto_split_address_for  -> 422 AUTO_SPLIT_UNAVAILABLE   (fail-closed None)
  token_is_enabled        -> 400 UNSUPPORTED_TOKEN

The token gate alone is NOT sufficient: `token_is_enabled("tron", "USDT")` is
True (pinned by test_tron_watchonly_intent.py) but tron is watch_only with
base58check addresses and AutoSplit is an EVM contract — the AutoSplit chain
gate is the line that holds there. And no Pydantic symbol whitelist exists on
this surface at all (deliberately — the registry gate is the single source,
never a second drifting set).

Each rejection pin has a CONTROL proving the rejection is attributable to the
named gate (with the gate mocked open the identical request succeeds) — never
a constant compared with itself. Gate mocks patch the OWNING module
`app.services.source_wallet_service`; SIWE is stubbed on the route module
(the suite-wide `stub_siwe` idiom from test_user_wallets_uniqueness.py — no
test signs a real SIWE message).

Imports of the not-yet-built modules happen INSIDE fixtures/tests so each
test fails RED with its own ModuleNotFoundError instead of one collection
crash. Direct-handler harness mirrored from test_creation_token_gate.py.
"""

import secrets
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.org_models import Membership, Organization

ADDR = "0x" + "a" * 40
AUTOSPLIT_ADDR = "0x" + "5" * 40
CHAIN = "base_sepolia"
# A real base58check wallet (checksum-valid, not a token contract, not the TRON
# zero address). Needed because the address family is now validated against the
# chain: an 0x address on a TRON chain no longer reaches the AutoSplit gate.
TRON_ADDR = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """create_all + FK-ordered ROW wipe (children first) — no drop_all: the
    shared Postgres carries tables outside this module's metadata and a drop
    dies on their FKs (the known drop_all gotcha)."""
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


@pytest.fixture
def stub_siwe(monkeypatch):
    """SIWE verification and the best-effort audit write are the route's only
    externals — stub both on the ROUTE module so the tests exercise the gate
    + DB path. The gates themselves are deliberately NOT patched here."""
    import app.api.source_wallet_routes as swr

    async def _ok(**kwargs):
        return "siwe-message"

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr(swr, "verify_challenge", _ok)
    monkeypatch.setattr(swr, "record_auth_event", _noop)


def _verify_payload(*, chain=CHAIN, token_symbol="USDC", address=ADDR, label=None):
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    return SourceWalletVerifyRequest(
        chain=chain,
        token_symbol=token_symbol,
        address=address,
        nonce=secrets.token_hex(8),
        signature="0x" + "1" * 130,
        label=label,
    )


async def _verify(session, ctx, **payload_kw):
    from app.api.source_wallet_routes import post_verify

    return await post_verify(
        payload=_verify_payload(**payload_kw), ctx=ctx, db=session
    )


async def _row_count(session) -> int:
    from app.models.source_wallet_models import SourceWallet

    return (
        await session.execute(select(func.count()).select_from(SourceWallet))
    ).scalar_one()


def _open_autosplit(monkeypatch):
    """The AutoSplit chain gate sits BEFORE the token gate and is fail-closed
    None on every unconfigured chain — mock it open so a LATER gate can be the
    deciding check, on any chain, without depending on the address map."""
    import app.services.source_wallet_service as svc

    monkeypatch.setattr(svc, "auto_split_address_for", lambda chain: AUTOSPLIT_ADDR)


@pytest.fixture
def autosplit_configured(monkeypatch):
    """The operator env flip: RSendsAutoSplit deployed on base_sepolia only.

    Nothing is mocked — this patches the raw AUTO_SPLIT_ADDRESSES_JSON string
    on the cached settings (the `split_enabled` idiom from
    test_intent_split_gate.py; the parsed map is a property that re-parses per
    access, so no cache clearing) and lets the real resolver run. Tests using
    this fixture exercise the shipping code path, not a stub of it.
    """
    from app.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "auto_split_addresses_json",
        '{"' + CHAIN + '": "' + AUTOSPLIT_ADDR + '"}',
    )


# ── Token gate: rejects both flavors, control proves attribution ──────────


@pytest.mark.asyncio
async def test_unregistered_token_rejected_no_row(session, stub_siwe, monkeypatch):
    """Registry-ABSENT token (DEGEN) → 400 UNSUPPORTED_TOKEN, no row born.
    AutoSplit gate mocked open so the token gate is the deciding check."""
    _open_autosplit(monkeypatch)
    user_id, org_id = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_id, org_id, "admin"), token_symbol="DEGEN")
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_TOKEN"
    assert await _row_count(session) == 0


@pytest.mark.asyncio
async def test_disabled_token_rejected_no_row(session, stub_siwe, monkeypatch):
    """Registry-PRESENT but disabled token (DAI on base, enabled=false) →
    same 400, no row."""
    _open_autosplit(monkeypatch)
    user_id, org_id = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _verify(
            session, (user_id, org_id, "admin"), chain="base", token_symbol="DAI"
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_TOKEN"
    assert await _row_count(session) == 0


@pytest.mark.asyncio
async def test_control_token_gate_mocked_open_succeeds(session, stub_siwe, monkeypatch):
    """With the token gate ALSO mocked open, the byte-identical DEGEN request
    succeeds — the rejections above are the token gate's and nobody else's.
    Patches the OWNING service module, never a re-imported alias (the
    merchant_routes dead-import no-op trap)."""
    import app.services.source_wallet_service as svc

    _open_autosplit(monkeypatch)
    monkeypatch.setattr(svc, "token_is_enabled", lambda chain, cur: True)
    user_id, org_id = await _make_org(session)

    await _verify(session, (user_id, org_id, "admin"), token_symbol="DEGEN")

    from app.models.source_wallet_models import SourceWallet

    row = (await session.execute(select(SourceWallet))).scalar_one()
    assert row.token_symbol == "DEGEN"


# ── AutoSplit chain gate: the token gate alone is not sufficient ──────────


@pytest.mark.asyncio
async def test_unknown_chain_rejected_no_row(session, stub_siwe):
    """A chain the registry has never heard of → 400 UNSUPPORTED_CHAIN."""
    user_id, org_id = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _verify(session, (user_id, org_id, "admin"), chain="dogechain")
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "UNSUPPORTED_CHAIN"
    assert await _row_count(session) == 0


@pytest.mark.asyncio
async def test_supported_chain_without_autosplit_rejected(
    session, stub_siwe, autosplit_configured
):
    """chain=tron, token=USDT: chain IS supported and the token IS enabled
    (token_is_enabled("tron","USDT") is True — the counterexample proving the
    token gate insufficient), but no AutoSplit ADDRESS is configured there →
    422 AUTO_SPLIT_UNAVAILABLE, no row.

    `autosplit_configured` is the load-bearing part. Before the address map was
    wired this test passed because auto_split_address_for returned None for
    EVERY chain — the refusal was real but unattributable, and would have
    survived the gate being deleted. The map is configured for real here, so
    the assertions below are non-vacuous: base_sepolia resolves in the very
    same environment in which tron does not.

    Note carefully what is NOT being asserted, because this test used to assert
    it: that TRON is ineligible for Auto Split. It is eligible — the contract
    compiles and runs there — and the refusal is no longer "tron is watch_only"
    but simply "no address is configured for this chain", exactly what
    base_sepolia would get from an empty map. The map is the gate.

    The address is a real TRON one, and that is also a change. Passing an EVM
    address here used to be deliberate ("the CHAIN gate must be the rejector,
    not the address regex"), a premise the address-family dispatch has since
    made obsolete: an 0x address on a TRON chain is now refused at PARSE, so it
    would never reach the AutoSplit gate and this test would be asserting the
    wrong rejection. Both gates are real; each has its own test, and
    `test_address_from_the_wrong_family_is_refused_at_parse` is the other one.
    """
    from app.services.router_registry import token_is_enabled
    from app.services.source_wallet_service import auto_split_address_for

    assert token_is_enabled("tron", "USDT") is True  # the trap being pinned
    # …and the feature is NOT simply off everywhere — the control that makes
    # the refusal below attributable to tron's absence from the map:
    assert auto_split_address_for(CHAIN) == AUTOSPLIT_ADDR
    assert auto_split_address_for("tron") is None

    user_id, org_id = await _make_org(session)
    with pytest.raises(HTTPException) as exc:
        await _verify(
            session,
            (user_id, org_id, "admin"),
            chain="tron",
            token_symbol="USDT",
            address=TRON_ADDR,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "AUTO_SPLIT_UNAVAILABLE"
    assert await _row_count(session) == 0


@pytest.mark.asyncio
async def test_address_from_the_wrong_family_is_refused_at_parse(session, stub_siwe):
    """An 0x address on a TRON chain, and a T-address on an EVM chain.

    The gate the test above used to stand in for. Dispatch is on the chain's
    declared `addressFormat`, never on the string's shape, so neither is
    migrated to the other family — a wallet the keeper will move funds out of
    is not something to guess about.
    """
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    def _build(chain, token_symbol, address):
        return SourceWalletVerifyRequest(
            chain=chain,
            token_symbol=token_symbol,
            address=address,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        )

    # Controls: each address is fine on its own chain.
    assert _build(CHAIN, "USDC", ADDR).address == ADDR
    assert _build("tron", "USDT", TRON_ADDR).address == TRON_ADDR

    with pytest.raises(ValidationError):
        _build("tron", "USDT", ADDR)
    with pytest.raises(ValidationError):
        _build(CHAIN, "USDC", TRON_ADDR)


@pytest.mark.asyncio
async def test_control_autosplit_gate_mocked_open_succeeds(session, stub_siwe, monkeypatch):
    """With ONLY auto_split_address_for mocked open, an otherwise-identical
    EVM request (base_sepolia + USDC) succeeds outright — attributing the
    422 above to the AutoSplit gate and not to some other layer."""
    _open_autosplit(monkeypatch)
    user_id, org_id = await _make_org(session)

    await _verify(session, (user_id, org_id, "admin"))
    assert await _row_count(session) == 1


@pytest.mark.asyncio
async def test_configured_chain_registers_with_nothing_mocked(
    session, stub_siwe, autosplit_configured
):
    """The positive half: base_sepolia + USDC registers through the REAL
    resolver reading the REAL address map — no gate is stubbed.

    The control above proves the 422 belongs to the AutoSplit gate; this proves
    the gate opens on the operator's env flip rather than only on a mock, and
    that the row is stamped with the address the map actually names.
    """
    from app.models.source_wallet_models import SourceWallet
    from app.services.source_wallet_service import resolve_registration_context

    user_id, org_id = await _make_org(session)

    await _verify(session, (user_id, org_id, "admin"))

    row = (await session.execute(select(SourceWallet))).scalar_one()
    assert row.chain == CHAIN
    assert row.environment == "test"
    assert row.token_symbol == "USDC"
    # The registration context the row was built from carries the configured
    # address — not a default, and not the mock the other tests inject.
    ctx = resolve_registration_context(CHAIN, "USDC")
    assert ctx["auto_split_address"] == AUTOSPLIT_ADDR


# ── Schema: the client can never name a token by address ──────────────────


def test_client_supplied_token_address_rejected_at_parse():
    """extra="forbid": a body carrying token_address — even the CORRECT USDC
    address — dies at parse, never read. Token resolution is exclusively
    server-side token_for(chain, symbol) (the API half of the contract
    header's obligation: no free token-address field, ever)."""
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    with pytest.raises(ValidationError):
        SourceWalletVerifyRequest(
            chain=CHAIN,
            token_symbol="USDC",
            address=ADDR,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
            token_address="0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        )


def test_zero_address_rejected_at_parse():
    """The zero address would burn the merchant's funds as a source wallet
    exactly as it would as a settlement wallet — reject, never coerce."""
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    with pytest.raises(ValidationError):
        SourceWalletVerifyRequest(
            chain=CHAIN,
            token_symbol="USDC",
            address="0x" + "0" * 40,
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        )


def test_malformed_address_rejected_at_parse():
    from app.models.source_wallet_schemas import SourceWalletVerifyRequest

    with pytest.raises(ValidationError):
        SourceWalletVerifyRequest(
            chain=CHAIN,
            token_symbol="USDC",
            address="0x1234",
            nonce=secrets.token_hex(8),
            signature="0x" + "1" * 130,
        )
