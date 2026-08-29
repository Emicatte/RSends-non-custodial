"""TRON watch-only poller — it SEES and RECORDS. It does not match.

Phase 1, slice 2. The poller asks TronGrid which USDT TRC-20 transfers landed on
the recipient addresses of pending TRON intents, and writes one
`PaymentSettlement` row per transfer. Nothing is matched to an intent, no intent
changes status, no webhook fires — slice 3 does that.

Contract pinned here:

  - DISCOVERY is `GET /v1/accounts/{addr}/transactions/trc20`, filtered by
    `contract_address` + `only_to=true` + `only_confirmed=true`, paged by
    `fingerprint`, from `min_timestamp` = the cursor. `only_confirmed=true` IS
    the finality rule; no confirmation depth is computed anywhere.
  - That endpoint returns SEVEN keys per transfer — `transaction_id`,
    `token_info`, `block_timestamp`, `from`, `to`, `type`, `value` — and
    therefore carries NEITHER a per-transfer index NOR a block number, both of
    which are NOT NULL on `payment_settlements`.
  - ENRICHMENT is `GET /v1/transactions/{txid}/events`, ONCE PER TRANSACTION,
    which supplies the real `event_index` and `block_number`.
  - A positional index derived from response ordering is FORBIDDEN. See
    `test_two_merchants_paid_by_one_transaction_both_land` for why: it silently
    drops a payment.
  - FAIL CLOSED. Enrichment that errors, matches nothing, or matches
    ambiguously writes NO row, and the cursor does NOT advance past that
    transaction. A payment that is not recorded must be re-observed, forever, in
    preference to being lost.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_poller.py -v
"""

import inspect
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.services import tron_poller as tp
from tests._source_helpers import code_without_prose
from app.services.tron_poller import TRON_CHAIN_ID, TronPoller

# ═══════════════════════════════════════════════════════════════
#  Real mainnet data — tx 0e35a6ad2639…, observed 2026-08-28
# ═══════════════════════════════════════════════════════════════
#
# ONE transaction, TWO USDT transfers, TWO DIFFERENT recipients. Each recipient
# surfaces it under its own `only_to` poll. This is the shape that makes a
# positional index lose money, and it is not exotic: 3 of 197 distinct
# transactions in a single 200-event sample carried >=2 USDT transfers.
#
# Note the real event indices are 1 and 0 — NOT 0 and 1, and NOT in response
# order. `event_index` counts every VM event in the transaction, including the
# `GasFreeTransfer` this tx also emitted at index 2 from another contract.

USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

TX = "0e35a6ad2639e86508d6cafd8a3b0898b3b0d189bf3843d01a0383aa06e7d6e0"
TX_BLOCK = 85758417
TX_TS = 1787946738000

PAYER = "TVJF7zCn8pffXP7rPd2RPsWJxQ4YaUTmTB"
PAYER_HEX = "0xd4040ff90042a66f485bf4d0bd073b2613f4bbfb"

# Merchant A — real event_index 1
MERCH_A = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
MERCH_A_HEX = "0xd057eb518fc1b2316617aaa7bb73c7e1876b7934"
VALUE_A = "2997721763"
EVENT_IDX_A = 1

# Merchant B — real event_index 0
MERCH_B = "TLntW9Z59LYY5KEi9cmwk3PKjQga828ird"
MERCH_B_HEX = "0x76b5c8429b78a38643e5ff9a94b4ca10c1efd867"
VALUE_B = "1500000"
EVENT_IDX_B = 0

NODE = "https://api.trongrid.io"


# ═══════════════════════════════════════════════════════════════
#  Response builders — shaped exactly like TronGrid's
# ═══════════════════════════════════════════════════════════════

def _transfer(*, to, value, txid=TX, ts=TX_TS, frm=PAYER, contract=USDT):
    """One element of the trc20 `data` array. Seven keys, no more."""
    return {
        "transaction_id": txid,
        "token_info": {
            "symbol": "USDT", "address": contract,
            "decimals": 6, "name": "Tether USD",
        },
        "block_timestamp": ts,
        "from": frm,
        "to": to,
        "type": "Transfer",
        "value": value,
    }


def _transfer_page(transfers, *, fingerprint=None):
    meta = {"at": 1787946711339, "page_size": len(transfers)}
    if fingerprint:
        meta["fingerprint"] = fingerprint
        meta["links"] = {"next": f"{NODE}/whatever?fingerprint={fingerprint}"}
    return {"data": transfers, "success": True, "meta": meta}


def _event(*, to_hex, value, index, txid=TX, block=TX_BLOCK, ts=TX_TS,
           frm_hex=PAYER_HEX, contract=USDT, name="Transfer"):
    """One element of the events `data` array, hex addresses and all."""
    return {
        "block_number": block,
        "block_timestamp": ts,
        "caller_contract_address": contract,
        "contract_address": contract,
        "event_index": index,
        "event_name": name,
        "result": {
            "0": frm_hex, "1": to_hex, "2": value,
            "from": frm_hex, "to": to_hex, "value": value,
        },
        "result_type": {"from": "address", "to": "address", "value": "uint256"},
        "event": "Transfer(address indexed from, address indexed to, uint256 value)",
        "transaction_id": txid,
    }


def _events_page(events):
    return {"data": events, "success": True, "meta": {"at": 1787946711339}}


# The real transaction's full event list, in the order TronGrid returned it:
# descending index, and with a foreign-contract event interleaved.
REAL_TX_EVENTS = [
    _event(to_hex="0x0", value="0", index=2, contract="TFFAMQLZybALaLb4uxHA9RBE7pxhUAjF3U",
           name="GasFreeTransfer"),
    _event(to_hex=MERCH_A_HEX, value=VALUE_A, index=EVENT_IDX_A),
    _event(to_hex=MERCH_B_HEX, value=VALUE_B, index=EVENT_IDX_B),
]


# ═══════════════════════════════════════════════════════════════
#  HTTP boundary double — the suite never touches the network
# ═══════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, payload=None, *, status_code=200, json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _stub_http(monkeypatch, handler):
    """Route the poller's httpx traffic to `handler(url, params) -> _Resp`.

    The handler may raise to model a transport fault. Returns the recorded
    `(url, params)` list so a test can assert WHICH endpoints were hit and HOW
    MANY times — the enrichment-call-count property depends on it.
    """
    calls: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, *a, **kw):
            self.kwargs = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, **kw):
            calls.append((url, dict(params or {})))
            out = handler(url, dict(params or {}))
            if isinstance(out, BaseException):
                raise out
            return out

    monkeypatch.setattr(tp.httpx, "AsyncClient", _Client)
    return calls


def _router(*, transfers_by_addr=None, events_by_tx=None, pages_by_addr=None):
    """Build a handler serving trc20 discovery and per-tx event enrichment.

    `pages_by_addr` maps an address to a LIST of pages (for fingerprint tests);
    `transfers_by_addr` is the single-page shorthand.
    """
    transfers_by_addr = transfers_by_addr or {}
    events_by_tx = events_by_tx or {}
    pages_by_addr = pages_by_addr or {}

    def handler(url, params):
        if "/transactions/trc20" in url:
            addr = url.split("/v1/accounts/")[1].split("/")[0]
            if addr in pages_by_addr:
                pages = pages_by_addr[addr]
                fp = params.get("fingerprint")
                idx = 0 if not fp else next(
                    i + 1 for i, p in enumerate(pages)
                    if p["meta"].get("fingerprint") == fp
                )
                return _Resp(pages[idx])
            return _Resp(_transfer_page(transfers_by_addr.get(addr, [])))
        if "/events" in url:
            txid = url.split("/v1/transactions/")[1].split("/")[0]
            out = events_by_tx.get(txid, [])
            if isinstance(out, BaseException):
                return out
            return _Resp(_events_page(out))
        raise AssertionError(f"unexpected URL {url!r}")

    return handler


# ═══════════════════════════════════════════════════════════════
#  DB fixture — create_all + FK-ordered row wipe, never drop_all
# ═══════════════════════════════════════════════════════════════

@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    from app.db.session import engine
    from app.models.db_models import Base
    import app.models.indexer_models  # noqa: F401 — register indexer_cursors
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


# ── helpers ──────────────────────────────────────────────────

_AMOUNT_SEQ = iter(range(1, 10_000))


