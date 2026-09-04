"""P0-1 — the request idempotency cache key must be tenant-scoped.

The key built at `app/middleware/idempotency.py` is derived from the request
path and the CLIENT-SUPPLIED `X-Idempotency-Key` header alone. Two merchants
that send the same key string to the same path within the 24h TTL therefore
collide on one Redis record, and the second one receives the FIRST one's
cached response — recipient address and calldata included. That is a
cross-tenant data leak on the money path, live the moment a second merchant
exists.

This module pins the key's composition: `(tenant, environment, path, idem_key)`,
with the request-body fingerprint stored ALONGSIDE the record rather than inside
the key (a body in the key would make a byte-different retry MISS the cache and
create a second intent — precisely what idempotency exists to prevent).

Harness: a minimal app carrying ONLY `IdempotencyMiddleware`, plus a 6-line
stand-in for `APIKeyMiddleware` that populates `request.state.client` the way the
real one does (`api_auth.py:79`). The rate limiter is deliberately NOT mounted:
in production it sits INSIDE idempotency (`main.py:305` vs `:314`) and is itself
fail-closed, so a 503 in the real stack is ambiguous between the two layers.
Here it cannot be — and the assertions still discriminate on the error CODE so
they stay honest if this app ever grows the limiter.

Redis is the real one (local / CI `redis:7`); every test uses a `uuid4()` idem
key so no case can observe another's record.

The merchant route mounted here is the REAL `create_payment_intent`, so
"no second intent row" is asserted against actual `payment_intents` rows.
"""

import secrets
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.merchant_routes import create_payment_intent
from app.config import get_settings
from app.db.session import async_session, engine
from app.middleware.idempotency import IdempotencyMiddleware
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import PaymentIntent, PaymentIntentResponse
from app.models.org_models import Membership, Organization
from app.models.user_wallets_models import UserWallet

# Two distinct merchants. Different owner wallets AND different settlement
# wallets, so a leaked response is visible in the `recipient` field.
OWNER_A = "0xaaaa35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE_A = "0x1111111111111111111111111111111111111111"
OWNER_B = "0xbbbb35cc6634c0532925a3b844bc9e7595f2bd18"
SETTLE_B = "0x2222222222222222222222222222222222222222"

MERCHANT_PATH = "/api/v1/merchant/payment-intent"
OTHER_MERCHANT_PATH = "/api/v1/merchant/webhook/test"
SESSION_PATH = "/api/v1/user/org/echo"


# ── DB fixture: create_all + FK-ordered ROW wipe (children first) ─────────
# No drop_all — the shared Postgres carries tables outside this module's
# metadata and a drop dies on their FKs (the known drop_all gotcha).

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import PaymentIntentRecipient
    from app.models.settlement_models import PaymentSettlement

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table in (
            PaymentIntentRecipient.__table__,
            PaymentSettlement.__table__,
            PaymentIntent.__table__,
            UserWallet.__table__,
            Membership.__table__,
            Organization.__table__,
            User.__table__,
        ):
            await conn.execute(table.delete())
    yield


@pytest_asyncio.fixture(autouse=True)
async def _isolate_redis_pool():
    """`cache_service` caches a module-global Redis pool (and circuit-breaker
    state) bound to the loop that created it, while pytest-asyncio gives every
    test its own loop. A pool built by an earlier test therefore raises here —
    and the middleware's fail-open arm swallows that as a warning, silently
    voiding every assertion in this module (three consecutive raises also trip
    the breaker OPEN for 15s, so the damage outlives the offending test).

    conftest resets the SQLAlchemy engine per test for exactly this reason
    (`_isolate_engine_per_test`) but not Redis. Same treatment.
    """
    import app.services.cache_service as cs

    async def _reset():
        if cs._pool is not None:
            try:
                await cs._pool.aclose()
            except Exception:
                pass
        cs._pool = None
        cs._rcb_state = cs._RedisCBState.CLOSED
        cs._rcb_failure_count = 0

    await _reset()
    yield
    await _reset()


