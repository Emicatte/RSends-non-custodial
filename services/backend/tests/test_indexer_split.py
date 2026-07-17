"""SplitPaymentMade indexing — one aggregate event, ONE settlement row, the
whole recipients/amounts vector validated against the stored split.

Atomic all-or-nothing settlement is STRUCTURAL here: a single settlement row
represents every leg (the contract reverts unless all legs transferred), so no
partial state can exist. The battle-tested finalize/reverse/webhook-once
machinery is reused untouched — these tests prove a split settles through it
and that every tampered variant records `rejected` and never settles.

Fabricated events mirror _decode_split_payment_made output; the watcher test
feeds a raw ABI-encoded log through PaymentWatcher._tick (FakeChain) to cover
the decoder + the address/topic source-authenticity pairing.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, func

import app.services.payment_indexer as idx
from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PaymentWatcher,
    _record_settlement,
    _finalize_and_reconcile,
)
from app.services.router_registry import token_for, to_base_units
from app.services.split_math import compute_split_amounts

from tests.test_payment_indexer_reorg import FakeChain

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
ROUTER = "0x" + "a" * 40
SPLIT_ROUTER = "0x" + "b" * 40
ALICE = "0x" + "1" * 40   # position 0 = primary
BOB = "0x" + "3" * 40
PAYER = "0x" + "2" * 40
CHAIN = 8453
TOTAL = to_base_units(100.0, USDC_DEC)  # 100_000000
BPS = [7000, 3000]
LEG_AMOUNTS = compute_split_amounts(TOTAL, BPS)  # [70_000000, 30_000000]


# ── DB + webhook fixtures ────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    from app.models.settlement_models import PaymentSettlement
    from app.models.merchant_models import PaymentIntent, PaymentIntentRecipient

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntentRecipient.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


@pytest.fixture
def webhook_calls(monkeypatch):
    """Capture (event, extra_payload) pairs — proves fire-once AND the additive
    split block in the payload."""
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append((event, extra_payload or {}))
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers ──────────────────────────────────────────────────
async def _make_split_intent(*, invoice_id, legs=None, amount=100.0,
                             currency="USDC", chain="base"):
    """A split intent: recipient NULL + N child rows (position order)."""
    from app.db.session import async_session
    from app.models.merchant_models import (
        IntentStatus, PaymentIntent, PaymentIntentRecipient,
    )

    legs = legs if legs is not None else [(ALICE, 7000), (BOB, 3000)]
    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_split_test",
            amount=amount,
            currency=currency,
            chain=chain,
            recipient=None,  # split: no single payee
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        for pos, (addr, bps) in enumerate(legs):
            db.add(PaymentIntentRecipient(
                intent_id=iid, position=pos, address=addr.lower(), share_bps=bps,
            ))
        await db.commit()
    return iid


async def _make_single_intent(*, invoice_id, recipient=ALICE):
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_split_test",
            amount=100.0,
            currency="USDC",
            chain="base",
            recipient=recipient,
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


def _split_ev(*, invoice_id, tx_hash, block_number, block_hash,
              recipients=None, amounts=None, token=USDC_ADDR, total=TOTAL,
              log_index=0):
    """Fabricated _decode_split_payment_made output."""
    recipients = recipients if recipients is not None else [ALICE, BOB]
    amounts = amounts if amounts is not None else list(LEG_AMOUNTS)
    return {
        "invoice_id": invoice_id.lower(),
        "merchant": recipients[0].lower(),   # primary → settlement.merchant
        "payer": PAYER.lower(),
        "token": token.lower(),
        "amount": total,
        "fee": 0,                            # SplitRouter is fee-less
        "block_timestamp": 1_700_000_000,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "block_number": block_number,
        "block_hash": block_hash.lower(),
        "split": {
            "recipients": [r.lower() for r in recipients],
            "amounts": list(amounts),
        },
    }


def _ev_single(*, invoice_id, tx_hash, block_number, block_hash,
               merchant=ALICE, token=USDC_ADDR, amount=TOTAL, log_index=0):
    return {
        "invoice_id": invoice_id.lower(),
        "merchant": merchant.lower(),
        "payer": PAYER.lower(),
        "token": token.lower(),
        "amount": amount,
        "fee": 600000,
        "block_timestamp": 1_700_000_000,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "block_number": block_number,
        "block_hash": block_hash.lower(),
    }


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def _word(n: int) -> str:
    return f"{n:064x}"


def _make_split_log(*, invoice_id, tx_hash, block_number, block_hash,
                    address=SPLIT_ROUTER, recipients=None, amounts=None,
                    token=USDC_ADDR, total=TOTAL, log_index=0):
    """Raw ABI-encoded SplitPaymentMade log (dynamic tails with offsets)."""
    recipients = recipients if recipients is not None else [ALICE, BOB]
    amounts = amounts if amounts is not None else list(LEG_AMOUNTS)
    n = len(recipients)
    off_recipients = 5 * 32
    off_amounts = off_recipients + 32 * (1 + n)
    data = (
        "0x"
        + _addr_word(token)
        + _word(total)
        + _word(off_recipients)
        + _word(off_amounts)
        + _word(1_700_000_000)
        + _word(n) + "".join(_addr_word(r) for r in recipients)
        + _word(n) + "".join(_word(a) for a in amounts)
    )
    return {
        "address": address,
        "topics": [
            idx.SPLIT_PAYMENT_MADE_TOPIC,
            invoice_id,
            "0x" + _addr_word(PAYER),
        ],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block_number),
        "blockHash": block_hash,
    }


async def _settlement(tx_hash):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        return (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == tx_hash.lower())
        )).scalar_one_or_none()


async def _settlement_count():
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(PaymentSettlement)
        )).scalar_one()


async def _intent(iid):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()


# ═══════════════════════════════════════════════════════════════
#  Happy path — a split settles through the untouched machinery
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_split_event_settles_intent(webhook_calls):
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "21" * 32
    iid = await _make_split_intent(invoice_id=inv)
    H = "0x" + "b1" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    ev = _split_ev(invoice_id=inv, tx_hash="0x" + "ba" * 32, block_number=100, block_hash=H)

    # INGEST → ONE pending settlement row (atomicity is structural), NOT paid.
    assert await _record_settlement(CHAIN, ev) == "new"
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.pending
    assert await _settlement_count() == 1
    assert s.split_legs == [
        {"address": ALICE, "share_bps": 7000, "amount": str(LEG_AMOUNTS[0])},
        {"address": BOB, "share_bps": 3000, "amount": str(LEG_AMOUNTS[1])},
    ]
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []

    # FINALIZE → final + paid + webhook once, split block in the payload.
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 1
    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.final and s.webhook_fired_at is not None
    assert (await _intent(iid)).status == IntentStatus.paid
    assert [c[0] for c in webhook_calls] == ["payment.completed"]
    assert webhook_calls[0][1]["split"] == s.split_legs

    # Idempotent: no second webhook.
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert [c[0] for c in webhook_calls] == ["payment.completed"]


# ═══════════════════════════════════════════════════════════════
#  Tampered variants — rejected, never settle, no webhook
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_tampered_leg_amounts_rejected(webhook_calls):
    """Event leg amounts differing from the deterministic math over the stored
    BPS (e.g. a hostile RPC or a spoofed contract) → rejected, review, no pay."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "22" * 32
    iid = await _make_split_intent(invoice_id=inv)
    H = "0x" + "b2" * 32
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    tampered = [LEG_AMOUNTS[0] - 1, LEG_AMOUNTS[1] + 1]  # conserved but wrong split
    ev = _split_ev(invoice_id=inv, tx_hash="0x" + "bb" * 32, block_number=100,
                   block_hash=H, amounts=tampered)

    await _record_settlement(CHAIN, ev)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert (await _intent(iid)).status == IntentStatus.review

    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert (await _intent(iid)).status == IntentStatus.review
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_wrong_recipient_set_rejected(webhook_calls):
    from app.models.settlement_models import SettlementStatus

    inv = "0x" + "23" * 32
    await _make_split_intent(invoice_id=inv)
    H = "0x" + "b3" * 32
    intruder = "0x" + "9" * 40
    ev = _split_ev(invoice_id=inv, tx_hash="0x" + "bc" * 32, block_number=100,
                   block_hash=H, recipients=[ALICE, intruder])

    await _record_settlement(CHAIN, ev)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_underpaid_split_total_rejected(webhook_calls):
    from app.models.settlement_models import SettlementStatus

    inv = "0x" + "24" * 32
    await _make_split_intent(invoice_id=inv)
    H = "0x" + "b4" * 32
    short = TOTAL - 1
    ev = _split_ev(invoice_id=inv, tx_hash="0x" + "bd" * 32, block_number=100,
                   block_hash=H, total=short,
                   amounts=compute_split_amounts(short, BPS))

    await _record_settlement(CHAIN, ev)
    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_cross_type_events_rejected(webhook_calls):
    """Fail-closed both ways: a split event against a single-recipient intent,
    and a single PaymentMade against a split intent, both record rejected."""
    from app.models.settlement_models import SettlementStatus

    # split event → single intent
    inv1 = "0x" + "25" * 32
    await _make_single_intent(invoice_id=inv1)
    ev1 = _split_ev(invoice_id=inv1, tx_hash="0x" + "be" * 32, block_number=100,
                    block_hash="0x" + "b5" * 32)
    await _record_settlement(CHAIN, ev1)
    assert (await _settlement(ev1["tx_hash"])).status == SettlementStatus.rejected

    # single event → split intent (recipient NULL → pre-existing fail-closed)
    inv2 = "0x" + "26" * 32
    await _make_split_intent(invoice_id=inv2)
    ev2 = _ev_single(invoice_id=inv2, tx_hash="0x" + "bf" * 32, block_number=100,
                     block_hash="0x" + "b6" * 32)
    await _record_settlement(CHAIN, ev2)
    assert (await _settlement(ev2["tx_hash"])).status == SettlementStatus.rejected

    assert webhook_calls == []


