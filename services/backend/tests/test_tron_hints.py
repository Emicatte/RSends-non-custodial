"""B1 and B5 — remembering a submitted hash, and acting on the verdict.

Reuses the recorded Nile fixtures from `test_tron_verifier.py`. Nothing here
touches the network, and the node client is counted rather than merely stubbed:
several of these assertions are about a call NOT happening, which is invisible
if you only look at state.

The invariant underneath all of it: a hint is an accelerator over the poller's
address scan, never a replacement for it. The last test in this file is the one
that proves refusing a hint costs nothing — an intent whose hint was rejected is
still closed by the ordinary amount-only match.
"""

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.services import tron_poller as tp
from app.services import tron_verifier as tv

FIXTURES = Path(__file__).parent / "fixtures" / "tron"

MERCHANT = "TAGfrptqq5mAK8EqJcXJeaTxf4zNYnUBpL"
PAYER = "TNHUQgX2C1bSxdfuKZM855FY6QfPWLJiEa"
STRANGER = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
TX_2_5 = "07f1b19de88dec6213e95b96715bfa3198b1ab38d7228810d46c3a2e25ff91d3"
TX_3_0 = "75e4fda0a1c1bb9c0c27d4e876e7a21a5a0bdca5ebb3727eb959c7b467f57a75"
# The two fixture payments this file uses, and they are ~4h apart. `created_at`
# is anchored to the EARLIER one, because the matcher requires
# `created_at <= block_timestamp <= expires_at` and an intent created after a
# transfer can never be paid by it.
PAID_AT = datetime.fromtimestamp(1788132336, tz=timezone.utc)        # TX_2_5
PAID_AT_3_0 = datetime.fromtimestamp(1788116751, tz=timezone.utc)    # TX_3_0
EARLIEST_PAID_AT = min(PAID_AT, PAID_AT_3_0)

NILE = tp.TRON_NILE


def _load(tx_hash: str, name: str):
    return json.loads((FIXTURES / tx_hash / f"{name}.json").read_text())


class CountingSource:
    """A fixture reader that also counts node reads.

    The count is the assertion in several tests: "a rejected hint is never
    re-fetched" is a statement about work not done, and a state check alone
    would pass even if the node were hammered every tick.
    """

    def __init__(self, tx_hash: str, *, present: bool = True):
        self.calls = 0
        self.info = _load(tx_hash, "gettransactioninfobyid") if present else {}
        self.tx = _load(tx_hash, "gettransactionbyid") if present else {}
        self.event_list = _load(tx_hash, "events")["data"] if present else []

    async def transaction_info(self, tx_hash: str) -> dict:
        self.calls += 1
        return self.info

    async def transaction(self, tx_hash: str) -> dict:
        self.calls += 1
        return self.tx

    async def events(self, tx_hash: str) -> list:
        self.calls += 1
        return self.event_list


@pytest_asyncio.fixture(autouse=True)
async def _db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.indexer_models  # noqa: F401
    import app.models.merchant_models  # noqa: F401
    import app.models.settlement_models  # noqa: F401
    import app.models.tron_hint_models  # noqa: F401
    from app.models.merchant_models import (
        MerchantWebhook, PaymentIntent, WebhookDelivery,
    )
    from app.models.settlement_models import PaymentSettlement
    from app.models.tron_hint_models import TronPaymentHint

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(TronPaymentHint.__table__.delete())
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
        await conn.execute(WebhookDelivery.__table__.delete())
        await conn.execute(MerchantWebhook.__table__.delete())
    yield


@pytest.fixture
def webhooks(monkeypatch):
    calls = []

    async def _fake(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append((event, intent.intent_id))
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake)
    return calls