async def _make_tron_intent(*, recipient, amount=None, chain="TRON",
                            merchant_id=None):
    """A pending watch-only TRON intent, as slice 1 creates them.

    `chain` is stored VERBATIM — slice 1 pins `row.chain == "TRON"`, uppercase.
    Each intent gets its own amount: 0019's `uq_intent_pending_amount` is unique
    over (merchant_id, environment, chain, currency, amount) while pending.
    """
    import secrets
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id=merchant_id or f"m_{secrets.token_hex(4)}",
            environment="live",
            amount=float(amount if amount is not None else next(_AMOUNT_SEQ)),
            currency="USDT",
            chain=chain,
            recipient=recipient,
            onchain_invoice_id=None,
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
        await db.commit()
    return iid


async def _settlements():
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement

    async with async_session() as db:
        rows = (await db.execute(
            select(PaymentSettlement).order_by(PaymentSettlement.id)
        )).scalars().all()
        # detach-safe snapshot
        return [{
            "tx_hash": r.tx_hash, "log_index": r.log_index,
            "block_number": r.block_number, "merchant": r.merchant,
            "payer": r.payer, "token": r.token, "amount": r.amount,
            "chain_id": r.chain_id, "status": r.status,
            "intent_id": r.intent_id, "invoice_id": r.invoice_id,
        } for r in rows]


async def _settlement_count():
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement

    async with async_session() as db:
        return (await db.execute(
            select(func.count()).select_from(PaymentSettlement)
        )).scalar_one()


async def _intents_snapshot():
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent

    async with async_session() as db:
        rows = (await db.execute(select(PaymentIntent))).scalars().all()
        return {r.intent_id: (r.status, r.matched_tx_hash, r.matched_at,
                              r.tx_hash, r.completed_at) for r in rows}


def _poller(nodes=(NODE,)):
    return TronPoller(node_urls=list(nodes))


# ═══════════════════════════════════════════════════════════════
#  Chain identity — before ANY other call, before the cursor
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_identity_failure_refuses_to_start_and_never_reads_the_cursor(
    monkeypatch, caplog
):
    """An unproven TRON node must stop the boot, not disable TRON quietly."""
    from app.models.indexer_models import IndexerCursor
    from app.services.tron_chain_identity import TronChainIdentityError

    async def _boom(node_url, **kw):
        raise TronChainIdentityError(f"unproven: {node_url}")

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _boom)
    monkeypatch.setattr(tp, "_configured_nodes", lambda: [NODE])
    # Any HTTP at all would mean the guard did not run first.
    _stub_http(monkeypatch, lambda url, params: (_ for _ in ()).throw(
        AssertionError(f"guard did not run first; hit {url}")))

    with caplog.at_level(logging.ERROR, logger=tp.logger.name):
        with pytest.raises(SystemExit):
            await tp.start_tron_poller_if_needed()

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1, [r.getMessage() for r in caplog.records]
    assert "identity" in criticals[0].getMessage().lower()

    # The negative side effect: no cursor row was created or read.
    from app.db.session import async_session
    async with async_session() as db:
        assert (await db.execute(select(IndexerCursor))).scalars().first() is None


@pytest.mark.asyncio
async def test_every_configured_node_is_proven_not_just_the_first(monkeypatch):
    proven = []

    async def _ok(node_url, **kw):
        proven.append(node_url)

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _ok)
    monkeypatch.setattr(tp, "_configured_nodes", lambda: [NODE, "https://failover"])
    monkeypatch.setattr(TronPoller, "_loop", lambda self: _noop())

    poller = await tp.start_tron_poller_if_needed()
    try:
        assert proven == [NODE, "https://failover"]
    finally:
        await tp.stop_tron_poller()
    assert poller is not None


async def _noop():
    return None


@pytest.mark.asyncio
async def test_no_tron_node_configured_is_silent_not_an_error(monkeypatch):
    monkeypatch.setattr(tp, "_configured_nodes", lambda: [])

    async def _never(node_url, **kw):
        raise AssertionError("must not probe when nothing is configured")

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _never)
    assert await tp.start_tron_poller_if_needed() is None


