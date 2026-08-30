"""Two TRON networks, one poller — and no way for either to see the other's.

Slice 2 was written for the only TRON network there was, so the network was a
module constant: one chain id, one USDT contract, one `"tron"` chain filter, one
node-URL setting. Nile makes every one of those a per-network fact, and the
failure modes of getting it wrong are all silent:

  - a shared cursor row would make each network's tick rewind or skip the
    other's, and `last_block` holds a millisecond timestamp, so the two would
    interleave into nonsense rather than erroring;
  - a mainnet-scoped recipient query would have the Nile poller ask TronGrid's
    Nile node about mainnet merchants' addresses, find nothing, and report a
    clean tick forever;
  - a mainnet-scoped matcher would leave Nile settlements recorded but
    unmatched — money observed, intent never completed, nothing said;
  - the mainnet USDT contract on Nile does not exist, so watching it observes
    nothing, forever, with no error.

None of these raise. All of them are tested here.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_nile_poller.py -q
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.services import tron_matcher as tm
from app.services import tron_poller as tp
from app.services.tron_poller import TRON_CHAIN_ID, TRON_NILE_CHAIN_ID, TronPoller

MAINNET_USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
NILE_USDT = "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf"

MAINNET_NODE = "https://api.trongrid.io"
NILE_NODE = "https://nile.trongrid.io"

PAYER = "TVJF7zCn8pffXP7rPd2RPsWJxQ4YaUTmTB"
PAYER_HEX = "0xd4040ff90042a66f485bf4d0bd073b2613f4bbfb"
MERCH = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
MERCH_HEX = "0xd057eb518fc1b2316617aaa7bb73c7e1876b7934"


# ═══════════════════════════════════════════════════════════════
#  HTTP double
# ═══════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _stub_http(monkeypatch, handler):
    calls: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None, **kw):
            calls.append((url, dict(params or {})))
            out = handler(url, dict(params or {}))
            if isinstance(out, BaseException):
                raise out
            return out

    monkeypatch.setattr(tp.httpx, "AsyncClient", _Client)
    return calls


def _transfer(txid, ts, contract, value="1500000"):
    return {
        "transaction_id": txid,
        "token_info": {"address": contract, "decimals": 6, "symbol": "USDT"},
        "block_timestamp": ts,
        "from": PAYER,
        "to": MERCH,
        "type": "Transfer",
        "value": value,
    }


def _event(txid, contract, value="1500000", index=0, block=1):
    return {
        "transaction_id": txid,
        "event_name": "Transfer",
        "contract_address": contract,
        "event_index": index,
        "block_number": block,
        "result": {"from": PAYER_HEX, "to": MERCH_HEX, "value": value},
    }


def _routes(transfers, events):
    """`transfers` keyed by contract address, `events` keyed by txid."""

    def handler(url, params):
        if "/transactions/trc20" in url:
            contract = params.get("contract_address")
            return _Resp({"data": transfers.get(contract, []), "meta": {}})
        if "/events" in url:
            txid = url.split("/v1/transactions/")[1].split("/")[0]
            return _Resp({"data": events.get(txid, []), "meta": {}})
        raise AssertionError(f"unexpected URL {url!r}")

    return handler


# ═══════════════════════════════════════════════════════════════
#  DB
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


_AMOUNT_SEQ = iter(range(1, 10_000))


async def _make_intent(*, chain, recipient=MERCH, environment="live", amount=None):
    from app.db.session import async_session
    from app.models.merchant_models import IntentStatus, PaymentIntent

    iid = f"pi_{secrets.token_hex(8)}"
    async with async_session() as db:
        db.add(PaymentIntent(
            intent_id=iid,
            reference_id=secrets.token_hex(8),
            merchant_id=f"m_{secrets.token_hex(4)}",
            environment=environment,
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


async def _cursor_rows():
    from app.db.session import async_session
    from app.models.indexer_models import IndexerCursor

    async with async_session() as db:
        rows = (await db.execute(select(IndexerCursor))).scalars().all()
        return {int(r.chain_id): int(r.last_block) for r in rows}


async def _settlements():
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement

    async with async_session() as db:
        rows = (await db.execute(
            select(PaymentSettlement).order_by(PaymentSettlement.id)
        )).scalars().all()
        return [
            {"chain_id": int(r.chain_id), "token": r.token, "tx_hash": r.tx_hash}
            for r in rows
        ]


async def _noop():
    return None


# ═══════════════════════════════════════════════════════════════
#  The network descriptor
# ═══════════════════════════════════════════════════════════════

def test_the_two_networks_are_distinct_in_every_field_that_keys_data():
    """Every field here is a key something is stored or looked up by. Two
    networks sharing any of them is a silent cross-network read."""
    m, n = tp.TRON_MAINNET, tp.TRON_NILE

    assert (m.key, n.key) == ("mainnet", "nile")
    assert m.chain_name != n.chain_name
    assert m.chain_id != n.chain_id
    assert m.usdt_contract != n.usdt_contract
    assert m.settings_attr != n.settings_attr
    assert m.chain_id == TRON_CHAIN_ID and n.chain_id == TRON_NILE_CHAIN_ID
    # The matcher compares `func.lower(PaymentIntent.chain) == chain_name`, so a
    # non-lowercase name here would match nothing and say nothing.
    assert m.chain_name == m.chain_name.lower()
    assert n.chain_name == n.chain_name.lower()
    assert tp.TRON_NETWORKS == (m, n)


def test_each_networks_genesis_key_is_registered():
    """A network whose key is not in the genesis registry cannot be proven, and
    would fail at boot rather than at import — worth catching here."""
    from app.services.tron_chain_identity import TRON_GENESIS_BLOCK_IDS

    for net in tp.TRON_NETWORKS:
        assert net.key in TRON_GENESIS_BLOCK_IDS, net.key


def test_each_network_reads_its_own_settings_field():
    """Two distinct variables, never one variable with a network flag choosing
    between them: a single field would make pointing at the wrong network a
    one-character mistake with no signal."""
    from app.config import get_settings

    s = get_settings()
    for net in tp.TRON_NETWORKS:
        assert hasattr(s, net.settings_attr), net.settings_attr


# ═══════════════════════════════════════════════════════════════
#  Cursors
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_two_networks_keep_separate_cursor_rows():
    """`last_block` holds a MILLISECOND timestamp here, so a shared row would
    not collide loudly — the two networks would drag one cursor back and forth
    and each would silently re-scan or skip windows of the other's history."""
    await tp._set_tron_cursor(tp.TRON_MAINNET, 1_700_000_000_000)
    await tp._set_tron_cursor(tp.TRON_NILE, 1_800_000_000_000)

    assert await _cursor_rows() == {
        TRON_CHAIN_ID: 1_700_000_000_000,
        TRON_NILE_CHAIN_ID: 1_800_000_000_000,
    }
    assert await tp._get_tron_cursor(tp.TRON_MAINNET) == 1_700_000_000_000
    assert await tp._get_tron_cursor(tp.TRON_NILE) == 1_800_000_000_000


@pytest.mark.asyncio
async def test_one_networks_cursor_write_never_moves_the_others():
    await tp._set_tron_cursor(tp.TRON_MAINNET, 1_700_000_000_000)
    await tp._set_tron_cursor(tp.TRON_NILE, 1_800_000_000_000)

    await tp._set_tron_cursor(tp.TRON_NILE, 1_900_000_000_000)

    assert await tp._get_tron_cursor(tp.TRON_MAINNET) == 1_700_000_000_000
    assert await tp._get_tron_cursor(tp.TRON_NILE) == 1_900_000_000_000


@pytest.mark.asyncio
async def test_a_cold_start_on_one_network_does_not_anchor_the_other():
    """Cold start anchors at now() and scans nothing. If the two shared a row,
    starting Nile would anchor mainnet at now() too — silently skipping every
    mainnet payment made before that moment."""
    await tp._set_tron_cursor(tp.TRON_MAINNET, 1_700_000_000_000)

    assert await tp._get_tron_cursor(tp.TRON_NILE) is None
    assert await tp._get_tron_cursor(tp.TRON_MAINNET) == 1_700_000_000_000


# ═══════════════════════════════════════════════════════════════
#  What each network watches
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_each_network_watches_only_its_own_chains_intents():
    """The recipient set is the poller's entire notion of "who to ask about".
    Mainnet-scoping it would have the Nile poller query a Nile node about
    mainnet merchants — zero results, zero errors, a clean-looking tick."""
    await _make_intent(chain="TRON", recipient=MERCH)
    await _make_intent(chain="TRON_NILE", recipient=PAYER)

    assert await tp._pending_tron_recipients(tp.TRON_MAINNET) == [MERCH]
    assert await tp._pending_tron_recipients(tp.TRON_NILE) == [PAYER]


@pytest.mark.asyncio
async def test_the_chain_filter_folds_case_like_its_mainnet_sibling():
    """`chain` is stored VERBATIM as the caller sent it, so the comparison folds
    in the query — the same idiom mainnet uses."""
    await _make_intent(chain="tron_nile", recipient=MERCH)
    await _make_intent(chain="Tron_Nile", recipient=PAYER)

    assert sorted(await tp._pending_tron_recipients(tp.TRON_NILE)) == sorted(
        [MERCH, PAYER]
    )


@pytest.mark.asyncio
async def test_each_network_polls_its_own_usdt_contract(monkeypatch):
    """Mainnet's USDT does not exist on Nile. Watching it there observes
    nothing, forever, without a single error."""
    await _make_intent(chain="TRON_NILE", recipient=MERCH)
    await tp._set_tron_cursor(tp.TRON_NILE, 1)

    calls = _stub_http(monkeypatch, _routes({}, {}))
    await TronPoller(network=tp.TRON_NILE, node_urls=[NILE_NODE])._observe()

    discovery = [c for c in calls if "/transactions/trc20" in c[0]]
    assert discovery, "no discovery call was made"
    assert {c[1]["contract_address"] for c in discovery} == {NILE_USDT}
    assert all(c[0].startswith(NILE_NODE) for c in discovery)


# ═══════════════════════════════════════════════════════════════
#  What each network writes
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_nile_settlement_is_stamped_with_niles_chain_id(monkeypatch):
    """chain_id is two thirds of the settlement idempotency key
    (chain_id, tx_hash, log_index) AND the only thing separating the two
    networks' rows. 3448148188 is also past a 4-byte signed integer, so this is
    the write that would have failed on Postgres before 0020."""
    await _make_intent(chain="TRON_NILE", recipient=MERCH)
    await tp._set_tron_cursor(tp.TRON_NILE, 1)

    txid = "nile" + secrets.token_hex(30)
    _stub_http(monkeypatch, _routes(
        {NILE_USDT: [_transfer(txid, 1_800_000_000_000, NILE_USDT)]},
        {txid: [_event(txid, NILE_USDT)]},
    ))

    result = await TronPoller(network=tp.TRON_NILE, node_urls=[NILE_NODE])._observe()

    assert result["written"] == 1
    rows = await _settlements()
    assert [r["chain_id"] for r in rows] == [TRON_NILE_CHAIN_ID]
    assert rows[0]["token"] == NILE_USDT


@pytest.mark.asyncio
async def test_the_same_txid_on_both_networks_is_two_rows_not_a_duplicate(monkeypatch):
    """The idempotency key is (chain_id, tx_hash, log_index). If both networks
    stamped one chain id, an identical hash on the testnet would be swallowed as
    a duplicate of a real mainnet payment — or vice versa."""
    await _make_intent(chain="TRON", recipient=MERCH)
    await _make_intent(chain="TRON_NILE", recipient=MERCH)
    await tp._set_tron_cursor(tp.TRON_MAINNET, 1)
    await tp._set_tron_cursor(tp.TRON_NILE, 1)

    txid = "a" * 64
    _stub_http(monkeypatch, _routes(
        {
            MAINNET_USDT: [_transfer(txid, 1_700_000_000_000, MAINNET_USDT)],
            NILE_USDT: [_transfer(txid, 1_800_000_000_000, NILE_USDT)],
        },
        {txid: [_event(txid, MAINNET_USDT), _event(txid, NILE_USDT)]},
    ))

    await TronPoller(network=tp.TRON_MAINNET, node_urls=[MAINNET_NODE])._observe()
    await TronPoller(network=tp.TRON_NILE, node_urls=[NILE_NODE])._observe()

    rows = await _settlements()
    assert sorted(r["chain_id"] for r in rows) == sorted(
        [TRON_CHAIN_ID, TRON_NILE_CHAIN_ID]
    )


# ═══════════════════════════════════════════════════════════════
#  Boot: each node proven against ITS network
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_each_configured_node_is_proven_against_its_own_network(monkeypatch):
    """The guard takes the network as an argument, so the poller must hand it
    the network that node is configured FOR — not the one that happens to be
    first in the tuple."""
    asked: list[tuple[str, str]] = []

    async def _prove(node_url, network, **kw):
        asked.append((node_url, network))

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _prove)
    monkeypatch.setattr(tp, "_configured_nodes", lambda net: {
        "mainnet": [MAINNET_NODE], "nile": [NILE_NODE],
    }[net.key])
    monkeypatch.setattr(TronPoller, "_loop", lambda self: _noop())

    pollers = await tp.start_tron_poller_if_needed()
    try:
        assert asked == [(MAINNET_NODE, "mainnet"), (NILE_NODE, "nile")]
        assert len(pollers) == 2
        assert {p.network.key for p in pollers} == {"mainnet", "nile"}
    finally:
        await tp.stop_tron_poller()


