"""Auto-disable a webhook endpoint after three consecutive PERMANENT failures.

Production carries dead webhook.site endpoints that have 404'd for weeks. Every
payment fans out to all of them and each burns five attempts over ~2h42m of
backoff, producing permanent ERRORs that mean nothing. Nobody prunes them by
hand, so this is the steady state of a months-old merchant account.

THE RULE PINNED HERE
  permanent (counts): HTTP 404, HTTP 410, DNS resolution failure
                      (httpx.ConnectError whose __cause__ is socket.gaierror),
                      and egress-blocked
  transient (never counts, however often it repeats): 5xx, timeouts,
                      connection-refused, TLS failures
  * a delivery counts ONCE, at retry exhaustion; the FINAL attempt decides
  * three consecutive → is_active=False + disabled_reason + disabled_at + WARNING
  * any successful delivery resets the counter to 0

`disabled_reason` holds a STABLE CODE, not prose — the dashboard maps it to copy,
so wording can change or be translated without rewriting rows. The
`url_not_allowed:` prefix on the egress case exists so a merchant reads "we would
not contact this URL" rather than "your server misbehaved".

WHY THE HTTP HOP AND NOTHING ELSE IS STUBBED
`test_tron_matching.py`'s `real_dispatch` fixture monkeypatches `_attempt_delivery`
itself. That function IS the classification layer — egress check, status-code
branch, exception handling, retry accounting. Stubbing it here would hide the
exact behaviour under test. `_http` below patches
`webhook_service.httpx.AsyncClient` instead (the idiom of test_webhook_signing.py
and test_webhook_enhanced.py), so the real `send_webhook` → real webhook
selection → real `WebhookDelivery` insert → real `_attempt_delivery` all run.

MAX_RETRIES, BASE_BACKOFF_SECONDS and the idempotency key are NOT touched: the
ladder is driven by resetting `next_retry_at` into the past between poller passes,
which is sound because re-selection is gated only on
`status == pending AND next_retry_at <= now` (webhook_service.py:1137-1145).

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_webhook_auto_disable.py -v
"""

import asyncio
import logging
import secrets
import socket
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.session import async_session, engine
from app.models.auth_models import User
from app.models.db_models import Base
from app.models.merchant_models import (
    DeliveryStatus,
    IntentStatus,
    MerchantWebhook,
    PaymentIntent,
    WebhookDelivery,
)
from app.models.org_models import Membership, Organization
from app.models.user_wallets_models import UserWallet
from app.services import webhook_service as ws
from app.services.webhook_service import (
    MAX_RETRIES,
    process_pending_deliveries,
    send_webhook,
)

MERCHANT = "0x" + "a" * 40
ENVIRONMENT = "test"
EVENT = "payment.completed"
HOOK_URL = "https://merchant.example/hook"
OTHER_URL = "https://other.example/hook"

# Three consecutive permanent failures disable. Named here so a test reads as
# the rule rather than as a magic 3.
DISABLE_AFTER = 3


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
#  The HTTP hop — the ONLY thing stubbed
# ═══════════════════════════════════════════════════════════════