# ═══════════════════════════════════════════════════════════════
#  Seeing and recording
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_transfer_to_a_pending_recipient_writes_one_settlement(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)]},
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    w = _poller()
    await tp._set_tron_cursor(TX_TS - 1)

    await w._tick()

    rows = await _settlements()
    assert len(rows) == 1, rows
    r = rows[0]
    assert r["tx_hash"] == TX
    assert r["chain_id"] == TRON_CHAIN_ID
    assert r["log_index"] == EVENT_IDX_A       # the REAL event index, not 0
    assert r["block_number"] == TX_BLOCK       # enrichment supplied it
    assert r["amount"] == Decimal(VALUE_A)
    assert r["invoice_id"] is None
    assert r["intent_id"] is None              # slice 3 fills this
    assert r["status"].value == "pending"


@pytest.mark.asyncio
async def test_base58_addresses_round_trip_byte_identical(monkeypatch):
    """Case intact, no folding. Lowercasing a base58check address destroys it."""
    await _make_tron_intent(recipient=MERCH_A)
    _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)]},
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    await tp._set_tron_cursor(TX_TS - 1)
    await _poller()._tick()

    r = (await _settlements())[0]
    assert r["merchant"] == MERCH_A
    assert r["payer"] == PAYER
    assert r["token"] == USDT
    for f in ("merchant", "payer", "token"):
        assert r[f] != r[f].lower(), f"{f} was case-folded: {r[f]}"


@pytest.mark.asyncio
async def test_an_address_with_no_transfers_is_a_no_op(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    calls = _stub_http(monkeypatch, _router(transfers_by_addr={MERCH_A: []}))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    assert await _settlement_count() == 0
    assert not [u for u, _ in calls if "/events" in u]   # nothing to enrich
    assert await tp._get_tron_cursor() == TX_TS - 1      # nothing seen, no move


@pytest.mark.asyncio
async def test_rerunning_the_same_tick_writes_nothing(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)]},
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    w = _poller()
    await tp._set_tron_cursor(TX_TS - 1)

    await w._tick()
    assert await _settlement_count() == 1
    await tp._set_tron_cursor(TX_TS - 1)   # replay the identical tick
    await w._tick()
    assert await _settlement_count() == 1, "idempotency broken"


# ═══════════════════════════════════════════════════════════════
#  The cross-address collision — why a positional index loses money
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_two_merchants_paid_by_one_transaction_both_land(monkeypatch):
    """The exact scenario from mainnet tx 0e35a6ad2639….

    One transaction pays two merchants. Each surfaces it under its own address
    poll. A positional index would assign log_index 0 to both, and
    `uq_settlement_onchain_log` (chain_id, tx_hash, log_index) would swallow the
    second as a duplicate — a LOST payment. The real event indices are 1 and 0.
    """
    await _make_tron_intent(recipient=MERCH_A)
    await _make_tron_intent(recipient=MERCH_B)
    _stub_http(monkeypatch, _router(
        transfers_by_addr={
            MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)],
            MERCH_B: [_transfer(to=MERCH_B, value=VALUE_B)],
        },
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    rows = await _settlements()
    assert len(rows) == 2, f"a payment was dropped: {rows}"
    by_merchant = {r["merchant"]: r for r in rows}
    assert by_merchant[MERCH_A]["log_index"] == EVENT_IDX_A   # 1
    assert by_merchant[MERCH_B]["log_index"] == EVENT_IDX_B   # 0
    assert by_merchant[MERCH_A]["amount"] == Decimal(VALUE_A)
    assert by_merchant[MERCH_B]["amount"] == Decimal(VALUE_B)
    assert {r["log_index"] for r in rows} == {0, 1}


@pytest.mark.asyncio
async def test_event_index_is_stored_as_returned_never_renumbered(monkeypatch):
    """Non-contiguous and out-of-order within the USDT subset — kept verbatim."""
    await _make_tron_intent(recipient=MERCH_A)
    await _make_tron_intent(recipient=MERCH_B)
    # Real-world shape: indices 7 and 3, returned high-then-low, with a foreign
    # event at 5 in between.
    events = [
        _event(to_hex=MERCH_A_HEX, value=VALUE_A, index=7),
        _event(to_hex="0x0", value="0", index=5, name="Swap",
               contract="TFFAMQLZybALaLb4uxHA9RBE7pxhUAjF3U"),
        _event(to_hex=MERCH_B_HEX, value=VALUE_B, index=3),
    ]
    _stub_http(monkeypatch, _router(
        transfers_by_addr={
            MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)],
            MERCH_B: [_transfer(to=MERCH_B, value=VALUE_B)],
        },
        events_by_tx={TX: events},
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    by_merchant = {r["merchant"]: r for r in await _settlements()}
    assert by_merchant[MERCH_A]["log_index"] == 7
    assert by_merchant[MERCH_B]["log_index"] == 3