@pytest.mark.asyncio
async def test_a_node_that_fails_its_networks_proof_stops_the_boot(monkeypatch):
    """Unchanged posture, now per network: an unproven node is fatal, and the
    cursor is never read. A Nile node quietly serving mainnet would record real
    payments against a testnet cursor and stamp them `test`."""
    from app.services.tron_chain_identity import TronChainIdentityError

    async def _prove(node_url, network, **kw):
        if network == "nile":
            raise TronChainIdentityError(f"not nile: {node_url}")

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _prove)
    monkeypatch.setattr(tp, "_configured_nodes", lambda net: {
        "mainnet": [MAINNET_NODE], "nile": [MAINNET_NODE],
    }[net.key])
    _stub_http(monkeypatch, lambda url, params: (_ for _ in ()).throw(
        AssertionError(f"guard did not run first; hit {url}")))

    with pytest.raises(SystemExit):
        await tp.start_tron_poller_if_needed()

    assert await _cursor_rows() == {}


@pytest.mark.asyncio
async def test_configuring_one_network_starts_only_that_one(monkeypatch):
    """An unconfigured network is silently absent, not an error — the same shape
    an empty router map gives the EVM indexer. It must not take the configured
    one down with it, nor start a poller with no nodes."""
    proven: list[str] = []

    async def _prove(node_url, network, **kw):
        proven.append(network)

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _prove)
    monkeypatch.setattr(tp, "_configured_nodes", lambda net: (
        [NILE_NODE] if net.key == "nile" else []
    ))
    monkeypatch.setattr(TronPoller, "_loop", lambda self: _noop())

    pollers = await tp.start_tron_poller_if_needed()
    try:
        assert proven == ["nile"]
        assert [p.network.key for p in pollers] == ["nile"]
    finally:
        await tp.stop_tron_poller()


@pytest.mark.asyncio
async def test_nothing_configured_is_silent_not_an_error(monkeypatch):
    async def _never(node_url, network, **kw):
        raise AssertionError("must not probe when nothing is configured")

    monkeypatch.setattr(tp, "assert_tron_chain_identity", _never)
    monkeypatch.setattr(tp, "_configured_nodes", lambda net: [])

    assert await tp.start_tron_poller_if_needed() == []


# ═══════════════════════════════════════════════════════════════
#  Matching: the environment stamp, and no cross-network match
# ═══════════════════════════════════════════════════════════════

def test_a_nile_settlement_is_stamped_test_and_mainnet_live():
    """The environment stamp is what scopes the intent search and the outbound
    webhook. Derived from the chain NAME, because neither TRON chain id is in
    the EVM testnet table and `is_testnet_chain` is fail-closed to mainnet —
    which is the right answer for mainnet and the wrong one for Nile."""
    assert tm._tron_environment(tp.TRON_MAINNET) == "live"
    assert tm._tron_environment(tp.TRON_NILE) == "test"


@pytest.mark.asyncio
async def test_the_matcher_does_not_reach_across_networks(monkeypatch):
    """A mainnet matcher pass must not see a Nile settlement, and neither must
    match it to the other network's intent. The failure is silent in both
    directions: unmatched money on one side, a wrongly completed intent on the
    other."""
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement, SettlementStatus
    from decimal import Decimal

    # 1.5 USDT == the 1500000 base units the settlement carries: an EXACT
    # match, so the outcome bucket is unambiguously "matched" rather than the
    # over/under-payment paths.
    nile_intent = await _make_intent(
        chain="TRON_NILE", recipient=MERCH, environment="test", amount=1.5
    )
    await _make_intent(
        chain="TRON", recipient=MERCH, environment="live", amount=1.5
    )

    async with async_session() as db:
        db.add(PaymentSettlement(
            invoice_id=None, merchant=MERCH, payer=PAYER, token=NILE_USDT,
            amount=Decimal("1500000"),
            block_timestamp=datetime.now(timezone.utc),
            chain_id=TRON_NILE_CHAIN_ID, tx_hash="n" * 64, log_index=0,
            block_number=1, status=SettlementStatus.pending, intent_id=None,
        ))
        await db.commit()

    async def _fake(db, *, merchant_id, event, intent, extra_payload=None):
        return 1

    monkeypatch.setattr("app.services.webhook_service.send_webhook", _fake)

    mainnet_pass = await tm.match_pending_tron_settlements(tp.TRON_MAINNET)
    assert mainnet_pass["matched"] == 0, "a mainnet pass saw a Nile settlement"

    nile_pass = await tm.match_pending_tron_settlements(tp.TRON_NILE)
    assert nile_pass["matched"] == 1

    async with async_session() as db:
        row = (await db.execute(select(PaymentSettlement))).scalars().one()
        assert row.intent_id == nile_intent