@pytest.fixture(autouse=True)
def _neutralize_downstream(monkeypatch):
    """Neutralize effects DOWNSTREAM of the middleware under test (the live
    on-chain fee read in the response builder, and the audit write). The
    idempotency middleware itself is deliberately NOT patched."""
    import app.api.merchant_routes as mr

    async def _no_onchain(intent):
        return None

    async def _no_log(*a, **k):
        return None

    monkeypatch.setattr(mr, "build_onchain_payment", _no_onchain)
    monkeypatch.setattr(mr, "log_event", _no_log)


# ── The app under test ───────────────────────────────────────────────────

def _build_app(*, with_idempotency: bool = True) -> FastAPI:
    """Minimal app: the real merchant create route + two echo stubs.

    `with_idempotency=False` is the mocked-open CONTROL — same app, same
    requests, middleware absent.
    """
    app = FastAPI()

    app.post(MERCHANT_PATH, response_model=PaymentIntentResponse)(create_payment_intent)

    @app.post(OTHER_MERCHANT_PATH)
    async def _stub_merchant(request: Request):
        client = getattr(request.state, "client", None) or {}
        return {"who": client.get("client_id"), "env": client.get("environment")}

    @app.post(SESSION_PATH)
    async def _stub_session(request: Request):
        # Echoes the caller's own token tail: a leaked reply is one bearing
        # somebody else's tail. Identical bodies, so the fingerprint check is
        # not what separates these two callers — the tenant key is.
        return {"who": request.headers.get("authorization", "")[-10:]}

    if with_idempotency:
        app.add_middleware(IdempotencyMiddleware)

    # Stand-in for APIKeyMiddleware — added last, so it runs OUTERMOST and
    # `request.state.client` is populated before idempotency reads it, exactly
    # as in main.py (:330 vs :314).
    @app.middleware("http")
    async def _inject_client(request: Request, call_next):
        client_id = request.headers.get("X-Test-Client-Id")
        if client_id:
            request.state.client = {
                "client_id": client_id,
                "environment": request.headers.get("X-Test-Env", "test"),
                "scope": "write",
            }
        return await call_next(request)

    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── Fixtures / helpers ───────────────────────────────────────────────────

async def _make_org(*, owner: str, settlement: str) -> None:
    async with async_session() as s:
        user = User(
            id=str(uuid4()),
            email=f"{secrets.token_hex(6)}@example.com",
            account_type="individual",
        )
        s.add(user)
        await s.flush()
        org = Organization(
            name="Org " + secrets.token_hex(3),
            slug=secrets.token_hex(8),
            owner_user_id=user.id,
            is_personal=False,
            plan="free",
            settlement_wallet=settlement,
        )
        s.add(org)
        await s.flush()
        s.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        s.add(
            UserWallet(
                user_id=user.id,
                org_id=org.id,
                address=owner,
                display_address=owner,
                verified_chain_id=84532,
                is_primary=True,
                chain_family="evm",
            )
        )
        await s.commit()


def _body(amount: float = 10.0, **kw) -> dict:
    d = {"amount": amount, "currency": "USDC", "chain": "base_sepolia"}
    d.update(kw)
    return d


def _headers(client_id: str, idem: str, env: str = "test") -> dict:
    return {
        "X-Test-Client-Id": client_id,
        "X-Test-Env": env,
        "X-Idempotency-Key": idem,
    }


async def _intent_count() -> int:
    async with async_session() as s:
        return (
            await s.execute(select(func.count()).select_from(PaymentIntent))
        ).scalar_one()


def _access_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "sid": secrets.token_hex(8), "typ": "access"},
        get_settings().auth_jwt_secret,
        algorithm="HS256",
    )


# ═══════════════════════════════════════════════════════════════════════
#  THE BUG — cross-tenant leak
# ═══════════════════════════════════════════════════════════════════════

async def test_two_clients_same_key_do_not_share_a_response():
    """P0-1. Merchant A and merchant B send the SAME idempotency key to the
    SAME path with an identical body. Each must receive its OWN intent, paying
    its OWN settlement wallet.

    Before the fix B receives A's cached response verbatim, so B's checkout
    points at A's recipient address — this assertion fails on `recipient`,
    which is the leak itself, not a missing import.
    """
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)
    await _make_org(owner=OWNER_B, settlement=SETTLE_B)
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app()) as c:
        ra = await c.post(MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, idem))
        rb = await c.post(MERCHANT_PATH, json=_body(), headers=_headers(OWNER_B, idem))

    assert ra.status_code == 200, ra.text
    assert rb.status_code == 200, rb.text
    assert ra.json()["recipient"] == SETTLE_A
    assert rb.json()["recipient"] == SETTLE_B, (
        "cross-tenant leak: B received A's recipient"
    )
    assert ra.json()["intent_id"] != rb.json()["intent_id"]
    assert await _intent_count() == 2