@pytest.mark.asyncio
async def test_enrichment_is_one_call_per_transaction_not_per_transfer(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    await _make_tron_intent(recipient=MERCH_B)
    calls = _stub_http(monkeypatch, _router(
        transfers_by_addr={
            MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)],
            MERCH_B: [_transfer(to=MERCH_B, value=VALUE_B)],
        },
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    event_calls = [u for u, _ in calls if "/events" in u]
    assert len(event_calls) == 1, event_calls   # two transfers, ONE transaction
    assert TX in event_calls[0]


# ═══════════════════════════════════════════════════════════════
#  Fail closed — no row, and the cursor stays put
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mode", ["transport", "http_500", "no_match", "ambiguous"])
@pytest.mark.asyncio
async def test_unenrichable_transfer_writes_nothing_and_pins_the_cursor(
    monkeypatch, caplog, mode
):
    """Four ways enrichment can fail; one outcome. No row, no cursor advance."""
    import httpx as _httpx

    await _make_tron_intent(recipient=MERCH_A)

    if mode == "transport":
        events = _httpx.ConnectError("refused")
    elif mode == "http_500":
        events = None            # handled below
    elif mode == "no_match":
        events = [_event(to_hex="0x" + "1" * 40, value="999", index=4)]
    else:  # ambiguous — two identical candidate events in one transaction
        events = [
            _event(to_hex=MERCH_A_HEX, value=VALUE_A, index=1),
            _event(to_hex=MERCH_A_HEX, value=VALUE_A, index=6),
        ]

    base = _router(
        transfers_by_addr={MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)]},
        events_by_tx={TX: events} if events is not None else {},
    )

    def handler(url, params):
        if mode == "http_500" and "/events" in url:
            return _Resp({"error": "boom"}, status_code=500)
        return base(url, params)

    _stub_http(monkeypatch, handler)
    await tp._set_tron_cursor(TX_TS - 1)

    with caplog.at_level(logging.WARNING, logger=tp.logger.name):
        await _poller()._tick()

    assert await _settlement_count() == 0, "fail-closed violated: a row was written"
    # The cursor pins TO the blocked transaction, never past it. `min_timestamp`
    # is INCLUSIVE (verified against mainnet: querying with the exact
    # block_timestamp of a known transfer returns that transfer), so the next
    # tick re-observes this transaction instead of skipping it.
    assert await tp._get_tron_cursor() == TX_TS, (
        "cursor advanced past a transaction that could not be enriched — "
        "the payment is now unobservable"
    )
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert loud, "an unenrichable transfer must be logged loudly"
    if mode == "ambiguous":
        assert any("ambiguous" in r.getMessage().lower() for r in loud), \
            [r.getMessage() for r in loud]


@pytest.mark.asyncio
async def test_one_bad_transaction_does_not_advance_past_a_later_good_one(
    monkeypatch
):
    """The cursor pins to the EARLIEST unenrichable transaction, not the max."""
    await _make_tron_intent(recipient=MERCH_A)
    bad_tx, good_tx = "b" * 64, "c" * 64
    _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [
            _transfer(to=MERCH_A, value=VALUE_A, txid=bad_tx, ts=TX_TS),
            _transfer(to=MERCH_A, value=VALUE_B, txid=good_tx, ts=TX_TS + 5000),
        ]},
        events_by_tx={
            bad_tx: [],                                       # nothing matches
            good_tx: [_event(to_hex=MERCH_A_HEX, value=VALUE_B, index=0,
                             txid=good_tx, ts=TX_TS + 5000)],
        },
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    assert await tp._get_tron_cursor() == TX_TS, (
        "cursor must pin to the earliest unenrichable transaction"
    )


def test_there_is_no_positional_fallback_anywhere_in_the_source():
    """No degraded mode. A positional index must be unreachable, not just unused."""
    code = code_without_prose(tp).lower()
    for forbidden in ("enumerate(transfers", "positional", "fallback_index",
                      "log_index=idx", "log_index=i,", "log_index=position"):
        assert forbidden not in code, f"a positional index crept in: {forbidden!r}"
    # The only source of log_index is the enrichment event.
    assert "event_index" in code