async def _intent(
    *,
    intent_id: str = "pi_hint_test",
    amount: float = 2.5,
    status=None,
    expires_delta: timedelta = timedelta(hours=1),
    chain: str = "tron_nile",
):
    """A TRON intent whose window contains the fixture's block timestamp.

    Two clocks meet here and they must both be satisfied. The matcher requires
    `created_at <= block_timestamp <= expires_at`, and the fixture payments are
    days old — so `created_at` is anchored to the earliest of them. The endpoint's expiry gate
    compares `expires_at` to NOW, so that end is anchored to the wall clock.
    Anchoring both to the fixture makes every intent arrive already expired.
    """
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=intent_id,
            merchant_id=MERCHANT,
            environment="test",
            amount=amount,
            currency="USDT",
            chain=chain,
            recipient=MERCHANT,
            status=status or IntentStatus.pending,
            created_at=EARLIEST_PAID_AT - timedelta(minutes=5),
            expires_at=datetime.now(timezone.utc) + expires_delta,
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)
        return intent.id, intent.intent_id


async def _hints():
    from app.db.session import async_session
    from app.models.tron_hint_models import TronPaymentHint

    async with async_session() as db:
        return (await db.execute(select(TronPaymentHint))).scalars().all()


async def _settlement_count() -> int:
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement

    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(PaymentSettlement)
        )).scalar_one()


async def _intent_row(intent_id: str):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()


# ═══════════════════════════════════════════════════════════════
#  B1 — the endpoint
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_verified_hint_settles_and_reports_the_new_status(webhooks):
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import HintState

    _, intent_id = await _intent()
    source = CountingSource(TX_2_5)

    async with async_session() as db:
        body = await submit_tron_tx_hint(
            intent_id,
            _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db,
            _source=source,
        )

    assert body.hint_state == "verified"
    assert body.status == IntentStatus.paid.value
    assert (await _intent_row(intent_id)).status == IntentStatus.paid
    assert await _settlement_count() == 1
    assert [e for e, _ in webhooks] == ["payment.completed"]

    [hint] = await _hints()
    assert hint.state == HintState.verified and hint.verified_at is not None


@pytest.mark.asyncio
async def test_an_unverifiable_hint_is_accepted_and_left_pending():
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session
    from app.models.tron_hint_models import HintState

    _, intent_id = await _intent()
    # Not solidified yet, or no such hash: the node answers {} to both.
    source = CountingSource(TX_2_5, present=False)

    async with async_session() as db:
        body = await submit_tron_tx_hint(
            intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=source,
        )

    assert body.hint_state == "pending"
    [hint] = await _hints()
    assert hint.state == HintState.pending
    assert await _settlement_count() == 0


@pytest.mark.asyncio
async def test_a_rejected_hint_records_its_reason_and_settles_nothing():
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import HintState

    # The invoice wants 3.0; the fixture transfer carries 2.5.
    _, intent_id = await _intent(amount=3.0)

    async with async_session() as db:
        body = await submit_tron_tx_hint(
            intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=CountingSource(TX_2_5),
        )

    assert body.hint_state == "rejected"
    [hint] = await _hints()
    assert hint.state == HintState.rejected
    assert hint.rejection_reason == "wrong_amount"
    # The poller path is untouched: nothing settled, intent still payable.
    assert await _settlement_count() == 0
    assert (await _intent_row(intent_id)).status == IntentStatus.pending


@pytest.mark.asyncio
async def test_a_double_click_yields_one_row():
    """Two identical submissions, one row — via the unique constraint.

    A select-then-insert would lose this race; the endpoint inserts and catches
    the IntegrityError instead.
    """
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session

    _, intent_id = await _intent()
    for _ in range(2):
        async with async_session() as db:
            await submit_tron_tx_hint(
                intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
                db=db, _source=CountingSource(TX_2_5, present=False),
            )

    assert len(await _hints()) == 1


@pytest.mark.asyncio
async def test_the_second_submission_does_not_re_verify():
    """An existing pending or verified row means the node is not asked again."""
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session

    _, intent_id = await _intent()
    first = CountingSource(TX_2_5, present=False)
    second = CountingSource(TX_2_5, present=False)

    async with async_session() as db:
        await submit_tron_tx_hint(
            intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=first,
        )
    async with async_session() as db:
        await submit_tron_tx_hint(
            intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=second,
        )

    assert first.calls > 0
    assert second.calls == 0, "a resubmission must not spend a node call"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(status="paid"), 409),
        (dict(expires_delta=timedelta(minutes=-1)), 409),
        (dict(chain="base_sepolia"), 409),
    ],
)
async def test_the_endpoint_refuses_an_intent_it_must_not_accelerate(kwargs, expected):
    from fastapi import HTTPException
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus

    if kwargs.get("status") == "paid":
        kwargs["status"] = IntentStatus.paid
    _, intent_id = await _intent(**kwargs)

    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await submit_tron_tx_hint(
                intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
                db=db, _source=CountingSource(TX_2_5),
            )
    assert exc.value.status_code == expected


@pytest.mark.asyncio
async def test_a_hash_already_settled_against_another_intent_is_refused():
    from fastapi import HTTPException
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session

    # First intent takes the transfer.
    _, first_id = await _intent(intent_id="pi_hint_first")
    async with async_session() as db:
        await submit_tron_tx_hint(
            first_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=CountingSource(TX_2_5),
        )
    assert await _settlement_count() == 1

    # A second intent cannot claim the same transaction.
    _, second_id = await _intent(intent_id="pi_hint_second")
    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await submit_tron_tx_hint(
                second_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
                db=db, _source=CountingSource(TX_2_5),
            )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_an_unknown_intent_is_404():
    from fastapi import HTTPException
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session

    async with async_session() as db:
        with pytest.raises(HTTPException) as exc:
            await submit_tron_tx_hint(
                "pi_nope", _Body(tx_hash=TX_2_5, payer_address=PAYER),
                db=db, _source=CountingSource(TX_2_5),
            )
    assert exc.value.status_code == 404


def test_the_body_carries_two_fields_and_no_more():
    """Recipient, amount, token and chain are not accepted, so they cannot lie."""
    from app.api.public_routes import TronTxHintRequest

    assert set(TronTxHintRequest.model_fields) == {"tx_hash", "payer_address"}

    # An uppercase hash is stored lowercase; a malformed one is refused.
    assert TronTxHintRequest(tx_hash=TX_2_5.upper()).tx_hash == TX_2_5
    with pytest.raises(Exception):
        TronTxHintRequest(tx_hash="0x" + TX_2_5)
    with pytest.raises(Exception):
        TronTxHintRequest(tx_hash="abc")


def test_the_public_post_is_allowlisted_by_method_and_prefix():
    """A method-scoped allowlist, not an EXEMPT_PATHS entry.

    `is_exempt` is a bare startswith: adding /api/v1/public there would exempt
    every future method and path under it, silently and forever.
    """
    from app.security.api_keys import is_exempt, is_post_public

    assert is_post_public("/api/v1/public/payment-intent/pi_x/tx-hint")
    assert not is_post_public("/api/v1/public/something-else")
    assert not is_exempt("/api/v1/public/payment-intent/pi_x/tx-hint")


# ═══════════════════════════════════════════════════════════════
#  B5 — the poller pass
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_pass_verifies_a_pending_hint_and_closes_the_intent(webhooks):
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints

    pk, intent_id = await _intent()
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    source = CountingSource(TX_2_5)
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)

    [hint] = await _hints()
    assert hint.state == HintState.verified
    assert hint.last_checked_at is not None
    assert (await _intent_row(intent_id)).status == IntentStatus.paid
    assert [e for e, _ in webhooks] == ["payment.completed"]


@pytest.mark.asyncio
async def test_a_rejected_hint_is_never_fetched_again():
    from app.db.session import async_session
    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints

    # 3.0 invoice, 2.5 transfer: rejected on amount.
    pk, _ = await _intent(amount=3.0)
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    source = CountingSource(TX_2_5)
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)
    after_first = source.calls
    assert after_first > 0
    [hint] = await _hints()
    assert hint.state == HintState.rejected

    # Ten more ticks must cost nothing.
    for _ in range(10):
        await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)
    assert source.calls == after_first, "a terminal hint kept costing node calls"


