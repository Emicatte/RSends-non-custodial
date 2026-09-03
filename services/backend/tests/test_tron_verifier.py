"""B2 — the transfer verifier, against responses Nile actually gave.

Every fixture in `tests/fixtures/tron/` was recorded from nile.trongrid.io; see
the README there. Nothing in this file touches the network, and nothing invents
a response shape: where a test needs a failure the chain did not hand us, it
mutates a copy of a real one and says so.

The load-bearing test is `test_the_verifier_and_the_poller_agree_on_the_log_index`.
The verifier and the poller reach the same transaction from opposite ends — the
verifier from a hash, the poller from an address scan — and they must derive the
same `(chain_id, tx_hash, log_index)`, because that triple is the settlement
idempotency key. If they ever disagreed, one payment would be written twice.
"""

import copy
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio

from app.services import tron_poller as tp
from app.services import tron_verifier as tv
from app.services.tron_verifier import Pending, Rejected, Verified, verify_transfer
from tests._source_helpers import code_without_prose

FIXTURES = Path(__file__).parent / "fixtures" / "tron"

MERCHANT = "TAGfrptqq5mAK8EqJcXJeaTxf4zNYnUBpL"
PAYER = "TNHUQgX2C1bSxdfuKZM855FY6QfPWLJiEa"
STRANGER = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"

TX_2_5 = "07f1b19de88dec6213e95b96715bfa3198b1ab38d7228810d46c3a2e25ff91d3"
TX_2_5_B = "e43d56193c9f28f587b560f47003eb8de8ab231f535c6b58f5786769f6064248"
TX_3_0 = "75e4fda0a1c1bb9c0c27d4e876e7a21a5a0bdca5ebb3727eb959c7b467f57a75"
TX_OUTBOUND = "b58adf31fb2e20491c99fba627fc5d8683618902e644f422b3958ae4fb0fab1c"
TX_TRX_ONLY = "254814d8a00c43eea66d5645d16208f0e6f58e8318e014374201c90dce6c76d5"

NILE = tp.TRON_NILE


def _load(tx_hash: str, name: str):
    return json.loads((FIXTURES / tx_hash / f"{name}.json").read_text())


@dataclass
class FakeIntent:
    """Only the attributes the verifier reads. Keeps B2 free of the ORM."""

    chain: str = "tron_nile"
    recipient: str = MERCHANT
    amount: float = 2.5
    expected_sender: Optional[str] = None


class FixtureSource:
    """Serves recorded responses, with per-test mutation.

    A fixture, not a mock: it replays what the node actually said. Every
    mutation deep-copies first, so one test cannot contaminate another and the
    files on disk are never rewritten.

    `present=False` models the two cases the solidity node cannot tell apart —
    a hash that does not exist, and one that has not solidified — both of which
    it answers with `{}`.
    """

    def __init__(self, tx_hash: str, *, present: bool = True):
        self.info = _load(tx_hash, "gettransactioninfobyid") if present else {}
        self.tx = _load(tx_hash, "gettransactionbyid") if present else {}
        self.event_list = _load(tx_hash, "events")["data"] if present else []

    def mutate_info(self, **kw) -> "FixtureSource":
        """`receipt__result="REVERT"` sets `info["receipt"]["result"]`."""
        self.info = copy.deepcopy(self.info)
        for path, value in kw.items():
            node = self.info
            *parents, leaf = path.split("__")
            for parent in parents:
                node = node.setdefault(parent, {})
            node[leaf] = value
        return self

    def mutate_event(self, index: int, **kw) -> "FixtureSource":
        """`result_to=...` sets `event["result"]["to"]`; anything else is a top-level key."""
        self.event_list = copy.deepcopy(self.event_list)
        for key, value in kw.items():
            if key.startswith("result_"):
                self.event_list[index]["result"][key[len("result_"):]] = value
            else:
                self.event_list[index][key] = value
        return self

    async def transaction_info(self, tx_hash: str) -> dict:
        return self.info

    async def transaction(self, tx_hash: str) -> dict:
        return self.tx

    async def events(self, tx_hash: str) -> list:
        return self.event_list


