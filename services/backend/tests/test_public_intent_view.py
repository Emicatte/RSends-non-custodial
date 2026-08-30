"""Limited public status view for the hosted checkout (/pay).

Access model: id-as-secret. `intent_id` is "pi_" + secrets.token_hex(16)
(128 bits, non-enumerable), so whoever holds the /pay link may read that ONE
intent's pay-relevant fields — and nothing merchant-private. The dedicated
endpoint `GET /api/v1/public/payment-intent/{intent_id}`:

- serializes an explicit field allowlist (never the ORM object) — leak guard
  asserts the exact key set;
- is read-only (an expired-pending intent is REPORTED as expired without
  persisting the flip — unlike the merchant GET);
- is per-IP rate limited (unauthenticated → per-IP, not per-key);
- 404s on miss, single-object only (no list, no enumeration);
- replaces the GET_PUBLIC_PREFIXES exception on the merchant route, which
  goes back to fully fail-closed (unauth GET → 401).

Direct-handler tests + TestClient middleware tests, same styles as
tests/test_merchant_env_isolation.py and tests/test_get_deny_by_default.py.
"""

import secrets
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.db_models import Base
from app.models.merchant_models import IntentStatus, PaymentIntent
from app.api.public_routes import get_public_payment_intent, public_router
from app.services.router_registry import to_base_units

OWNER = "0x742d35cc6634c0532925a3b844bc9e7595f2bd18"

# The complete public contract. Anything beyond this is a leak.
PUBLIC_FIELDS = {
    "status", "amount", "currency", "chain", "expires_at",
    "merchant_name", "tx_hash", "onchain",
    # Watch-only chains have no `onchain` block, so these four ARE the payment
    # instruction there: where to send, how much exactly, and what has arrived.
    "recipient", "amount_exact", "amount_received", "underpaid_amount",
}

# A real TRON mainnet address (the USDT TRC-20 contract), used purely as a
# well-formed base58check value. Mixed case is the point: base58 excludes
# 0 O I l, so folding it does not produce a different address, it produces a
# string that no longer decodes.
TRON_PAYEE = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


# ── Fixtures ─────────────────────────────────────────────────

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
def _no_rpc(monkeypatch):
    """Public view builds onchain instructions like the merchant GET — stub the
    live fee RPC out."""
    async def _none(intent):
        return None

    monkeypatch.setattr("app.api.public_routes.build_onchain_payment", _none)


def _intent(
    *,
    status: IntentStatus = IntentStatus.pending,
    expires_in_minutes: int = 30,
    metadata: dict | None = None,
    tx_hash: str | None = None,
    matched_tx_hash: str | None = None,
    amount: float = 100.0,
    currency: str = "USDC",
    chain: str = "base",
    recipient: str | None = None,
    amount_received: str | None = None,
    underpaid_amount: str | None = None,
) -> PaymentIntent:
    # amount_received carries a column default of "0"; pass it only when the
    # test actually wants a value, so the default is exercised otherwise.
    observed = {
        k: v
        for k, v in (
            ("amount_received", amount_received),
            ("underpaid_amount", underpaid_amount),
        )
        if v is not None
    }
    return PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=OWNER,
        environment="live",
        amount=amount,
        currency=currency,
        chain=chain,
        recipient=recipient,
        status=status,
        metadata_=metadata,
        expected_sender="0x00000000000000000000000000000000000000aa",
        tx_hash=tx_hash,
        matched_tx_hash=matched_tx_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        **observed,
    )


# ── limited view, no auth ────────────────────────────────────

@pytest.mark.asyncio
async def test_public_view_returns_limited_fields(session):
    """A valid id with NO auth returns the pay-relevant view."""
    intent = _intent(metadata={"merchant_name": "Caffè Emi", "order_ref": "secret-42"})
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)

    assert resp.status == "pending"
    assert resp.amount == 100.0
    assert resp.currency == "USDC"
    assert resp.chain == "base"
    assert resp.merchant_name == "Caffè Emi"