async def test_session_users_same_key_do_not_share_a_response():
    """Same leak on the session (JWT) surface. `/api/v1/user/` is exempt from
    APIKeyMiddleware, so `request.state.client` is absent there and every org
    would otherwise fall into one shared bucket. Identical bodies, so only the
    tenant component of the key can separate them."""
    idem = f"ORD-{uuid4()}"
    tok_a = _access_token(str(uuid4()))
    tok_b = _access_token(str(uuid4()))

    async with _client(_build_app()) as c:
        ra = await c.post(
            SESSION_PATH, json={"x": 1},
            headers={"Authorization": f"Bearer {tok_a}", "X-Idempotency-Key": idem},
        )
        rb = await c.post(
            SESSION_PATH, json={"x": 1},
            headers={"Authorization": f"Bearer {tok_b}", "X-Idempotency-Key": idem},
        )

    assert ra.json()["who"] == tok_a[-10:]
    assert rb.json()["who"] == tok_b[-10:], "cross-user leak on the session surface"


# ═══════════════════════════════════════════════════════════════════════
#  Replay / fingerprint
# ═══════════════════════════════════════════════════════════════════════

async def test_identical_retry_is_replayed_and_creates_no_second_row():
    """The whole point of the feature: same client, same key, byte-identical
    body → the first response comes back and NO second intent is born.

    Already true before the fix; kept as the regression guard that the tenant
    scoping must not break.
    """
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app()) as c:
        r1 = await c.post(MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, idem))
        r2 = await c.post(MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, idem))

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json()["intent_id"] == r1.json()["intent_id"]
    assert r2.headers.get("X-Idempotency-Replayed") == "true"
    assert await _intent_count() == 1


async def test_same_key_different_body_is_409_and_creates_no_second_row():
    """A key reused with a different payload is a client bug, and answering it
    with the first payload's response silently drops the second request. It
    must be a 409 — never a new intent, never a misleading replay.

    Before the fix the second call gets a 200 carrying the FIRST body's amount.
    """
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app()) as c:
        r1 = await c.post(
            MERCHANT_PATH, json=_body(amount=10.0), headers=_headers(OWNER_A, idem)
        )
        r2 = await c.post(
            MERCHANT_PATH, json=_body(amount=99.0), headers=_headers(OWNER_A, idem)
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409, r2.text
    # Flat envelope — matches DUPLICATE_REQUEST_IN_FLIGHT, its neighbour in the
    # same middleware. Route-raised 409s use the {"detail": {...}} form; this is
    # not one of those.
    assert r2.json()["error"] == "IDEMPOTENCY_KEY_REUSED"
    assert await _intent_count() == 1


# ═══════════════════════════════════════════════════════════════════════
#  The other two key components
# ═══════════════════════════════════════════════════════════════════════

async def test_same_key_different_environment_does_not_collide():
    """`test` and `live` keys of the SAME owner share `client_id`, so the
    environment must be its own component or a test-mode retry replays a live
    intent (and vice versa).

    Driven against the echo stub rather than the create route on purpose: a
    live-env create is refused upstream by the mainnet-activation gate
    (403 `mainnet_activation_required`), which would decide this test before the
    idempotency layer ever spoke. The claim here is about the KEY, so the
    handler is kept trivial and the two requests are otherwise identical.
    """
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app()) as c:
        r_test = await c.post(
            OTHER_MERCHANT_PATH, json={}, headers=_headers(OWNER_A, idem, env="test")
        )
        r_live = await c.post(
            OTHER_MERCHANT_PATH, json={}, headers=_headers(OWNER_A, idem, env="live")
        )

    assert r_test.json() == {"who": OWNER_A, "env": "test"}
    assert r_live.json() == {"who": OWNER_A, "env": "live"}, (
        "the test-environment response was replayed for a live-environment request"
    )