# ═══════════════════════════════════════════════════════════════
#  Cursor + pagination
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cursor_advances_and_the_next_tick_asks_from_the_last_seen(
    monkeypatch
):
    await _make_tron_intent(recipient=MERCH_A)
    calls = _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)]},
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    w = _poller()
    await tp._set_tron_cursor(TX_TS - 1)

    await w._tick()
    assert await tp._get_tron_cursor() == TX_TS

    await w._tick()
    trc20 = [p for u, p in calls if "/transactions/trc20" in u]
    assert trc20[-1]["min_timestamp"] == TX_TS, trc20[-1]


@pytest.mark.asyncio
async def test_the_discovery_call_carries_the_finality_and_filter_params(
    monkeypatch
):
    await _make_tron_intent(recipient=MERCH_A)
    calls = _stub_http(monkeypatch, _router(transfers_by_addr={MERCH_A: []}))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    _, params = next((u, p) for u, p in calls if "/transactions/trc20" in u)
    assert params["contract_address"] == USDT
    assert params["only_to"] == "true"
    assert params["only_confirmed"] == "true"     # THIS is the finality rule
    assert params["order_by"] == "block_timestamp,asc"
    assert int(params["limit"]) <= 200


@pytest.mark.asyncio
async def test_fingerprint_pagination_is_followed(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    t1 = _transfer(to=MERCH_A, value=VALUE_A, txid="d" * 64)
    t2 = _transfer(to=MERCH_A, value=VALUE_B, txid="e" * 64, ts=TX_TS + 1000)
    calls = _stub_http(monkeypatch, _router(
        pages_by_addr={MERCH_A: [
            _transfer_page([t1], fingerprint="FP1"),
            _transfer_page([t2]),
        ]},
        events_by_tx={
            "d" * 64: [_event(to_hex=MERCH_A_HEX, value=VALUE_A, index=0, txid="d" * 64)],
            "e" * 64: [_event(to_hex=MERCH_A_HEX, value=VALUE_B, index=0,
                              txid="e" * 64, ts=TX_TS + 1000)],
        },
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    trc20 = [p for u, p in calls if "/transactions/trc20" in u]
    assert len(trc20) == 2, trc20
    assert "fingerprint" not in trc20[0]
    assert trc20[1]["fingerprint"] == "FP1"
    assert await _settlement_count() == 2


# ═══════════════════════════════════════════════════════════════
#  This slice does not touch intents
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_no_intent_is_mutated_by_anything_in_this_slice(monkeypatch):
    await _make_tron_intent(recipient=MERCH_A)
    await _make_tron_intent(recipient=MERCH_B)
    before = await _intents_snapshot()

    _stub_http(monkeypatch, _router(
        transfers_by_addr={
            MERCH_A: [_transfer(to=MERCH_A, value=VALUE_A)],
            MERCH_B: [_transfer(to=MERCH_B, value=VALUE_B)],
        },
        events_by_tx={TX: REAL_TX_EVENTS},
    ))
    await tp._set_tron_cursor(TX_TS - 1)

    await _poller()._tick()

    assert await _settlement_count() == 2      # it DID record
    assert await _intents_snapshot() == before  # and changed no intent
    assert all(r["intent_id"] is None for r in await _settlements())


@pytest.mark.asyncio
async def test_only_pending_tron_intents_contribute_addresses(monkeypatch):
    """Non-TRON chains, and non-pending TRON intents, are not polled."""
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    await _make_tron_intent(recipient=MERCH_A)                      # polled
    await _make_tron_intent(recipient=MERCH_B, chain="base")        # not TRON
    cancelled = await _make_tron_intent(recipient="T" + "1" * 33)
    async with async_session() as db:
        row = (await db.execute(select(PaymentIntent).where(
            PaymentIntent.intent_id == cancelled))).scalar_one()
        row.status = IntentStatus.cancelled
        await db.commit()

    calls = _stub_http(monkeypatch, _router(transfers_by_addr={MERCH_A: []}))
    await tp._set_tron_cursor(TX_TS - 1)
    await _poller()._tick()

    polled = {u.split("/v1/accounts/")[1].split("/")[0]
              for u, _ in calls if "/transactions/trc20" in u}
    assert polled == {MERCH_A}, polled


@pytest.mark.asyncio
async def test_chain_is_matched_case_insensitively(monkeypatch):
    """Slice 1 stores `chain` verbatim — 'TRON' uppercase is the real value."""
    await _make_tron_intent(recipient=MERCH_A, chain="tron")
    await _make_tron_intent(recipient=MERCH_B, chain="TRON")
    calls = _stub_http(monkeypatch, _router(
        transfers_by_addr={MERCH_A: [], MERCH_B: []}))
    await tp._set_tron_cursor(TX_TS - 1)
    await _poller()._tick()

    polled = {u.split("/v1/accounts/")[1].split("/")[0]
              for u, _ in calls if "/transactions/trc20" in u}
    assert polled == {MERCH_A, MERCH_B}, polled


# ═══════════════════════════════════════════════════════════════
#  The hard guardrail — TRON must reach no EVM machinery
# ═══════════════════════════════════════════════════════════════

def test_tron_chain_id_is_in_no_evm_chain_table():
    """728126428 in any of these starts a PaymentWatcher and SystemExits the boot."""
    from app.services import chain_access, router_registry, rpc_manager

    assert TRON_CHAIN_ID == 728126428
    assert TRON_CHAIN_ID not in router_registry.CHAIN_IDS.values()
    assert TRON_CHAIN_ID not in chain_access.TESTNET_CHAIN_IDS
    assert TRON_CHAIN_ID not in chain_access.CHAIN_ID_BY_NAME.values()
    assert TRON_CHAIN_ID not in rpc_manager._DEFAULT_PROVIDERS

    from app.config import get_settings
    s = get_settings()
    for m in (s.rsends_router_addresses, s.rsends_router_v2_addresses,
              s.split_router_addresses):
        assert str(TRON_CHAIN_ID) not in {str(k) for k in m}


def test_the_poller_is_not_a_payment_watcher():
    """A sibling service, not a parameterization of the EVM indexer.

    String literals are deliberately still in scope here: an `eth_*` method
    name reaches the wire as a string, so stripping strings would hide exactly
    the violation this looks for.
    """
    code = code_without_prose(tp)
    for forbidden in ("PaymentWatcher", "eth_getLogs", "eth_chainId",
                      "eth_blockNumber", "get_rpc_manager", "_finalize_and_reconcile"):
        assert forbidden not in code, \
            f"the TRON poller reached into EVM machinery: {forbidden}"


# ═══════════════════════════════════════════════════════════════
#  Address conversion — ONE decoder, reused
# ═══════════════════════════════════════════════════════════════

def test_base58_to_hex_matches_real_mainnet_pairs():
    from app.security.input_validator import tron_address_to_evm_hex

    assert tron_address_to_evm_hex(MERCH_A) == MERCH_A_HEX
    assert tron_address_to_evm_hex(MERCH_B) == MERCH_B_HEX
    assert tron_address_to_evm_hex(PAYER) == PAYER_HEX
    assert tron_address_to_evm_hex(USDT) == "0xa614f803b6fd780986a42c78ec9c7f77e6ded13c"


def test_base58_to_hex_rejects_what_is_not_a_tron_address():
    from app.security.input_validator import tron_address_to_evm_hex

    for bad in (None, "", "0x" + "a" * 40, MERCH_A.lower(), MERCH_A[:-1], 42):
        assert tron_address_to_evm_hex(bad) is None, bad


def test_there_is_exactly_one_base58_decoder():
    """The conversion reuses `is_tron_address`'s decode; it does not duplicate it."""
    from app.security import input_validator as iv

    src = inspect.getsource(iv)
    # Both public functions must route through the single private decoder.
    assert src.count("def _tron_decode") == 1
    assert "_tron_decode(" in inspect.getsource(iv.is_tron_address)
    assert "_tron_decode(" in inspect.getsource(iv.tron_address_to_evm_hex)
    # And the poller must not carry a decoder of its own.
    poller_src = inspect.getsource(tp)
    assert "58" not in poller_src.replace("base58", ""), \
        "the poller looks like it grew its own base58 decoder"