# ═══════════════════════════════════════════════════════════════
#  The happy path, on three real transfers
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tx_hash,amount",
    [(TX_2_5, 2.5), (TX_2_5_B, 2.5), (TX_3_0, 3.0)],
)
async def test_a_real_transfer_verifies(tx_hash, amount):
    result = await verify_transfer(
        NILE, tx_hash, FakeIntent(amount=amount), PAYER,
        source=FixtureSource(tx_hash),
    )
    assert isinstance(result, Verified), result

    transfer, event = result.settlement_input
    # base58 in, base58 out: a settlement row stores what a human can check
    # against an explorer, and nothing here re-encodes an address.
    assert transfer["to"] == MERCHANT
    assert transfer["from"] == PAYER
    assert transfer["token_info"]["address"] == NILE.usdt_contract
    # The value comes from the chain, not from the invoice.
    assert transfer["value"] == str(int(amount * 1_000_000))
    assert int(event["block_number"]) > 0


@pytest.mark.asyncio
async def test_the_verifier_and_the_poller_agree_on_the_log_index():
    """The settlement idempotency key cannot diverge between the two paths.

    The poller starts from an address scan and the verifier starts from a hash.
    Both must land on the same `(chain_id, tx_hash, log_index)` or
    `uq_settlement_onchain_log` would accept both and book one payment twice.
    """
    discovery = json.loads(
        (FIXTURES / f"discovery_trc20_{MERCHANT}.json").read_text()
    )["data"]
    scanned = next(t for t in discovery if t["transaction_id"] == TX_2_5)
    events = _load(TX_2_5, "events")["data"]

    # What the POLLER derives, from the transfer its own scan produced.
    poller_event = tp._pair_transfer_to_event(scanned, events)

    # What the VERIFIER derives, from nothing but the hash.
    verified = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=FixtureSource(TX_2_5)
    )
    assert isinstance(verified, Verified)

    assert int(verified.event["event_index"]) == int(poller_event["event_index"])
    assert int(verified.event["block_number"]) == int(poller_event["block_number"])
    # The whole key, spelled out, because that is the thing that must match.
    assert (NILE.chain_id, TX_2_5, int(verified.event["event_index"])) == (
        NILE.chain_id, TX_2_5, int(poller_event["event_index"])
    )


# ═══════════════════════════════════════════════════════════════
#  Pending — never Rejected
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_an_unknown_hash_is_pending_not_rejected():
    # The solidity node answers {} for a hash it has never seen AND for one
    # that has not solidified yet. Calling either fake would eventually call a
    # real payment fake, seconds before it lands.
    result = await verify_transfer(
        NILE, "ab" * 32, FakeIntent(), PAYER,
        source=FixtureSource(TX_2_5, present=False),
    )
    assert isinstance(result, Pending), result


@pytest.mark.asyncio
async def test_a_transaction_without_a_block_number_is_pending():
    source = FixtureSource(TX_2_5)
    source.info = {k: v for k, v in source.info.items() if k != "blockNumber"}
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Pending), result


# ═══════════════════════════════════════════════════════════════
#  Every rejection reason is reachable
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_wrong_network_is_rejected():
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(chain="tron"), PAYER,
        source=FixtureSource(TX_2_5),
    )
    assert isinstance(result, Rejected) and result.reason == "wrong_network"


@pytest.mark.asyncio
async def test_a_transfer_to_someone_else_is_rejected():
    # No mutation needed: this is a real transfer OUT of the merchant address.
    result = await verify_transfer(
        NILE, TX_OUTBOUND, FakeIntent(amount=1.5), PAYER,
        source=FixtureSource(TX_OUTBOUND),
    )
    assert isinstance(result, Rejected) and result.reason == "wrong_recipient"