@contextmanager
def _http(*outcomes):
    """Patch `webhook_service.httpx.AsyncClient` and nothing else.

    Each outcome is an int status code or an exception INSTANCE. Outcomes are
    consumed in order; the last one repeats for every further call, so
    `_http(404)` means "404 for all five attempts" and `_http(500, 500, 404)`
    expresses a mixed ladder ending permanent.

    Yields the list of URLs posted to, so a test can assert an endpoint was
    never contacted.
    """
    seq = list(outcomes)
    posted: list[str] = []

    async def _post(url, *, content=None, headers=None, **kwargs):
        posted.append(url)
        outcome = seq[min(len(posted) - 1, len(seq) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        resp = MagicMock()
        resp.status_code = outcome
        resp.text = f"stubbed {outcome}"
        return resp

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        yield posted


def _dns_failure() -> httpx.ConnectError:
    """The name does not resolve. httpx wraps socket.gaierror in ConnectError."""
    exc = httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")
    exc.__cause__ = socket.gaierror(8, "nodename nor servname provided, or not known")
    return exc


def _connection_refused() -> httpx.ConnectError:
    """The host resolves and refuses. SAME exception class as _dns_failure —
    only __cause__ differs. This pair is what proves the classification
    discriminates on the cause and not on isinstance."""
    exc = httpx.ConnectError("[Errno 61] Connection refused")
    exc.__cause__ = ConnectionRefusedError(61, "Connection refused")
    return exc


def _read_timeout() -> httpx.ReadTimeout:
    return httpx.ReadTimeout("timed out")


# ═══════════════════════════════════════════════════════════════
#  Builders
# ═══════════════════════════════════════════════════════════════

async def _register_webhook(session, *, url=HOOK_URL, merchant_id=MERCHANT):
    wh = MerchantWebhook(
        merchant_id=merchant_id,
        environment=ENVIRONMENT,
        url=url,
        secret=secrets.token_hex(32),
        events=[EVENT],
        is_active=True,
    )
    session.add(wh)
    await session.commit()
    return wh.id


async def _make_intent(session, *, merchant_id=MERCHANT):
    """A settled intent — `payment.completed` is what a live endpoint receives.

    Deliberately NOT `pending`: 0019's `uq_intent_pending_amount` is unique over
    (merchant, env, chain, currency, amount) while pending, and these tests fan
    out several intents for one merchant.
    """
    now = datetime.now(timezone.utc)
    intent = PaymentIntent(
        intent_id=f"pi_{secrets.token_hex(16)}",
        reference_id=secrets.token_hex(8),
        merchant_id=merchant_id,
        environment=ENVIRONMENT,
        amount=10.0,
        currency="USDC",
        chain="base_sepolia",
        recipient="0x" + "c" * 40,
        status=IntentStatus.paid,
        created_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=30),
    )
    session.add(intent)
    await session.commit()
    return intent


async def _make_org(session, *, owner_address):
    """User+Org+Membership+primary wallet, so `_resolve_owner_address` resolves
    to `owner_address`. Same shape as test_webhook_reads.py:56-74."""
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
    session.add(UserWallet(
        user_id=user.id, org_id=org.id, address=owner_address,
        display_address=owner_address, verified_chain_id=84532,
        is_primary=True, chain_family="evm",
    ))
    await session.commit()
    return org


# ═══════════════════════════════════════════════════════════════
#  Driving one delivery to a terminal status
# ═══════════════════════════════════════════════════════════════

async def _deliver(session, *, outcome, merchant_id=MERCHANT):
    """Fan out ONE event and drive every delivery it creates to a terminal
    status under `outcome`. Returns the URLs that were actually POSTed to.

    No real backoff is waited on: `next_retry_at` is pushed into the past before
    each poller pass. The MAX_RETRIES exit returns before touching
    `next_retry_at`, so exhaustion genuinely ends the loop.
    """
    intent = await _make_intent(session, merchant_id=merchant_id)

    with _http(outcome) as posted:
        await send_webhook(
            session, merchant_id=merchant_id, event=EVENT, intent=intent,
        )
        # send_webhook already made attempt 1; MAX_RETRIES-1 poller passes finish
        # the ladder. The spare passes make a runaway visible as an assertion
        # rather than as a hang.
        for _ in range(MAX_RETRIES + 3):
            pending = (await session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.status == DeliveryStatus.pending
                )
            )).scalars().all()
            if not pending:
                break
            past = datetime.now(timezone.utc) - timedelta(seconds=1)
            for delivery in pending:
                delivery.next_retry_at = past
            await session.flush()
            await process_pending_deliveries(session)
        else:
            raise AssertionError(
                "deliveries never reached a terminal status — the retry ladder "
                "did not terminate"
            )

    await session.commit()
    return posted


async def _state(webhook_id):
    """Read the endpoint back in a FRESH session, so an assertion cannot pass on
    an identity-map artefact — the writes must really have been committed."""
    async with async_session() as db:
        wh = (await db.execute(
            select(MerchantWebhook).where(MerchantWebhook.id == webhook_id)
        )).scalar_one()
        return {
            "is_active": wh.is_active,
            "failures": wh.consecutive_permanent_failures,
            "reason": wh.disabled_reason,
            "disabled_at": wh.disabled_at,
        }


async def _delivery_count(webhook_id):
    async with async_session() as db:
        return len((await db.execute(
            select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook_id)
        )).scalars().all())