async def test_same_key_different_path_does_not_collide():
    """Already true before the fix — the path is the one component the key has
    always had. Regression guard so the rewrite does not drop it."""
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app()) as c:
        r1 = await c.post(MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, idem))
        r2 = await c.post(
            OTHER_MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, idem)
        )

    assert r1.status_code == 200, r1.text
    assert r2.json() == {"who": OWNER_A, "env": "test"}, (
        "the create response leaked onto another path"
    )


# ═══════════════════════════════════════════════════════════════════════
#  Fail-closed
# ═══════════════════════════════════════════════════════════════════════

async def test_redis_down_on_a_merchant_route_fails_closed(monkeypatch):
    """Merchant routes are financial: if idempotency cannot be verified the
    request must be refused, not waved through unprotected.

    Attribution is structural — the rate limiter (also fail-closed, also 503)
    is not mounted in this app — and the assertion still names the idempotency
    layer's own code so it cannot silently start passing for the limiter's
    reason.
    """
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)

    async def _no_redis():
        return None

    monkeypatch.setattr("app.middleware.idempotency.get_redis", _no_redis)

    async with _client(_build_app()) as c:
        r = await c.post(
            MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, f"ORD-{uuid4()}")
        )

    assert r.status_code == 503, r.text
    assert r.json()["error"] == "SERVICE_TEMPORARILY_UNAVAILABLE"
    assert await _intent_count() == 0


async def test_redis_down_on_a_parameterised_merchant_route_fails_closed(monkeypatch):
    """`/payment-intent/{id}/cancel` and `/resolve` are financial too. The old
    exact-match set could never match them — only prefix matching can."""
    async def _no_redis():
        return None

    monkeypatch.setattr("app.middleware.idempotency.get_redis", _no_redis)

    app = _build_app()

    @app.post("/api/v1/merchant/payment-intent/{intent_id}/cancel")
    async def _stub_cancel(intent_id: str):
        return {"cancelled": intent_id}

    async with _client(app) as c:
        r = await c.post(
            "/api/v1/merchant/payment-intent/pi_abc/cancel",
            json={},
            headers=_headers(OWNER_A, f"ORD-{uuid4()}"),
        )

    assert r.status_code == 503, r.text
    assert r.json()["error"] == "SERVICE_TEMPORARILY_UNAVAILABLE"


# ═══════════════════════════════════════════════════════════════════════
#  CONTROL — every rejection above is the idempotency layer's
# ═══════════════════════════════════════════════════════════════════════

async def test_control_without_the_middleware_both_requests_go_through():
    """Same app, same two requests, middleware absent → BOTH reach the handler
    and TWO rows are born. This is what proves the 409 and the replay above are
    the idempotency layer's doing and not some earlier validation firing first.

    The amounts differ deliberately: migration 0019's `uq_intent_pending_amount`
    rejects a second PENDING intent on the same
    (merchant_id, environment, chain, currency, amount). With equal amounts this
    control would "pass" because the DB refused the row — for the wrong reason.
    """
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)
    idem = f"ORD-{uuid4()}"

    async with _client(_build_app(with_idempotency=False)) as c:
        r1 = await c.post(
            MERCHANT_PATH, json=_body(amount=10.0), headers=_headers(OWNER_A, idem)
        )
        r2 = await c.post(
            MERCHANT_PATH, json=_body(amount=99.0), headers=_headers(OWNER_A, idem)
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["intent_id"] != r2.json()["intent_id"]
    assert await _intent_count() == 2


async def test_control_redis_down_without_the_middleware_still_creates_the_row(
    monkeypatch,
):
    """Companion control for the fail-closed pins: with the middleware absent,
    a dead Redis does not stop the create. So the 503s above are the
    idempotency layer refusing, not the request being invalid."""
    await _make_org(owner=OWNER_A, settlement=SETTLE_A)

    async def _no_redis():
        return None

    monkeypatch.setattr("app.middleware.idempotency.get_redis", _no_redis)

    async with _client(_build_app(with_idempotency=False)) as c:
        r = await c.post(
            MERCHANT_PATH, json=_body(), headers=_headers(OWNER_A, f"ORD-{uuid4()}")
        )

    assert r.status_code == 200, r.text
    assert await _intent_count() == 1