@pytest.mark.asyncio
async def test_a_trx_transfer_is_rejected_as_having_no_transfer_log():
    # A plain TRX send: it SUCCEEDED, it simply is not a TRC-20 transfer. Its
    # receipt carries only net_usage and has no `result` field at all, so the
    # success check must not read the absence as failure.
    source = FixtureSource(TX_TRX_ONLY)
    assert "result" not in source.info["receipt"], "fixture drifted"
    result = await verify_transfer(
        NILE, TX_TRX_ONLY, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Rejected) and result.reason == "no_transfer_log"


@pytest.mark.asyncio
async def test_a_transfer_of_another_token_is_rejected():
    source = FixtureSource(TX_2_5).mutate_event(
        0, contract_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    )
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Rejected) and result.reason == "wrong_contract"


@pytest.mark.asyncio
async def test_a_short_payment_is_rejected_on_amount():
    # The invoice wants 2.5 and the chain carries 2.5; ask for 3.0 instead.
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(amount=3.0), PAYER,
        source=FixtureSource(TX_2_5),
    )
    assert isinstance(result, Rejected) and result.reason == "wrong_amount"
    assert "2500000" in result.detail


@pytest.mark.asyncio
async def test_a_different_sender_is_rejected():
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), STRANGER, source=FixtureSource(TX_2_5)
    )
    assert isinstance(result, Rejected) and result.reason == "sender_mismatch"


@pytest.mark.asyncio
async def test_a_payer_who_is_not_the_expected_sender_is_rejected():
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(expected_sender=STRANGER), PAYER,
        source=FixtureSource(TX_2_5),
    )
    assert isinstance(result, Rejected) and result.reason == "sender_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt_result,reason",
    [("REVERT", "reverted"), ("OUT_OF_ENERGY", "out_of_energy"),
     ("OUT_OF_TIME", "failed_other")],
)
async def test_a_failed_receipt_is_rejected_with_its_reason(receipt_result, reason):
    # Mutated rather than recorded: producing a genuinely failed transfer means
    # signing and spending from the faucet account, and nothing in this
    # repository holds a private key. See the fixtures README.
    source = FixtureSource(TX_2_5).mutate_info(receipt__result=receipt_result)
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Rejected) and result.reason == reason


@pytest.mark.asyncio
async def test_a_failed_contract_ret_is_rejected_even_when_the_receipt_looks_fine():
    source = FixtureSource(TX_2_5)
    source.tx = copy.deepcopy(source.tx)
    source.tx["ret"] = [{"contractRet": "REVERT"}]
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Rejected) and result.reason == "reverted"


@pytest.mark.asyncio
async def test_an_ambiguous_enrichment_is_rejected_not_guessed():
    # Two indistinguishable Transfer events: the index is a coin flip, and
    # picking either would give a real payment the other one's log index.
    source = FixtureSource(TX_2_5)
    duplicate = copy.deepcopy(source.event_list[0])
    duplicate["event_index"] = 7
    source.event_list = source.event_list + [duplicate]
    result = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=source
    )
    assert isinstance(result, Rejected) and result.reason == "unenrichable"


def test_every_rejection_reason_is_reachable_and_closed():
    """Every reason `verify_transfer` can produce is exercised above.

    `not_found` is deliberately not in that set: it is the give-up verdict the
    hint pass writes for an intent nobody can pay any more, and no amount of
    reading the chain produces it. It shares the closed set because it shares
    the column, and a column with two vocabularies is one nobody can query. It
    is exercised in `test_tron_hints.py`.
    """
    exercised = {
        "wrong_network", "reverted", "out_of_energy", "failed_other",
        "no_transfer_log", "wrong_contract", "wrong_recipient",
        "wrong_amount", "sender_mismatch", "unenrichable",
    }
    assert exercised == tv.REJECTION_REASONS - {"not_found"}
    # Still a legal verdict, just not one this module reaches.
    assert Rejected("not_found").reason == "not_found"
    with pytest.raises(ValueError):
        Rejected("something_new")