# ═══════════════════════════════════════════════════════════════
#  Permanent failures disable
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_three_consecutive_404s_disable_the_endpoint(session, caplog):
    """404 means the URL is not there. Three deliveries' worth of it — fifteen
    attempts over hours — is not a bad afternoon, it is a dead endpoint."""
    wid = await _register_webhook(session)

    with caplog.at_level(logging.WARNING, logger="app.services.webhook_service"):
        for _ in range(DISABLE_AFTER):
            await _deliver(session, outcome=404)

    state = await _state(wid)
    assert state["is_active"] is False, "three permanent failures must disable"
    assert state["reason"] == "endpoint_not_found_404", state["reason"]
    assert state["disabled_at"] is not None, "the date is half the message"

    warned = "\n".join(
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    )
    assert HOOK_URL in warned, f"the WARNING must name the endpoint: {warned!r}"
    assert MERCHANT in warned, f"the WARNING must name the merchant: {warned!r}"


@pytest.mark.asyncio
async def test_one_failed_delivery_counts_once_not_once_per_attempt(session):
    """THE ACCOUNTING TEST. One permanent failure is FIVE attempts over hours;
    the counter must move by one, not by five.

    Every other test in this file counts deliveries, so all of them would still
    pass if the increment landed inside `_attempt_delivery` per attempt — three
    404s would then disable on the FIRST dead delivery instead of the third,
    and the endpoint would die in minutes rather than the ~8 hours the rule
    describes. This is the only test that can see that.
    """
    wid = await _register_webhook(session)

    posted = await _deliver(session, outcome=404)

    assert len(posted) == MAX_RETRIES, (
        f"premise: one delivery is {MAX_RETRIES} attempts, got {len(posted)}"
    )
    state = await _state(wid)
    assert state["failures"] == 1, (
        f"one given-up delivery must count ONCE, not once per attempt "
        f"(got {state['failures']})"
    )
    assert state["is_active"] is True, "one permanent failure must not disable"


@pytest.mark.asyncio
async def test_three_consecutive_dns_failures_disable_the_endpoint(session):
    """A hostname that no longer resolves is as gone as a 404. The egress guard
    deliberately lets DNS failures through (webhook_service.py:147-152), so this
    is caught at the delivery layer or not at all."""
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=_dns_failure())

    state = await _state(wid)
    assert state["is_active"] is False
    assert state["reason"] == "dns_resolution_failed", state["reason"]
    assert state["disabled_at"] is not None


@pytest.mark.asyncio
async def test_three_egress_blocked_deliveries_disable_the_endpoint(session):
    """The most aggressive of the three permanent causes, and the one that fires
    fastest — so the one that must not reach production untested.

    An egress-blocked delivery is terminal at attempt 1 (webhook_service.py:1178-1187):
    it never enters the retry ladder, so three of them disable an endpoint in
    MINUTES where three 404s take ~8 hours. That asymmetry is intended — a URL
    we refuse to contact is a configuration error, not a temporary one — but the
    reason code must say so: `url_not_allowed:` reads as "unreachable by policy",
    not "your server misbehaved".
    """
    wid = await _register_webhook(session, url="http://merchant.example/hook")

    for _ in range(DISABLE_AFTER):
        posted = await _deliver(session, outcome=200)
        assert posted == [], (
            "an egress-blocked endpoint must never be contacted at all"
        )

    state = await _state(wid)
    assert state["is_active"] is False
    assert state["reason"] == "url_not_allowed:scheme_not_https", state["reason"]
    assert state["disabled_at"] is not None


# ═══════════════════════════════════════════════════════════════
#  A success clears the slate
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_success_between_404s_resets_the_counter(session):
    """404, 404, success, 404 → one, not three. An endpoint that is alive must
    not carry permanent blame forward from before it recovered."""
    wid = await _register_webhook(session)

    await _deliver(session, outcome=404)
    await _deliver(session, outcome=404)
    assert (await _state(wid))["failures"] == 2, "premise: two accumulated"

    await _deliver(session, outcome=200)
    assert (await _state(wid))["failures"] == 0, "a success must reset to zero"

    await _deliver(session, outcome=404)

    state = await _state(wid)
    assert state["is_active"] is True, "must NOT disable — the run was broken"
    assert state["failures"] == 1, "counting restarts after the success"
    assert state["reason"] is None
    assert state["disabled_at"] is None


# ═══════════════════════════════════════════════════════════════
#  Transient failures never count, however often they repeat
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_three_consecutive_500s_do_not_disable(session):
    """The server exists and is unwell. The existing backoff owns this case."""
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=500)

    state = await _state(wid)
    assert state["is_active"] is True, "a 5xx endpoint must stay enabled"
    assert state["failures"] == 0
    assert state["reason"] is None