@pytest.mark.asyncio
async def test_public_view_leaks_nothing(session):
    """The serialized key set IS the contract — no merchant-private field."""
    intent = _intent(metadata={"merchant_name": "Caffè Emi", "customer_email": "x@y.z"})
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)
    dumped = resp.model_dump()

    assert set(dumped.keys()) == PUBLIC_FIELDS
    flat = str(dumped)
    assert "customer_email" not in flat
    assert intent.reference_id not in flat
    assert intent.expected_sender not in flat
    assert intent.intent_id not in flat            # already in the URL; not echoed
    assert OWNER not in flat                        # merchant_id never exposed


@pytest.mark.asyncio
async def test_merchant_name_falls_back_and_stays_optional(session):
    # Distinct amounts — uq_intent_pending_amount forbids two pending intents
    # sharing (merchant_id, environment, chain, currency, amount); these two
    # agree on all of it. Only merchant_name is asserted.
    store = _intent(metadata={"store_name": "Bottega"}, amount=100.0)
    bare = _intent(amount=101.0)
    session.add_all([store, bare])
    await session.commit()

    assert (await get_public_payment_intent(store.intent_id, db=session)).merchant_name == "Bottega"
    assert (await get_public_payment_intent(bare.intent_id, db=session)).merchant_name is None


@pytest.mark.asyncio
async def test_tx_hash_prefers_matched_settlement(session):
    intent = _intent(
        status=IntentStatus.completed,
        tx_hash="0x" + "11" * 32,
        matched_tx_hash="0x" + "22" * 32,
    )
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)
    assert resp.tx_hash == "0x" + "22" * 32


# ── watch-only: the address IS the payment instruction ───────

@pytest.mark.asyncio
async def test_tron_recipient_round_trips_byte_identical(session):
    """A base58check payee survives the public view with its case intact.

    This is the whole reason the field exists. `onchain` is null on a
    watch-only chain, so this string is the only thing telling the payer where
    to send; base58 has no 0 O I l, so a folded T-address does not decode at
    all, and the matcher compares `recipient == settlement.merchant` with no
    folding on either side.
    """
    intent = _intent(currency="USDT", chain="TRON", recipient=TRON_PAYEE)
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)

    assert resp.recipient == TRON_PAYEE
    assert resp.recipient != TRON_PAYEE.lower()      # nothing folded it
    assert resp.recipient != TRON_PAYEE.upper()


@pytest.mark.asyncio
async def test_amount_exact_is_what_the_matcher_expects(session):
    """The decimal the payer retypes converts to the base units we compare.

    Asserted through `to_base_units` rather than against a literal, because the
    promise is agreement with the settlement layer, not a particular spelling.
    """
    intent = _intent(
        currency="USDT", chain="TRON", recipient=TRON_PAYEE, amount=10.000001,
    )
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)

    assert resp.amount_exact == "10.000001"
    assert to_base_units(float(resp.amount_exact), 6) == to_base_units(intent.amount, 6)


@pytest.mark.asyncio
async def test_amount_exact_never_uses_scientific_notation(session):
    """A payer cannot paste "1e-06" into a wallet."""
    intent = _intent(
        currency="USDT", chain="TRON", recipient=TRON_PAYEE, amount=0.000001,
    )
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)
    assert resp.amount_exact == "0.000001"
    assert "e" not in resp.amount_exact.lower()


@pytest.mark.asyncio
async def test_amount_exact_is_null_for_an_unregistered_token(session):
    """No known scale means no number — never one derived from a guess."""
    intent = _intent(currency="NOPE", chain="base")
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)
    assert resp.amount_exact is None


@pytest.mark.asyncio
async def test_partial_carries_received_and_missing(session):
    """The two numbers the partial card is built from, as the matcher wrote them."""
    intent = _intent(
        status=IntentStatus.partial,
        currency="USDT",
        chain="TRON",
        recipient=TRON_PAYEE,
        amount=10.0,
        amount_received="4.5",
        underpaid_amount="5.5",
        matched_tx_hash="a" * 64,
    )
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)

    assert resp.status == "partial"
    assert resp.amount_received == "4.5"
    assert resp.underpaid_amount == "5.5"
    assert resp.tx_hash == "a" * 64