@pytest.mark.asyncio
async def test_a_hint_whose_intent_is_no_longer_payable_is_skipped_without_a_node_call():
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import TronPaymentHint
    from app.services import tron_hints

    pk, _ = await _intent(status=IntentStatus.cancelled)
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    source = CountingSource(TX_2_5)
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)
    assert source.calls == 0, "the intent state belongs in the query, not after the fetch"


@pytest.mark.asyncio
async def test_the_give_up_rule_fires_only_past_the_late_window():
    from app.db.session import async_session
    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints

    # Expired, but inside the 24h window: still retried.
    pk, _ = await _intent(intent_id="pi_recent", expires_delta=timedelta(hours=-1))
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    source = CountingSource(TX_2_5, present=False)
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)
    [hint] = await _hints()
    assert hint.state == HintState.pending
    assert source.calls > 0


@pytest.mark.asyncio
async def test_a_hint_past_the_late_window_is_given_up_on():
    from app.db.session import async_session
    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints

    pk, _ = await _intent(expires_delta=timedelta(hours=-30))
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    source = CountingSource(TX_2_5, present=False)
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: source)

    [hint] = await _hints()
    assert hint.state == HintState.rejected
    assert hint.rejection_reason == "not_found"
    assert source.calls == 0, "a hint being given up on need not be fetched"


@pytest.mark.asyncio
async def test_the_endpoint_and_the_pass_racing_yield_one_settlement_and_one_webhook(
    webhooks,
):
    from app.api.public_routes import submit_tron_tx_hint
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import TronPaymentHint
    from app.services import tron_hints

    pk, intent_id = await _intent()

    # The endpoint settles it...
    async with async_session() as db:
        await submit_tron_tx_hint(
            intent_id, _Body(tx_hash=TX_2_5, payer_address=PAYER),
            db=db, _source=CountingSource(TX_2_5),
        )
    # ...and the poller pass runs over the same transaction anyway, as it would
    # on the very next tick.
    await tron_hints.run_hint_pass(NILE, source_for=lambda h: CountingSource(TX_2_5))
    await tp._run_matching_pass(NILE)

    assert await _settlement_count() == 1
    assert (await _intent_row(intent_id)).status == IntentStatus.paid
    assert [e for e, _ in webhooks] == ["payment.completed"], webhooks


@pytest.mark.asyncio
async def test_a_rejected_hint_does_not_stop_the_ordinary_poller_match(webhooks):
    """The proof that refusing to accelerate never costs a payment.

    The hint is rejected because the payer submitted the wrong hash. The real
    transfer is still on chain, the address scan still finds it, and the
    amount-only match still closes the intent.
    """
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus
    from app.models.tron_hint_models import HintState, TronPaymentHint
    from app.services import tron_hints, tron_matcher

    # Invoice for 3.0; the payer submits the hash of their 2.5 transfer.
    pk, intent_id = await _intent(amount=3.0)
    async with async_session() as db:
        db.add(TronPaymentHint(intent_pk=pk, tx_hash=TX_2_5, payer_address=PAYER))
        await db.commit()

    await tron_hints.run_hint_pass(NILE, source_for=lambda h: CountingSource(TX_2_5))
    [hint] = await _hints()
    assert hint.state == HintState.rejected

    # Now the poller's own scan observes the real 3.0 transfer.
    discovery = json.loads(
        (FIXTURES / f"discovery_trc20_{MERCHANT}.json").read_text()
    )["data"]
    scanned = next(t for t in discovery if t["transaction_id"] == TX_3_0)
    event = tp._pair_transfer_to_event(scanned, _load(TX_3_0, "events")["data"])
    assert await tp._record_settlement(scanned, event, NILE) == "new"

    await tron_matcher.match_pending_tron_settlements(NILE)

    intent = await _intent_row(intent_id)
    assert intent.status == IntentStatus.paid
    assert intent.matched_tx_hash == TX_3_0
    assert [e for e, _ in webhooks] == ["payment.completed"]


@dataclass
class _Body:
    """Stands in for the request model at the handler boundary."""

    tx_hash: str
    payer_address: Optional[str] = None