@pytest.mark.asyncio
async def test_three_consecutive_timeouts_do_not_disable(session):
    """A slow endpoint is a working endpoint having a bad day."""
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=_read_timeout())

    state = await _state(wid)
    assert state["is_active"] is True
    assert state["failures"] == 0


@pytest.mark.asyncio
async def test_three_consecutive_connection_refused_do_not_disable(session):
    """THE DISCRIMINATION TEST. Identical exception class to the DNS case —
    httpx.ConnectError — differing only in __cause__. If the implementation
    classifies on the exception type it disables here, and this fails.

    A refused connection means the name resolved and something answered the
    door with a no: the host exists, the service may be restarting.
    """
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=_connection_refused())

    state = await _state(wid)
    assert state["is_active"] is True, (
        "connection-refused is transient; only ConnectError caused by "
        "socket.gaierror is permanent"
    )
    assert state["failures"] == 0
    assert state["reason"] is None


# ═══════════════════════════════════════════════════════════════
#  Consequences of being disabled
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_disabled_endpoint_receives_no_further_deliveries(session):
    """Driven to auto-disable end-to-end, then a fourth event fans out.

    Deliberately not written by hand-setting is_active=False: the
    `is_active == True` filter already exists (webhook_service.py:1394), so that
    version would pass today and prove nothing about auto-disable.
    """
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=404)
    assert (await _state(wid))["is_active"] is False, "premise: it disabled"

    before = await _delivery_count(wid)
    posted = await _deliver(session, outcome=404)

    assert posted == [], f"a disabled endpoint must not be contacted: {posted}"
    assert await _delivery_count(wid) == before, (
        "no new webhook_deliveries row may be created for a disabled endpoint"
    )


@pytest.mark.asyncio
async def test_other_endpoints_of_the_same_merchant_are_unaffected(session):
    """The counter is per endpoint. One merchant's dead webhook.site URL must
    not take down the endpoint that actually runs their shop."""
    dead = await _register_webhook(session, url=HOOK_URL)
    alive = await _register_webhook(session, url=OTHER_URL)

    # Both endpoints receive every event; the stub 404s the dead one and 200s
    # the live one, by URL.
    async def _post(url, *, content=None, headers=None, **kwargs):
        resp = MagicMock()
        resp.status_code = 404 if url == HOOK_URL else 200
        resp.text = "stubbed"
        return resp

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        for _ in range(DISABLE_AFTER):
            intent = await _make_intent(session)
            await send_webhook(
                session, merchant_id=MERCHANT, event=EVENT, intent=intent,
            )
            for _ in range(MAX_RETRIES + 3):
                pending = (await session.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.status == DeliveryStatus.pending
                    )
                )).scalars().all()
                if not pending:
                    break
                past = datetime.now(timezone.utc) - timedelta(seconds=1)
                for delivery in pending:
                    delivery.next_retry_at = past
                await session.flush()
                await process_pending_deliveries(session)
            await session.commit()

    assert (await _state(dead))["is_active"] is False, "premise: the dead one died"

    survivor = await _state(alive)
    assert survivor["is_active"] is True, "the working endpoint must survive"
    assert survivor["failures"] == 0
    assert survivor["reason"] is None
    assert survivor["disabled_at"] is None


# ═══════════════════════════════════════════════════════════════
#  Concurrency
# ═══════════════════════════════════════════════════════════════

class _Rendezvous:
    """Hold every POST until BOTH deliveries have reached the HTTP hop.

    Without this the two coroutines interleave at whatever points the event loop
    happens to yield, and the race is reproduced by luck. The barrier makes the
    dangerous interleaving — both attempts in flight, both about to give up —
    happen on every run.
    """

    def __init__(self, parties: int) -> None:
        self._barrier = asyncio.Barrier(parties)

    async def wait(self) -> None:
        try:
            async with asyncio.timeout(5):
                await self._barrier.wait()
        except (TimeoutError, asyncio.TimeoutError):  # pragma: no cover
            raise AssertionError(
                "the two deliveries did not reach the HTTP hop together — the "
                "test's attempt counts are asymmetric, not a product bug"
            )