@pytest.mark.asyncio
async def test_evm_intent_keeps_its_shape(session):
    """Regression pin: the router-chain view is unchanged except for the
    additions, and a split intent (no single payee) reports a null recipient."""
    intent = _intent(recipient=None)
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)

    assert resp.recipient is None
    assert resp.amount_exact == "100"          # USDC, 6 decimals
    assert resp.amount_received == "0"         # column default, never written on EVM
    assert resp.underpaid_amount is None


# ── 404 on miss, single-object only ──────────────────────────

@pytest.mark.asyncio
async def test_unknown_id_404(session):
    with pytest.raises(HTTPException) as exc:
        await get_public_payment_intent(f"pi_{secrets.token_hex(16)}", db=session)
    assert exc.value.status_code == 404
    assert exc.value.detail["error"] == "INTENT_NOT_FOUND"


def test_no_list_or_enumeration_route():
    """The public router exposes exactly one single-object GET."""
    app = FastAPI()
    app.include_router(public_router)
    routes = [
        (r.path, sorted(r.methods))
        for r in app.routes
        if r.path.startswith("/api/v1/public")
    ]
    assert routes == [("/api/v1/public/payment-intent/{intent_id}", ["GET"])]


# ── read-only: expiry reported, never persisted ──────────────

@pytest.mark.asyncio
async def test_expired_pending_reported_not_persisted(session):
    intent = _intent(expires_in_minutes=-5)          # already past expiry
    session.add(intent)
    await session.commit()

    resp = await get_public_payment_intent(intent.intent_id, db=session)
    assert resp.status == "expired"

    row = (await session.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == intent.intent_id)
    )).scalar_one()
    assert row.status == IntentStatus.pending        # public route wrote nothing


# ── middleware: auth boundary ────────────────────────────────

class _Settings:
    api_get_deny_by_default = True


def _mw_client(monkeypatch):
    """APIKeyMiddleware with the REAL is_get_public path functions, stub handlers."""
    from app.middleware.api_auth import APIKeyMiddleware

    async def _verify(_request):
        return None

    monkeypatch.setattr("app.middleware.api_auth.verify_api_key", _verify)
    monkeypatch.setattr("app.middleware.api_auth.get_settings", lambda: _Settings())
    monkeypatch.delenv("RSEND_DEV_AUTH_BYPASS", raising=False)

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/v1/public/payment-intent/{intent_id}")
    async def _public(intent_id: str):
        return {"ok": "public"}

    @app.get("/api/v1/merchant/payment-intent/{intent_id}")
    async def _merchant(intent_id: str):
        return {"ok": "merchant"}

    return TestClient(app, raise_server_exceptions=False)


def test_public_path_passes_middleware_unauthenticated(monkeypatch):
    c = _mw_client(monkeypatch)
    assert c.get("/api/v1/public/payment-intent/pi_deadbeef").status_code == 200


def test_merchant_get_no_longer_public(monkeypatch):
    """The old checkout allowlist exception is gone — merchant GET fails closed."""
    c = _mw_client(monkeypatch)
    assert c.get("/api/v1/merchant/payment-intent/pi_deadbeef").status_code == 401


# ── middleware: per-IP rate limit ────────────────────────────

def test_public_view_per_ip_rate_limited(monkeypatch):
    """21st request in the window from one IP → 429 (20/min per-IP rule)."""
    from app.middleware.rate_limit import RateLimitMiddleware

    async def _redis_down(*a, **k):
        raise ConnectionError("no redis in tests")

    # Force the deterministic in-memory limiter (debug mode allows the fallback).
    monkeypatch.setattr("app.middleware.rate_limit._check_redis", _redis_down)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/api/v1/public/payment-intent/{intent_id}")
    async def _public(intent_id: str):
        return {"ok": True}

    c = TestClient(app, raise_server_exceptions=False)
    url = f"/api/v1/public/payment-intent/pi_{secrets.token_hex(16)}"

    codes = [c.get(url).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20
    assert codes[20] == 429
