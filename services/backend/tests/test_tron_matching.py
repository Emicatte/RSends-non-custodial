"""TRON matching — one settlement, one intent, and the invoice closes.

Phase 1, slice 3. Slice 2 records TRON settlements with `intent_id = NULL` and
draws no conclusion. This matches a recorded settlement to exactly one pending
intent, closes the intent, and fires the webhook that already exists.

Contract pinned here:

  - A settlement matches an intent on chain + status + recipient + token +
    environment + validity window. **Amount is NOT a match criterion** — matching
    on it would make an underpayment unmatchable, and an unmatched underpayment
    is a payment that silently disappears.
  - The recipient comparison is EXACT and CASE-SENSITIVE. Base58check has no
    `0 O I l`; folding one does not merely change it, it can produce a string
    that is not base58 at all. The dead matcher's own candidate query lowercases
    the recipient and says so (`webhook_service.py:717-720`).
  - Zero candidates: nothing changes. One: close it. More than one: choose
    NOTHING, mark the settlement `rejected`, fire `payment.ambiguous`.
  - Amounts compare as EXACT INTEGERS in base units, no tolerance. The written
    columns are in TOKEN units, because `_build_payload` emits `amount` in token
    units beside them.
  - Over -> paid. Under -> `partial`, never rejected: on TRON the money is
    already at the merchant, and rejecting it makes a real payment vanish from
    the merchant's view.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_matching.py -v
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.services import tron_matcher as tm
from app.services import tron_poller as tp
from app.services.tron_poller import TRON_CHAIN_ID, USDT_TRC20_CONTRACT
from tests._source_helpers import code_without_prose

# Real mainnet values, same provenance as the slice-2 suite.
MERCH = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
MERCH_OTHER = "TLntW9Z59LYY5KEi9cmwk3PKjQga828ird"
PAYER = "TVJF7zCn8pffXP7rPd2RPsWJxQ4YaUTmTB"
USDT_DECIMALS = 6

# An EVM settlement, to prove the matcher never touches one.
EVM_CHAIN = 84532
EVM_MERCHANT = "0x" + "ab" * 20
EVM_TOKEN = "0x" + "cd" * 20


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.indexer_models  # noqa: F401
    import app.models.merchant_models  # noqa: F401
    import app.models.settlement_models  # noqa: F401
    from app.models.indexer_models import IndexerCursor
    from app.models.merchant_models import PaymentIntent
    from app.models.settlement_models import PaymentSettlement

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
        await conn.execute(IndexerCursor.__table__.delete())
    yield


@pytest.fixture
def webhooks(monkeypatch):
    """Capture every dispatch as (event, intent_id, extra). Proves fire-once."""
    calls = []

    async def _fake(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append((event, intent.intent_id, extra_payload or {}))
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake)
    return calls


# ── builders ─────────────────────────────────────────────────

_TX_SEQ = iter(range(1, 10_000))
_AMT_SEQ = iter(range(1, 10_000))


async def _make_intent(*, recipient=MERCH, amount=None, chain="TRON",
                       status=None, environment="live", merchant_id=None,
                       created_at=None, expires_at=None):
    """A pending watch-only TRON intent. Each gets a distinct amount — 0019's
    `uq_intent_pending_amount` is unique over (merchant, env, chain, currency,
    amount) while pending."""
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    now = datetime.now(timezone.utc)
    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id=merchant_id or "m_tron_match",
            environment=environment,
            amount=float(amount if amount is not None else next(_AMT_SEQ)),
            currency="USDT",
            chain=chain,
            recipient=recipient,
            onchain_invoice_id=None,
            status=status or IntentStatus.pending,
            created_at=created_at or (now - timedelta(minutes=5)),
            expires_at=expires_at or (now + timedelta(minutes=30)),
        ))
        await db.commit()
    return iid


async def _make_settlement(*, merchant=MERCH, amount_base, chain_id=TRON_CHAIN_ID,
                           token=USDT_TRC20_CONTRACT, intent_id=None,
                           block_timestamp=None, status=None, tx_hash=None):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement, SettlementStatus

    tx = tx_hash or f"{next(_TX_SEQ):064x}"
    async with async_session() as db:
        row = PaymentSettlement(
            invoice_id=None,
            merchant=merchant,
            payer=PAYER,
            token=token,
            amount=Decimal(amount_base),
            block_timestamp=block_timestamp or datetime.now(timezone.utc),
            chain_id=chain_id,
            tx_hash=tx,
            log_index=0,
            block_number=85758417,
            status=status or SettlementStatus.pending,
            intent_id=intent_id,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _intent(iid):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()


async def _settlement(sid):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement

    async with async_session() as db:
        return await db.get(PaymentSettlement, sid)


async def _intents_snapshot():
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    async with async_session() as db:
        rows = (await db.execute(select(PaymentIntent))).scalars().all()
        return {r.intent_id: (r.status, r.amount_received, r.overpaid_amount,
                              r.underpaid_amount, r.matched_tx_hash,
                              r.completed_at) for r in rows}


def _base(tokens: float) -> int:
    from app.services.router_registry import to_base_units
    return to_base_units(tokens, USDT_DECIMALS)


# ═══════════════════════════════════════════════════════════════
#  Exact amount — the happy path
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_exact_amount_closes_the_intent_and_fires_completed(webhooks):
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus

    iid = await _make_intent(amount=10.0)
    sid = await _make_settlement(amount_base=_base(10.0))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 1, result
    intent = await _intent(iid)
    assert intent.status == IntentStatus.paid
    assert intent.amount_received == "10"
    assert intent.overpaid_amount is None
    assert intent.underpaid_amount is None
    assert intent.completed_at is not None

    s = await _settlement(sid)
    assert s.intent_id == iid
    assert s.status == SettlementStatus.final
    assert s.webhook_fired_at is not None

    assert [(e, i) for e, i, _ in webhooks] == [("payment.completed", iid)]


@pytest.mark.asyncio
async def test_matched_tx_hash_is_carried_to_the_intent(webhooks):
    iid = await _make_intent(amount=10.0)
    sid = await _make_settlement(amount_base=_base(10.0))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    s = await _settlement(sid)
    assert (await _intent(iid)).matched_tx_hash == s.tx_hash


# ═══════════════════════════════════════════════════════════════
#  Over and under
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_overpayment_is_paid_and_records_the_excess(webhooks):
    from app.models.merchant_models import IntentStatus

    iid = await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(12.5))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 1
    intent = await _intent(iid)
    assert intent.status == IntentStatus.paid          # the invoice IS satisfied
    assert intent.amount_received == "12.5"
    assert intent.overpaid_amount == "2.5"
    assert intent.underpaid_amount is None
    assert [e for e, _, _ in webhooks] == ["payment.completed"]


@pytest.mark.asyncio
async def test_underpayment_goes_partial_and_is_never_rejected(webhooks):
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus

    iid = await _make_intent(amount=10.0)
    sid = await _make_settlement(amount_base=_base(4.25))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["partial"] == 1, result
    intent = await _intent(iid)
    assert intent.status == IntentStatus.partial
    assert intent.status != IntentStatus.paid
    assert intent.amount_received == "4.25"
    assert intent.underpaid_amount == "5.75"
    assert intent.overpaid_amount is None
    # Not completed — the invoice is not satisfied.
    assert intent.completed_at is None

    s = await _settlement(sid)
    assert s.intent_id == iid
    # The money IS on chain and fully processed. `final` describes the
    # SETTLEMENT, not the invoice — the invoice is `partial`.
    assert s.status == SettlementStatus.final
    assert s.status != SettlementStatus.rejected, (
        "a real payment was rejected — it would vanish from the merchant's view"
    )
    assert [(e, i) for e, i, _ in webhooks] == [("payment.partial", iid)]


@pytest.mark.asyncio
async def test_amount_columns_are_token_units_not_base_units(webhooks):
    """`_build_payload` emits `amount` in token units; these sit beside it."""
    iid = await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(10.5))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    intent = await _intent(iid)
    assert intent.amount_received == "10.5"
    assert intent.amount_received != "10500000"
    assert intent.overpaid_amount == "0.5"
    # And never scientific notation, whatever the magnitude.
    for v in (intent.amount_received, intent.overpaid_amount):
        assert "E" not in v.upper(), v


@pytest.mark.asyncio
async def test_a_second_underpayment_does_not_accumulate(webhooks):
    """Explicitly out of scope: two underpayments do not close the invoice."""
    from app.models.merchant_models import IntentStatus

    iid = await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(6.0))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)
    assert (await _intent(iid)).status == IntentStatus.partial

    await _make_settlement(amount_base=_base(4.0))
    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    # The intent is no longer pending, so the second payment finds no candidate.
    assert result["matched"] == 0 and result["partial"] == 0
    intent = await _intent(iid)
    assert intent.status == IntentStatus.partial
    assert intent.amount_received == "6"      # NOT accumulated to 10


# ═══════════════════════════════════════════════════════════════
#  Zero candidates, and everything the matcher must not touch
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_zero_candidates_changes_nothing(webhooks):
    from app.models.settlement_models import SettlementStatus

    iid = await _make_intent(recipient=MERCH_OTHER, amount=10.0)
    before = await _intents_snapshot()
    sid = await _make_settlement(merchant=MERCH, amount_base=_base(10.0))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0
    assert await _intents_snapshot() == before
    s = await _settlement(sid)
    assert s.intent_id is None
    assert s.status == SettlementStatus.pending   # still eligible next tick
    assert webhooks == []
    assert iid  # referenced


@pytest.mark.asyncio
async def test_recipient_matching_is_case_sensitive(webhooks):
    """A base58 address differing only in case is a DIFFERENT address."""
    folded = MERCH.lower()
    assert folded != MERCH
    await _make_intent(recipient=folded, amount=10.0)
    sid = await _make_settlement(merchant=MERCH, amount_base=_base(10.0))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0, "a case-folded recipient must not match"
    assert (await _settlement(sid)).intent_id is None
    assert webhooks == []


@pytest.mark.asyncio
async def test_a_settlement_already_carrying_an_intent_id_is_not_rematched(webhooks):
    from app.models.merchant_models import IntentStatus

    iid = await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(10.0), intent_id="pi_someoneelse")

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhooks == []


@pytest.mark.asyncio
async def test_an_evm_settlement_is_never_matched(webhooks):
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus

    iid = await _make_intent(recipient=EVM_MERCHANT, chain="base", amount=10.0)
    sid = await _make_settlement(
        merchant=EVM_MERCHANT, token=EVM_TOKEN, chain_id=EVM_CHAIN,
        amount_base=_base(10.0),
    )

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0
    assert (await _intent(iid)).status == IntentStatus.pending
    s = await _settlement(sid)
    assert s.intent_id is None
    assert s.status == SettlementStatus.pending
    assert webhooks == []


@pytest.mark.asyncio
async def test_a_foreign_token_does_not_match(webhooks):
    await _make_intent(amount=10.0)
    sid = await _make_settlement(amount_base=_base(10.0), token="TXXXfakeTokenAddressNotUsdt000000")

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0
    assert (await _settlement(sid)).intent_id is None


@pytest.mark.parametrize("when", ["before_created", "after_expiry"])
@pytest.mark.asyncio
async def test_a_settlement_outside_the_validity_window_does_not_match(
    webhooks, when
):
    now = datetime.now(timezone.utc)
    await _make_intent(
        amount=10.0,
        created_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=10),
    )
    ts = (now - timedelta(minutes=30)) if when == "before_created" \
        else (now + timedelta(minutes=30))
    sid = await _make_settlement(amount_base=_base(10.0), block_timestamp=ts)

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0, when
    assert (await _settlement(sid)).intent_id is None


@pytest.mark.asyncio
async def test_an_intent_that_expired_since_payment_is_not_matched(webhooks):
    """DELIBERATE, and a divergence from the EVM path — pinned so it is a
    decision, not an accident.

    `_finalize_settlement` treats `expired` as payable ("money on-chain wins
    over the timer"). This matcher does not: an intent expired between payment
    and matching gets ZERO candidates, and the settlement stays unmatched
    forever. The merchant has the money and nothing in the product says so.
    Recorded in CLAUDE.md.
    """
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus

    now = datetime.now(timezone.utc)
    iid = await _make_intent(
        amount=10.0, status=IntentStatus.expired,
        created_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=10),
    )
    sid = await _make_settlement(amount_base=_base(10.0))

    result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["matched"] == 0
    assert (await _intent(iid)).status == IntentStatus.expired
    s = await _settlement(sid)
    assert s.intent_id is None
    assert s.status == SettlementStatus.pending
    assert webhooks == []


# ═══════════════════════════════════════════════════════════════
#  Ambiguity — choose nothing
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_two_candidates_touch_no_intent_and_fire_ambiguous(webhooks, caplog):
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus

    a = await _make_intent(amount=10.0)
    b = await _make_intent(amount=11.0)      # distinct amount: 0019
    before = await _intents_snapshot()
    sid = await _make_settlement(amount_base=_base(10.0))

    with caplog.at_level(logging.WARNING, logger=tm.logger.name):
        result = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert result["ambiguous"] == 1, result
    assert result["matched"] == 0
    # Not one intent was touched.
    assert await _intents_snapshot() == before
    assert (await _intent(a)).status == IntentStatus.pending
    assert (await _intent(b)).status == IntentStatus.pending

    s = await _settlement(sid)
    assert s.intent_id is None, "ambiguity must not pick a winner"
    assert s.status == SettlementStatus.rejected, "must not be retried blindly"

    events = [e for e, _, _ in webhooks]
    assert events == ["payment.ambiguous"], events
    _, _, extra = webhooks[0]
    assert set(extra["candidate_intent_ids"]) == {a, b}

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in caplog.records]
    msg = errors[0].getMessage()
    assert a in msg and b in msg, msg
    assert s.tx_hash[:16] in msg or s.tx_hash in msg, msg


@pytest.mark.asyncio
async def test_an_ambiguous_settlement_holds_no_intent(webhooks):
    """`rejected` deliberately does not hold: an ambiguous payment must not
    freeze N invoices out of expiry and cancellation."""
    from app.db.session import async_session
    from app.services.intent_service import has_settlement_hold

    a = await _make_intent(amount=10.0)
    b = await _make_intent(amount=11.0)
    await _make_settlement(amount_base=_base(10.0))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    async with async_session() as db:
        assert await has_settlement_hold(db, a) is False
        assert await has_settlement_hold(db, b) is False


@pytest.mark.asyncio
async def test_an_ambiguous_settlement_is_not_reprocessed(webhooks):
    await _make_intent(amount=10.0)
    await _make_intent(amount=11.0)
    await _make_settlement(amount_base=_base(10.0))

    assert (await tm.match_pending_tron_settlements(tp.TRON_MAINNET))["ambiguous"] == 1
    second = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert second["ambiguous"] == 0
    assert [e for e, _, _ in webhooks] == ["payment.ambiguous"]


# ═══════════════════════════════════════════════════════════════
#  Fire once
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_rerunning_the_matcher_fires_no_second_webhook(webhooks):
    from app.models.merchant_models import IntentStatus

    iid = await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(10.0))

    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert [e for e, _, _ in webhooks] == ["payment.completed"]
    assert (await _intent(iid)).status == IntentStatus.paid


@pytest.mark.asyncio
async def test_rerunning_after_a_partial_fires_no_second_webhook(webhooks):
    await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(3.0))

    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert [e for e, _, _ in webhooks] == ["payment.partial"]


# ═══════════════════════════════════════════════════════════════
#  Redrive — the EVM sweep is chain-scoped and never sees TRON
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_failed_dispatch_is_redriven_next_pass(monkeypatch):
    """The claim is released on failure; nothing EVM-side would ever retry it."""
    from app.models.merchant_models import IntentStatus

    calls = []
    fail = {"now": True}

    async def _flaky(db, *, merchant_id, event, intent, extra_payload=None):
        if fail["now"]:
            raise RuntimeError("webhook backend down")
        calls.append((event, intent.intent_id))
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _flaky)

    iid = await _make_intent(amount=10.0)
    sid = await _make_settlement(amount_base=_base(10.0))

    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    # Intent is paid, settlement is final, but the claim was released.
    assert (await _intent(iid)).status == IntentStatus.paid
    s = await _settlement(sid)
    assert s.webhook_fired_at is None
    assert calls == []

    fail["now"] = False
    redriven = await tm.redrive_tron_webhooks(tp.TRON_MAINNET)

    assert redriven == 1
    assert calls == [("payment.completed", iid)]
    assert (await _settlement(sid)).webhook_fired_at is not None


@pytest.mark.asyncio
async def test_the_redrive_reuses_the_partial_event_for_a_partial_intent(
    monkeypatch
):
    calls = []
    fail = {"now": True}

    async def _flaky(db, *, merchant_id, event, intent, extra_payload=None):
        if fail["now"]:
            raise RuntimeError("down")
        calls.append(event)
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _flaky)

    await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(2.0))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    fail["now"] = False
    assert await tm.redrive_tron_webhooks(tp.TRON_MAINNET) == 1
    assert calls == ["payment.partial"]


@pytest.mark.asyncio
async def test_the_redrive_leaves_an_already_fired_settlement_alone(webhooks):
    await _make_intent(amount=10.0)
    await _make_settlement(amount_base=_base(10.0))
    await tm.match_pending_tron_settlements(tp.TRON_MAINNET)

    assert await tm.redrive_tron_webhooks(tp.TRON_MAINNET) == 0
    assert [e for e, _, _ in webhooks] == ["payment.completed"]


@pytest.mark.asyncio
async def test_the_redrive_never_touches_an_evm_settlement(webhooks):
    from app.models.merchant_models import IntentStatus
    from app.models.settlement_models import SettlementStatus
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    iid = await _make_intent(recipient=EVM_MERCHANT, chain="base", amount=10.0)
    async with async_session() as db:
        row = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == iid))).scalar_one()
        row.status = IntentStatus.paid
        row.matched_tx_hash = "0x" + "ee" * 32
        await db.commit()
    await _make_settlement(
        merchant=EVM_MERCHANT, token=EVM_TOKEN, chain_id=EVM_CHAIN,
        amount_base=_base(10.0), status=SettlementStatus.final,
        intent_id=iid, tx_hash="0x" + "ee" * 32,
    )

    assert await tm.redrive_tron_webhooks(tp.TRON_MAINNET) == 0
    assert webhooks == []


# ═══════════════════════════════════════════════════════════════
#  Isolation — a matching bug must not stop the recording
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_matcher_failure_does_not_prevent_recording_or_move_the_cursor(
    monkeypatch
):
    """The matching pass runs AFTER the writes and after the cursor, wrapped."""
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    from app.services import tron_poller as tp

    TS = 1787946738000
    TX = "f" * 64
    transfer = {
        "transaction_id": TX,
        "token_info": {"symbol": "USDT", "address": USDT_TRC20_CONTRACT,
                       "decimals": 6, "name": "Tether USD"},
        "block_timestamp": TS, "from": PAYER, "to": MERCH,
        "type": "Transfer", "value": str(_base(10.0)),
    }
    event = {
        "block_number": 85758417, "block_timestamp": TS,
        "caller_contract_address": USDT_TRC20_CONTRACT,
        "contract_address": USDT_TRC20_CONTRACT,
        "event_index": 0, "event_name": "Transfer",
        "result": {"from": "0xd4040ff90042a66f485bf4d0bd073b2613f4bbfb",
                   "to": "0xd057eb518fc1b2316617aaa7bb73c7e1876b7934",
                   "value": str(_base(10.0))},
        "result_type": {}, "event": "Transfer(...)", "transaction_id": TX,
    }

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._p = payload

        def json(self):
            return self._p

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, url, params=None, **kw):
            if "/transactions/trc20" in url:
                return _Resp({"data": [transfer], "success": True, "meta": {}})
            return _Resp({"data": [event], "success": True, "meta": {}})

    monkeypatch.setattr(tp.httpx, "AsyncClient", _Client)

    async def _boom(network):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(tm, "match_pending_tron_settlements", _boom)

    await _make_intent(amount=10.0)
    await tp._set_tron_cursor(tp.TRON_MAINNET, TS - 1)

    await tp.TronPoller(
        network=tp.TRON_MAINNET, node_urls=["https://api.trongrid.io"]
    )._tick()

    # Recorded despite the matcher blowing up...
    async with async_session() as db:
        n = (await db.execute(
            select(func.count()).select_from(PaymentSettlement)
        )).scalar_one()
    assert n == 1, "a matching bug prevented a settlement from being recorded"
    # ...and the cursor still advanced.
    assert await tp._get_tron_cursor(tp.TRON_MAINNET) == TS


@pytest.mark.asyncio
async def test_the_poller_tick_reports_matching_counts(monkeypatch):
    from app.services import tron_poller as tp

    async def _fake(network):
        return {"matched": 3, "partial": 1, "ambiguous": 2, "unmatched": 0}

    monkeypatch.setattr(tm, "match_pending_tron_settlements", _fake)
    await tp._set_tron_cursor(tp.TRON_MAINNET, 1)

    result = await tp.TronPoller(
        network=tp.TRON_MAINNET, node_urls=["https://x"]
    )._tick()

    assert result["matched"] == 3
    assert result["partial"] == 1
    assert result["ambiguous"] == 2


# ═══════════════════════════════════════════════════════════════
#  The dead matcher stays dead
# ═══════════════════════════════════════════════════════════════

def test_the_dead_matcher_is_not_revived():
    """It stays dead. The docstring explains why; the CODE must not call it."""
    from app.services import webhook_service

    code = code_without_prose(tm)
    for forbidden in ("match_transaction_to_intent", "finalize_match",
                      "match_and_complete_intent", "amount_tolerance_percent",
                      "allow_partial", "allow_overpayment"):
        assert forbidden not in code, f"the dead matcher leaked in: {forbidden}"

    # And it is still dead where it lives — this slice does not delete it.
    assert hasattr(webhook_service, "finalize_match")
    assert hasattr(webhook_service, "match_transaction_to_intent")


def test_the_matcher_never_folds_an_address():
    """`func.lower` on the CHAIN name is fine; on an address it is corruption."""
    code = code_without_prose(tm).replace("func.lower(PaymentIntent.chain)", "")
    assert ".lower()" not in code, (
        "an address comparison was case-folded; base58check is case-SENSITIVE"
    )
    assert "func.lower" not in code, (
        "a SQL-side fold crept in beyond the chain-name comparison"
    )