# ═══════════════════════════════════════════════════════════════
#  End-to-end through the watcher: raw log → decode → settle
# ═══════════════════════════════════════════════════════════════
async def _async_return(v):
    return v


async def _async_set(d, c, b):
    d[c] = b


@pytest.mark.asyncio
async def test_watcher_decodes_and_settles_raw_split_log(monkeypatch, webhook_calls):
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "27" * 32
    iid = await _make_split_intent(invoice_id=inv)

    H = "0x" + "27" * 32
    rpc = FakeChain()
    rpc.latest = 110
    rpc.finalized = 108
    rpc.block_hashes[105] = H
    rpc.logs = [_make_split_log(invoice_id=inv, tx_hash="0x" + "c0" * 32,
                                block_number=105, block_hash=H)]

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    cursor = {CHAIN: 100}
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))

    w = PaymentWatcher(
        chain_id=CHAIN, router_address=ROUTER, split_router_address=SPLIT_ROUTER
    )
    await w._tick()  # scans 101..110, split log at 105, finalized (105 <= 108)

    assert (await _intent(iid)).status == IntentStatus.paid
    assert await _settlement_count() == 1
    assert [c[0] for c in webhook_calls] == ["payment.completed"]


@pytest.mark.asyncio
async def test_watcher_drops_split_log_from_wrong_address(monkeypatch, webhook_calls):
    """Source authenticity: a SplitPaymentMade emitted by anything but THIS
    chain's split router (incl. the main router) is dropped, never recorded."""
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "28" * 32
    iid = await _make_split_intent(invoice_id=inv)

    H = "0x" + "28" * 32
    rpc = FakeChain()
    rpc.latest = 110
    rpc.finalized = 108
    rpc.block_hashes[105] = H
    rpc.logs = [
        # spoof 1: split event from the MAIN router address
        _make_split_log(invoice_id=inv, tx_hash="0x" + "c1" * 32,
                        block_number=105, block_hash=H, address=ROUTER),
        # spoof 2: split event from a random contract
        _make_split_log(invoice_id=inv, tx_hash="0x" + "c2" * 32,
                        block_number=105, block_hash=H, address="0x" + "d" * 40),
    ]

    monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: rpc)
    cursor = {CHAIN: 100}
    monkeypatch.setattr(idx, "_get_last_block", lambda c: _async_return(cursor.get(c)))
    monkeypatch.setattr(idx, "_set_last_block", lambda c, b: _async_set(cursor, c, b))

    w = PaymentWatcher(
        chain_id=CHAIN, router_address=ROUTER, split_router_address=SPLIT_ROUTER
    )
    await w._tick()

    assert await _settlement_count() == 0
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []
