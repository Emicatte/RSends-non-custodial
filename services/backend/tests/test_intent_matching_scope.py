"""F-3/F-4: who and what can touch an intent's state via event matching.

Root cause under both findings: an on-chain PaymentMade is matched to an
intent by PUBLIC invoiceId alone, and the match is allowed to mutate the
intent's user-visible state even when validation fails.

Invariants pinned here:
  - F-4(a): a stranger's payment (wrong merchant / under-amount) NEVER changes
    a pending intent's user-visible state — recorded `rejected`, intent
    untouched, and the real payment still completes.
  - F-4(b): payability/validity is checked BEFORE a settlement is stamped
    final — an invalid-at-finalize settlement lands `rejected`, never
    final-and-stranded; a valid settlement rescues an intent stuck in
    `review` (griefed before this fix).
  - F-3: matching is scoped by chain_id AND environment IN the query —
    the same invoiceId on the wrong chain or wrong environment is an orphan
    (no intent link, nothing mutated). invoiceId alone is not sufficient.
  - derive_invoice_id folds the chain id: the same reference_id derives
    different invoice ids on different chains (cross-chain replay defense).

All RPC mocked (FakeChain, as in test_late_settlement_rescue). Run:
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_intent_matching_scope.py
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services.payment_indexer import _record_settlement, _finalize_and_reconcile
from app.services.router_registry import derive_invoice_id, token_for, to_base_units

USDC_ADDR, USDC_DEC = token_for("base_sepolia", "USDC")
MERCHANT = "0x" + "1" * 40
STRANGER = "0x" + "9" * 40
PAYER = "0x" + "2" * 40
CHAIN = 84532          # base_sepolia — environment "test"
WRONG_CHAIN = 8453     # base mainnet — environment "live"
AMT = to_base_units(100.0, USDC_DEC)


@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.settlement_models import PaymentSettlement
    from app.models.merchant_models import PaymentIntent, PaymentIntentRecipient
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntentRecipient.__table__.delete())  # FK child before parent
        await conn.execute(PaymentIntent.__table__.delete())
    yield


@pytest.fixture
def webhook_calls(monkeypatch):
    calls = []

    async def _fake_send_webhook(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append(event)
        return None

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake_send_webhook)
    return calls


# ── helpers ──────────────────────────────────────────────────
async def _make_intent(*, invoice_id, status=None, chain="base_sepolia",
                       environment="test", merchant_id="m_scope_test"):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id=merchant_id,
            environment=environment,
            amount=100.0,
            currency="USDC",
            chain=chain,
            recipient=MERCHANT,
            onchain_invoice_id=invoice_id.lower(),
            status=status or IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


def _ev(*, invoice_id, tx_hash, block_number=100, block_hash=None, log_index=0,
        merchant=MERCHANT, amount=AMT):
    return {
        "invoice_id": invoice_id.lower(),
        "merchant": merchant.lower(),
        "payer": PAYER.lower(),
        "token": USDC_ADDR.lower(),
        "amount": amount,
        "fee": 600000,
        "block_timestamp": 1_700_000_000,
        "tx_hash": tx_hash.lower(),
        "log_index": log_index,
        "block_number": block_number,
        "block_hash": (block_hash or tx_hash).lower(),
    }


class FakeChain:
    """eth_getBlockByNumber-only mock — enough for _finalize_and_reconcile."""
    def __init__(self):
        self.block_hashes: dict[int, str] = {}

    async def call(self, method, params, **kw):
        if method == "eth_getBlockByNumber":
            bn = int(params[0], 16)
            h = self.block_hashes.get(bn)
            return None if h is None else {"number": hex(bn), "hash": h}
        raise AssertionError(f"unexpected RPC {method}")


async def _intent(iid):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        return (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()


async def _settlement(tx_hash):
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        return (await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.tx_hash == tx_hash.lower())
        )).scalar_one_or_none()


async def _set_intent(iid, **fields):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        row = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == iid)
        )).scalar_one()
        for k, v in fields.items():
            setattr(row, k, v)
        await db.commit()


# ═══════════════════════════════════════════════════════════════
#  F-4(a): a stranger's payment never touches a pending intent
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_wrong_merchant_event_does_not_touch_pending_intent(webhook_calls):
    """The griefing vector reachable on testnet today: a PaymentMade with the
    right (public) invoiceId but the wrong merchant must be recorded rejected
    WITHOUT flipping the intent to review or stamping matched_tx_hash — and
    the honest payment must still complete afterwards."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "41" * 32
    iid = await _make_intent(invoice_id=inv)

    grief = _ev(invoice_id=inv, tx_hash="0x" + "e1" * 32, merchant=STRANGER, amount=1)
    assert await _record_settlement(CHAIN, grief) == "new"

    s = await _settlement(grief["tx_hash"])
    assert s.status == SettlementStatus.rejected
    intent = await _intent(iid)
    assert intent.status == IntentStatus.pending      # NOT review
    assert intent.matched_tx_hash is None             # NOT the stranger's tx
    assert intent.matched_at is None

    # The honest payer now pays: it must match, finalize, and complete.
    H = "0x" + "e2" * 32
    real = _ev(invoice_id=inv, tx_hash="0x" + "e2" * 32, block_hash=H)
    assert await _record_settlement(CHAIN, real) == "new"
    rpc = FakeChain()
    rpc.block_hashes[100] = H
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 1

    intent = await _intent(iid)
    assert intent.status == IntentStatus.paid
    assert intent.matched_tx_hash == real["tx_hash"]
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_underpayment_event_does_not_touch_pending_intent(webhook_calls):
    """Same invariant for under-amount (1 wei to the RIGHT merchant)."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "42" * 32
    iid = await _make_intent(invoice_id=inv)

    grief = _ev(invoice_id=inv, tx_hash="0x" + "e3" * 32, amount=1)
    await _record_settlement(CHAIN, grief)

    assert (await _settlement(grief["tx_hash"])).status == SettlementStatus.rejected
    intent = await _intent(iid)
    assert intent.status == IntentStatus.pending
    assert intent.matched_tx_hash is None
    assert webhook_calls == []


# ═══════════════════════════════════════════════════════════════
#  F-4(b): payability/validity BEFORE the final stamp
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_invalid_at_finalize_lands_rejected_not_final_stranded(webhook_calls):
    """A settlement that fails validation at finalize time must NOT be stamped
    final (which would strand it forever — the reconcile loop only revisits
    pending rows). It lands rejected; the intent is untouched."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "43" * 32
    iid = await _make_intent(invoice_id=inv)
    H = "0x" + "e4" * 32
    ev = _ev(invoice_id=inv, tx_hash="0x" + "e4" * 32, block_hash=H)
    await _record_settlement(CHAIN, ev)  # valid at ingest → pending

    # Drift between ingest and finalize (defensive path): recipient changed.
    await _set_intent(iid, recipient=STRANGER)

    rpc = FakeChain()
    rpc.block_hashes[100] = H
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 0

    s = await _settlement(ev["tx_hash"])
    assert s.status == SettlementStatus.rejected      # NOT final
    intent = await _intent(iid)
    assert intent.status == IntentStatus.pending      # NOT review
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_valid_settlement_rescues_review_intent(webhook_calls):
    """An intent stuck in `review` (griefed before this fix, or flagged by the
    legacy matching path) is rescued by its real, VALID settlement: review →
    paid + payment.completed. Stranding money because a stranger sent 1 wei
    first is not acceptable."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "44" * 32
    iid = await _make_intent(invoice_id=inv, status=IntentStatus.review)
    H = "0x" + "e5" * 32
    ev = _ev(invoice_id=inv, tx_hash="0x" + "e5" * 32, block_hash=H)
    await _record_settlement(CHAIN, ev)

    rpc = FakeChain()
    rpc.block_hashes[100] = H
    res = await _finalize_and_reconcile(CHAIN, rpc, final_head=200)
    assert res["finalized"] == 1

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.final
    intent = await _intent(iid)
    assert intent.status == IntentStatus.paid
    assert webhook_calls == ["payment.completed"]


@pytest.mark.asyncio
async def test_invalid_settlement_leaves_review_intent_untouched(webhook_calls):
    """review + INVALID settlement: the settlement lands rejected and the
    intent stays review (needs the human it was flagged for)."""
    from app.models.settlement_models import SettlementStatus
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "45" * 32
    iid = await _make_intent(invoice_id=inv, status=IntentStatus.review)
    H = "0x" + "e6" * 32
    ev = _ev(invoice_id=inv, tx_hash="0x" + "e6" * 32, block_hash=H)
    await _record_settlement(CHAIN, ev)
    await _set_intent(iid, recipient=STRANGER)  # make it invalid at finalize

    rpc = FakeChain()
    rpc.block_hashes[100] = H
    await _finalize_and_reconcile(CHAIN, rpc, final_head=200)

    assert (await _settlement(ev["tx_hash"])).status == SettlementStatus.rejected
    assert (await _intent(iid)).status == IntentStatus.review
    assert webhook_calls == []


# ═══════════════════════════════════════════════════════════════
#  F-3: matching is scoped by chain_id AND environment
# ═══════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_event_on_wrong_chain_does_not_match(webhook_calls):
    """Same invoiceId observed on a DIFFERENT chain is an orphan: no intent
    link, nothing mutated. This is the native-ETH cross-chain replay defense
    (ZERO_ADDRESS is the same token address on every chain, so only chain
    scoping can stop it)."""
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "46" * 32
    iid = await _make_intent(invoice_id=inv, chain="base_sepolia", environment="test")

    ev = _ev(invoice_id=inv, tx_hash="0x" + "e7" * 32)
    assert await _record_settlement(WRONG_CHAIN, ev) == "new"

    s = await _settlement(ev["tx_hash"])
    assert s is not None
    assert s.intent_id is None                        # orphan, not matched
    intent = await _intent(iid)
    assert intent.status == IntentStatus.pending
    assert intent.matched_tx_hash is None
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_event_on_wrong_environment_does_not_match(webhook_calls):
    """Defense-in-depth: even where the chain name passes, an environment
    mismatch refuses the match IN the query (a test event can never touch a
    live intent and vice versa)."""
    from app.models.merchant_models import IntentStatus

    inv = "0x" + "47" * 32
    # Directly-inserted pathological row: mainnet chain but test environment
    # (the create gate forbids this combination — the indexer must not trust it).
    iid = await _make_intent(invoice_id=inv, chain="base", environment="test")

    ev = _ev(invoice_id=inv, tx_hash="0x" + "e8" * 32)
    await _record_settlement(WRONG_CHAIN, ev)  # chain 8453 → environment "live"

    s = await _settlement(ev["tx_hash"])
    assert s.intent_id is None
    assert (await _intent(iid)).status == IntentStatus.pending
    assert webhook_calls == []


@pytest.mark.asyncio
async def test_right_chain_and_environment_still_matches(webhook_calls):
    """Control: the scoping must not break legitimate matching — chain name is
    matched case-insensitively (the column stores merchant-provided casing)."""
    from app.models.settlement_models import SettlementStatus

    inv = "0x" + "48" * 32
    iid = await _make_intent(invoice_id=inv, chain="BASE_SEPOLIA", environment="test")

    ev = _ev(invoice_id=inv, tx_hash="0x" + "e9" * 32)
    await _record_settlement(CHAIN, ev)

    s = await _settlement(ev["tx_hash"])
    assert s.intent_id == iid
    assert s.status == SettlementStatus.pending


# ═══════════════════════════════════════════════════════════════
#  derive_invoice_id folds the chain id
# ═══════════════════════════════════════════════════════════════
def test_derive_invoice_id_differs_per_chain():
    ref = "ref_abc123"
    a = derive_invoice_id(ref, 84532)
    b = derive_invoice_id(ref, 8453)
    assert a != b
    assert a.startswith("0x") and len(a) == 66
    assert b.startswith("0x") and len(b) == 66


def test_derive_invoice_id_formula_is_pinned():
    """keccak256(f"{chain_id}:{reference_id}") — the payer-facing id every
    /pay link carries; changing this silently orphans in-flight invoices."""
    from eth_utils import keccak

    ref = "ref_pinned"
    assert derive_invoice_id(ref, 84532) == "0x" + keccak(b"84532:ref_pinned").hex()