# ═══════════════════════════════════════════════════════════════
#  Verified wires into the ONE settlement writer
# ═══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture
async def _db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.indexer_models  # noqa: F401
    import app.models.merchant_models  # noqa: F401
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import (
        MerchantWebhook, PaymentIntent, WebhookDelivery,
    )
    from app.models.settlement_models import PaymentSettlement

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(PaymentSettlement.__table__.delete())
        await conn.execute(PaymentIntent.__table__.delete())
        await conn.execute(WebhookDelivery.__table__.delete())
        await conn.execute(MerchantWebhook.__table__.delete())
    yield


@pytest.fixture
def webhooks(monkeypatch):
    """Capture every dispatch as (event, intent_id). Proves fire-once."""
    calls = []

    async def _fake(db, *, merchant_id, event, intent, extra_payload=None):
        calls.append((event, intent.intent_id))
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake)
    return calls


async def _pending_intent():
    """A pending Nile intent for the 2.5 USDT transfer in the fixture."""
    from datetime import datetime, timedelta, timezone
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    paid_at = datetime.fromtimestamp(1788132336, tz=timezone.utc)
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id="pi_verifier_wiring",
            merchant_id=MERCHANT,
            environment="test",          # Nile is the test environment
            amount=2.5,
            currency="USDT",
            chain="tron_nile",
            recipient=MERCHANT,
            status=IntentStatus.pending,
            created_at=paid_at - timedelta(minutes=5),
            expires_at=paid_at + timedelta(hours=1),
        )
        db.add(intent)
        await db.commit()
    return "pi_verifier_wiring"


@pytest.mark.asyncio
async def test_verified_writes_through_the_poller_s_own_writer(_db, webhooks):
    """One settlement row and one webhook, whichever path saw it first.

    The verifier hands `_record_settlement` exactly what an address scan would
    have handed it, so the second arrival is a duplicate rather than a second
    booking. This is what `settlement_input` exists to guarantee.
    """
    from sqlalchemy import func, select
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent
    from app.models.settlement_models import PaymentSettlement
    from app.services import tron_matcher

    intent_id = await _pending_intent()

    verified = await verify_transfer(
        NILE, TX_2_5, FakeIntent(), PAYER, source=FixtureSource(TX_2_5)
    )
    assert isinstance(verified, Verified)

    transfer, event = verified.settlement_input
    assert await tp._record_settlement(transfer, event, NILE) == "new"

    # Now the poller reaches the same transaction from its own address scan.
    discovery = json.loads(
        (FIXTURES / f"discovery_trc20_{MERCHANT}.json").read_text()
    )["data"]
    scanned = next(t for t in discovery if t["transaction_id"] == TX_2_5)
    poller_event = tp._pair_transfer_to_event(scanned, _load(TX_2_5, "events")["data"])
    assert await tp._record_settlement(scanned, poller_event, NILE) == "duplicate"

    async with async_session() as db:
        rows = (await db.execute(
            select(func.count()).select_from(PaymentSettlement)
        )).scalar_one()
    assert rows == 1, "one payment, one row, whichever path recorded it"

    await tron_matcher.match_pending_tron_settlements(NILE)

    async with async_session() as db:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == intent_id)
        )).scalar_one()
    assert intent.status == IntentStatus.paid
    assert intent.matched_tx_hash == TX_2_5
    assert [e for e, _ in webhooks] == ["payment.completed"], webhooks


# ═══════════════════════════════════════════════════════════════
#  The index has exactly one source
# ═══════════════════════════════════════════════════════════════

def test_the_verifier_never_derives_an_index_of_its_own():
    code = code_without_prose(tv)
    assert "_pair_transfer_to_event(" in code, (
        "the index must come from the poller's enrichment, not from here"
    )
    # It never even names the index: it passes the enrichment's event through
    # untouched. A receipt `log[]` position is a different index space, and
    # reading one here would book a payment twice.
    assert "event_index" not in code
    assert "log_index" not in code
    assert '"log"' not in code and "'log'" not in code
