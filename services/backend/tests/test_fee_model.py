"""
Fee-model backend tests (non-custodial flat fee).

Covers the Phase-B wiring:
  - PaymentMade 4-word decode incl. `fee`            (payment_indexer._decode_payment_made)
  - event-vs-invoice validation                       (payment_indexer._validate_event_against_intent)
  - settlement: valid -> paid + fee recorded;
    mismatch -> review, no completion                 (payment_indexer._record_settlement)
  - create-intent payload: live quoteFee -> fee/total/maxFee + maxFee calldata,
    and graceful degradation when the quote is unavailable
                                                       (router_registry.build_onchain_payment)
  - live quoteFee eth_call encode/parse               (router_registry.quote_fee_onchain)

These are self-contained (no running HTTP server); the DB-backed ones use the
app's async_session against the configured Postgres.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services import router_registry
from app.services.router_registry import (
    build_onchain_payment,
    quote_fee_onchain,
    token_for,
    to_base_units,
    _selector,
)
from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    _decode_payment_made,
    _validate_event_against_intent,
    _record_settlement,
    _finalize_and_reconcile,
)


class _FakeRPC:
    """Minimal mock for the finalize step: canonical block hash per number."""
    def __init__(self, block_hashes):
        self.block_hashes = block_hashes

    async def call(self, method, params, **kw):
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag in ("finalized", "safe"):
                return {"number": "0x0", "hash": "0x" + "00" * 32}
            bn = int(tag, 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": tag, "hash": h}
        raise AssertionError(f"unexpected RPC {method}")

USDC_ADDR, USDC_DEC = token_for("base", "USDC")  # ("0x8335..2913", 6)
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40

# Locked fee for €0.60 base in USDC smallest units.
BASE_FEE = 600000  # 0.60 * 10**6


# ── log/event builders ───────────────────────────────────────
def _word(n: int) -> str:
    return f"{n:064x}"


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def make_log(*, invoice_id, merchant, payer, token, amount, fee, ts,
             tx_hash="0x" + "ab" * 32, log_index=0, block=100):
    """Craft an eth_getLogs-shaped PaymentMade log (4 data words: token, amount, fee, ts)."""
    data = "0x" + _addr_word(token) + _word(amount) + _word(fee) + _word(ts)
    return {
        "topics": [PAYMENT_MADE_TOPIC, invoice_id, "0x" + _addr_word(merchant), "0x" + _addr_word(payer)],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block),
    }


# ═══════════════════════════════════════════════════════════════
#  Decode — the event now carries `fee` (data word 2)
# ═══════════════════════════════════════════════════════════════
class TestDecodePaymentMade:
    def test_decodes_fee_word(self):
        inv = "0x" + "cd" * 32
        log = make_log(
            invoice_id=inv, merchant=MERCHANT, payer=PAYER, token=USDC_ADDR,
            amount=100_000000, fee=BASE_FEE, ts=1_700_000_000, log_index=3, block=4242,
        )
        ev = _decode_payment_made(log)
        assert ev is not None
        assert ev["invoice_id"] == inv
        assert ev["merchant"] == MERCHANT.lower()
        assert ev["payer"] == PAYER.lower()
        assert ev["token"] == USDC_ADDR.lower()
        assert ev["amount"] == 100_000000
        assert ev["fee"] == BASE_FEE              # ← the bug fix: word 2 is fee, not block_ts
        assert ev["block_timestamp"] == 1_700_000_000
        assert ev["log_index"] == 3
        assert ev["block_number"] == 4242

    def test_rejects_short_data(self):
        # Only 3 words (old layout) → must be rejected, not mis-parsed.
        log = make_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT, payer=PAYER,
                       token=USDC_ADDR, amount=1, fee=1, ts=1)
        log["data"] = log["data"][: 2 + 64 * 3]   # truncate to 3 words
        assert _decode_payment_made(log) is None


# ═══════════════════════════════════════════════════════════════
#  Validation — event must match the stored invoice
# ═══════════════════════════════════════════════════════════════
class TestValidateEventAgainstIntent:
    def _intent(self):
        return SimpleNamespace(recipient=MERCHANT, chain="base", currency="USDC", amount=100.0)

    def _ev(self, **over):
        ev = {"merchant": MERCHANT.lower(), "token": USDC_ADDR.lower(), "amount": 100_000000}
        ev.update(over)
        return ev

    def test_valid_match(self):
        assert _validate_event_against_intent(self._ev(), self._intent()) == []

    def test_overpayment_is_valid(self):
        assert _validate_event_against_intent(self._ev(amount=200_000000), self._intent()) == []

    def test_wrong_merchant(self):
        reasons = _validate_event_against_intent(self._ev(merchant="0x" + "9" * 40), self._intent())
        assert any("merchant" in r for r in reasons)

    def test_wrong_token(self):
        reasons = _validate_event_against_intent(self._ev(token="0x" + "9" * 40), self._intent())
        assert any("token" in r for r in reasons)

    def test_underpayment(self):
        reasons = _validate_event_against_intent(self._ev(amount=99_000000), self._intent())
        assert any("amount" in r for r in reasons)


# ═══════════════════════════════════════════════════════════════
#  create-intent payload — live fee, maxFee, calldata, degradation
# ═══════════════════════════════════════════════════════════════
class TestBuildOnchainPayment:
    def _intent(self):
        return SimpleNamespace(
            chain="base", currency="USDC", amount=100.0, recipient=MERCHANT,
            onchain_invoice_id="0x" + "ab" * 32, reference_id="ref-onchain",
        )

    @pytest.mark.asyncio
    async def test_includes_fee_total_maxfee_and_calldata(self, monkeypatch):
        monkeypatch.setattr(router_registry, "router_address_for", lambda chain: "0x" + "9" * 40)

        async def fake_quote(cid, router, token, amount):
            return BASE_FEE
        monkeypatch.setattr(router_registry, "quote_fee_onchain", fake_quote)

        out = await build_onchain_payment(self._intent())
        amount_base = to_base_units(100.0, USDC_DEC)
        assert out["fee"] == str(BASE_FEE)
        assert out["total"] == str(amount_base + BASE_FEE)
        assert out["maxFee"] == str(BASE_FEE)          # payer ceiling == quoted fee
        assert out["feeUnavailable"] is False
        assert out["function"] == "pay"
        # calldata is pay(...,maxFee): selector + 5 words; ends with the maxFee word.
        assert out["calldata"].startswith("0x" + _selector("pay(bytes32,address,address,uint256,uint256)").hex())
        assert out["calldata"].endswith(_word(BASE_FEE))
        assert out["payWithPermitCalldata"] is not None

    @pytest.mark.asyncio
    async def test_degrades_when_quote_unavailable(self, monkeypatch):
        monkeypatch.setattr(router_registry, "router_address_for", lambda chain: "0x" + "9" * 40)

        async def fake_quote(cid, router, token, amount):
            return None  # router not deployed / RPC down
        monkeypatch.setattr(router_registry, "quote_fee_onchain", fake_quote)

        out = await build_onchain_payment(self._intent())
        assert out["feeUnavailable"] is True
        assert out["fee"] is None and out["total"] is None and out["maxFee"] is None
        assert out["calldata"] is None and out["payWithPermitCalldata"] is None
        # The static fields the frontend needs to self-quote are still present.
        assert out["token"] == USDC_ADDR and out["amount"] == str(to_base_units(100.0, USDC_DEC))


# ═══════════════════════════════════════════════════════════════
#  Live quoteFee eth_call — encode request, parse uint256 result
# ═══════════════════════════════════════════════════════════════
class TestQuoteFeeOnchain:
    @pytest.mark.asyncio
    async def test_encodes_call_and_parses_result(self, monkeypatch):
        router = "0x" + "9" * 40
        captured = {}

        class FakeRPC:
            async def call(self, method, params, **kw):
                captured["method"] = method
                captured["params"] = params
                return "0x" + _word(BASE_FEE)

        monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: FakeRPC())

        fee = await quote_fee_onchain(8453, router, USDC_ADDR, 100_000000)
        assert fee == BASE_FEE
        assert captured["method"] == "eth_call"
        call_obj = captured["params"][0]
        assert call_obj["to"] == router
        assert call_obj["data"].startswith("0x" + _selector("quoteFee(address,uint256)").hex())
        assert call_obj["data"].endswith(_word(100_000000))  # amount is the last arg word

    @pytest.mark.asyncio
    async def test_returns_none_on_rpc_error(self, monkeypatch):
        class BoomRPC:
            async def call(self, *a, **k):
                raise RuntimeError("rpc down")
        monkeypatch.setattr("app.services.rpc_manager.get_rpc_manager", lambda cid: BoomRPC())
        assert await quote_fee_onchain(8453, "0x" + "9" * 40, USDC_ADDR, 1) is None


# ═══════════════════════════════════════════════════════════════
#  Settlement (DB) — valid -> paid + fee; mismatch -> review
# ═══════════════════════════════════════════════════════════════
@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.settlement_models import PaymentSettlement
    from app.models.merchant_models import PaymentIntent
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Isolate the tables these tests touch from rows left by other tests/files.
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
    yield


async def _make_intent(*, invoice_id, recipient=MERCHANT, amount=100.0, currency="USDC", chain="base"):
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_fee_test",
            amount=amount,
            currency=currency,
            chain=chain,
            recipient=recipient,
            onchain_invoice_id=invoice_id.lower(),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


class TestRecordSettlement:
    """Two-phase lifecycle: _record_settlement only INGESTS (pending/rejected);
    _finalize_and_reconcile is what marks an invoice paid once it's final."""

    @pytest.mark.asyncio
    async def test_valid_event_ingests_pending_then_finalizes_paid(self):
        from app.db.session import async_session
        from app.models.merchant_models import PaymentIntent, IntentStatus
        from app.models.settlement_models import PaymentSettlement, SettlementStatus

        inv = "0x" + "11" * 32
        iid = await _make_intent(invoice_id=inv)
        bhash = "0x" + "a5" * 32

        ev = {
            "invoice_id": inv, "merchant": MERCHANT.lower(), "payer": PAYER.lower(),
            "token": USDC_ADDR.lower(), "amount": to_base_units(100.0, USDC_DEC),
            "fee": BASE_FEE, "block_timestamp": 1_700_000_000,
            "tx_hash": "0x" + "aa" * 32, "log_index": 0, "block_number": 500,
            "block_hash": bhash,
        }
        # INGEST → pending, fee recorded, invoice NOT yet paid.
        assert await _record_settlement(8453, ev) == "new"
        async with async_session() as db:
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
            )).scalar_one()
            assert stl.status == SettlementStatus.pending
            assert stl.fee == Decimal(BASE_FEE)
            assert stl.amount == Decimal(ev["amount"])
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == iid)
            )).scalar_one()
            assert intent.status == IntentStatus.pending

        # FINALIZE (canonical hash, block well below final_head) → paid.
        await _finalize_and_reconcile(8453, _FakeRPC({500: bhash}), final_head=600)
        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == iid)
            )).scalar_one()
            assert intent.status == IntentStatus.paid
            assert intent.matched_tx_hash == ev["tx_hash"]
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
            )).scalar_one()
            assert stl.status == SettlementStatus.final

    @pytest.mark.asyncio
    async def test_mismatched_merchant_rejected_and_review(self):
        from app.db.session import async_session
        from app.models.merchant_models import PaymentIntent, IntentStatus
        from app.models.settlement_models import PaymentSettlement, SettlementStatus

        inv = "0x" + "22" * 32
        iid = await _make_intent(invoice_id=inv)  # recipient == MERCHANT

        ev = {
            "invoice_id": inv, "merchant": ("0x" + "9" * 40).lower(), "payer": PAYER.lower(),
            "token": USDC_ADDR.lower(), "amount": to_base_units(100.0, USDC_DEC),
            "fee": BASE_FEE, "block_timestamp": 1_700_000_000,
            "tx_hash": "0x" + "bb" * 32, "log_index": 0, "block_number": 501,
            "block_hash": "0x" + "b5" * 32,
        }
        assert await _record_settlement(8453, ev) == "new"

        async with async_session() as db:
            intent = (await db.execute(
                select(PaymentIntent).where(PaymentIntent.intent_id == iid)
            )).scalar_one()
            assert intent.status == IntentStatus.review     # NOT paid
            assert intent.completed_at is None
            # settlement recorded as rejected (audit) with the on-chain fee.
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
            )).scalar_one()
            assert stl.status == SettlementStatus.rejected
            assert stl.fee == Decimal(BASE_FEE)

    @pytest.mark.asyncio
    async def test_idempotent_on_duplicate_log(self):
        inv = "0x" + "33" * 32
        await _make_intent(invoice_id=inv)
        ev = {
            "invoice_id": inv, "merchant": MERCHANT.lower(), "payer": PAYER.lower(),
            "token": USDC_ADDR.lower(), "amount": to_base_units(100.0, USDC_DEC),
            "fee": BASE_FEE, "block_timestamp": 1_700_000_000,
            "tx_hash": "0x" + "cc" * 32, "log_index": 7, "block_number": 502,
            "block_hash": "0x" + "c5" * 32,
        }
        assert await _record_settlement(8453, ev) == "new"
        assert await _record_settlement(8453, ev) == "duplicate"  # same log+hash → no-op
