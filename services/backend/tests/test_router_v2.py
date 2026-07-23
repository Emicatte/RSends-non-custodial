"""
RSendsRouterV2 backend wiring — the fee-less, ownerless mainnet router.

The v2 PaymentMade event drops the fee word (6 args, 3 data words). These
tests pin the decode, the settlement ingest (fee stored as 0 — the
SplitPaymentMade precedent), and — in later slices in this same file — the
dual-topic watcher filter and the v2 `build_onchain_payment` branch.

Same conventions as test_fee_model.py: self-contained, DB-backed cases use
the app's async_session against the configured Postgres.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.services.payment_indexer import (
    PAYMENT_MADE_TOPIC,
    PAYMENT_MADE_V2_TOPIC,
    _decode_payment_made,
    _decode_payment_made_v2,
    _record_settlement,
)
from app.services.router_registry import token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base", "USDC")
MERCHANT = "0x" + "1" * 40
PAYER = "0x" + "2" * 40


# ── log builders (v2 layout: 3 data words — token, amount, blockTimestamp) ──
def _word(n: int) -> str:
    return f"{n:064x}"


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def make_v2_log(*, invoice_id, merchant, payer, token, amount, ts,
                tx_hash="0x" + "ab" * 32, log_index=0, block=100,
                block_hash="0x" + "a5" * 32):
    data = "0x" + _addr_word(token) + _word(amount) + _word(ts)
    return {
        "topics": [PAYMENT_MADE_V2_TOPIC, invoice_id,
                   "0x" + _addr_word(merchant), "0x" + _addr_word(payer)],
        "data": data,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
        "blockNumber": hex(block),
        "blockHash": block_hash,
    }


# ═══════════════════════════════════════════════════════════════
#  Decode — 3 data words, NO fee word; fee normalized to 0
# ═══════════════════════════════════════════════════════════════
class TestDecodePaymentMadeV2:
    def test_decodes_three_words_fee_is_zero(self):
        inv = "0x" + "cd" * 32
        log = make_v2_log(
            invoice_id=inv, merchant=MERCHANT, payer=PAYER, token=USDC_ADDR,
            amount=100_000000, ts=1_700_000_000, log_index=3, block=4242,
        )
        ev = _decode_payment_made_v2(log)
        assert ev is not None
        assert ev["invoice_id"] == inv
        assert ev["merchant"] == MERCHANT.lower()
        assert ev["payer"] == PAYER.lower()
        assert ev["token"] == USDC_ADDR.lower()
        assert ev["amount"] == 100_000000
        assert ev["fee"] == 0                      # no fee word exists — normalized 0
        assert ev["block_timestamp"] == 1_700_000_000   # word 2, NOT word 3
        assert ev["log_index"] == 3
        assert ev["block_number"] == 4242

    def test_rejects_short_data(self):
        # Only 2 words → must be rejected, not mis-parsed.
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        log["data"] = log["data"][: 2 + 64 * 2]
        assert _decode_payment_made_v2(log) is None

    def test_rejects_v1_topic(self):
        """A v1 log fed to the v2 decoder must return None — the dispatch keys
        on topic0 and each decoder re-checks it (defence-in-depth)."""
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        log["topics"][0] = PAYMENT_MADE_TOPIC
        assert _decode_payment_made_v2(log) is None

    def test_v1_decoder_rejects_v2_log(self):
        """The reverse direction: a v2 log (v2 topic, 3 words) must not be
        accepted by the v1 decoder — neither by topic nor by data length."""
        log = make_v2_log(invoice_id="0x" + "00" * 32, merchant=MERCHANT,
                          payer=PAYER, token=USDC_ADDR, amount=1, ts=1)
        assert _decode_payment_made(log) is None


# ═══════════════════════════════════════════════════════════════
#  Settlement ingest — v2 event stores fee == 0 (nullable column untouched)
# ═══════════════════════════════════════════════════════════════
async def _make_intent(*, invoice_id, recipient=MERCHANT, amount=100.0,
                       currency="USDC", chain="base"):
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id="m_router_v2_test",
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


class TestRecordSettlementV2:
    @pytest.mark.asyncio
    async def test_v2_event_ingests_with_zero_fee(self):
        from app.db.session import async_session
        from app.models.settlement_models import PaymentSettlement, SettlementStatus

        inv = "0x" + "e1" * 32
        await _make_intent(invoice_id=inv)

        log = make_v2_log(
            invoice_id=inv, merchant=MERCHANT, payer=PAYER, token=USDC_ADDR,
            amount=to_base_units(100.0, USDC_DEC), ts=1_700_000_000,
            tx_hash="0x" + "e2" * 32, block=500,
        )
        ev = _decode_payment_made_v2(log)
        assert ev is not None

        assert await _record_settlement(8453, ev) == "new"
        async with async_session() as db:
            stl = (await db.execute(
                select(PaymentSettlement).where(PaymentSettlement.tx_hash == ev["tx_hash"])
            )).scalar_one()
            assert stl.status == SettlementStatus.pending
            assert stl.fee == Decimal(0)
            assert stl.amount == Decimal(ev["amount"])