@contextmanager
def _http_in_lockstep(status_code: int, rendezvous: _Rendezvous):
    """`_http`, plus a barrier so concurrent attempts advance together."""

    async def _post(url, *, content=None, headers=None, **kwargs):
        await rendezvous.wait()
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = f"stubbed {status_code}"
        return resp

    client = AsyncMock()
    client.post = AsyncMock(side_effect=_post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.webhook_service.httpx.AsyncClient", return_value=client):
        yield


async def _finish_ladder(delivery_id: int, webhook_id: int):
    """Drive ONE delivery to exhaustion in its OWN session, as a second poller
    worker would.

    Each worker resolves its own `MerchantWebhook` instance, which is the whole
    point: two sessions each holding their own copy of the row is exactly how the
    read-modify-write is lost. `process_pending_deliveries` is not used here
    because its batch SELECT is unfiltered — two concurrent callers would each
    pick up BOTH rows and attempt them twice. The function under test,
    `_attempt_delivery`, is the real one, reached the way the poller reaches it.
    """
    async with async_session() as db:
        for _ in range(MAX_RETRIES + 2):
            delivery = await db.get(WebhookDelivery, delivery_id)
            if delivery.status is not DeliveryStatus.pending:
                return
            webhook = await db.get(MerchantWebhook, webhook_id)
            await ws._attempt_delivery(delivery, webhook)
            await db.commit()
        raise AssertionError("delivery never reached a terminal status")


@pytest.mark.asyncio
async def test_two_deliveries_exhausting_concurrently_both_count(session):
    """THE RACE. A dead endpoint fails on EVERY event at once — that is the
    scenario this whole feature exists for, not an edge case.

    Two deliveries for the same endpoint give up at the same moment. If the
    increment is a read-modify-write on an ORM attribute, both workers read the
    same value and both write value+1: the counter advances by ONE instead of
    two, disabling takes more failures than intended, and nobody notices because
    the symptom is that the logs keep filling.

    A sequential version of this test passes against the broken implementation
    and proves nothing — the two writes must genuinely overlap.
    """
    wid = await _register_webhook(session)

    # Real fan-out creates both delivery rows (and burns attempt 1 of each).
    delivery_ids = []
    with _http(404):
        for _ in range(2):
            intent = await _make_intent(session)
            await send_webhook(
                session, merchant_id=MERCHANT, event=EVENT, intent=intent,
            )
            delivery_ids.append((await session.execute(
                select(WebhookDelivery)
                .order_by(WebhookDelivery.id.desc())
                .limit(1)
            )).scalar_one().id)
    await session.commit()

    assert (await _state(wid))["failures"] == 0, (
        "premise: neither delivery has given up yet"
    )

    # Both finish their ladders in lockstep, in separate sessions.
    rendezvous = _Rendezvous(2)
    with _http_in_lockstep(404, rendezvous):
        await asyncio.gather(*(
            _finish_ladder(did, wid) for did in delivery_ids
        ))

    state = await _state(wid)
    assert state["failures"] == 2, (
        f"two concurrently-exhausted deliveries must count TWICE, not once "
        f"(got {state['failures']}) — the increment is not atomic"
    )
    assert state["is_active"] is True, "two is below the threshold of three"


# ═══════════════════════════════════════════════════════════════
#  Re-enabling
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_re_enabling_clears_the_three_columns_and_deliveries_resume(session):
    """Auto-disable is only honest if the merchant can undo it. Re-enabling
    clears the counter, the reason and the date — a fresh start, not an endpoint
    that disables again on its next single failure.

    The route is imported INSIDE the test on purpose: it does not exist yet, and
    a module-level import would error the whole file at collection instead of
    failing this one test.
    """
    from app.api.user_org_webhooks_routes import enable_org_webhook

    org = await _make_org(session, owner_address=MERCHANT)
    wid = await _register_webhook(session)

    for _ in range(DISABLE_AFTER):
        await _deliver(session, outcome=404)
    assert (await _state(wid))["is_active"] is False, "premise: it disabled"

    await enable_org_webhook(
        webhook_id=wid,
        ctx=("user-unused", str(org.id), "operator"),
        environment=ENVIRONMENT,
        db=session,
    )

    state = await _state(wid)
    assert state["is_active"] is True
    assert state["failures"] == 0, "re-enabling resets the counter"
    assert state["reason"] is None, "a re-enabled endpoint is not 'disabled because…'"
    assert state["disabled_at"] is None

    posted = await _deliver(session, outcome=200)
    assert posted == [HOOK_URL], f"deliveries must resume: {posted}"
