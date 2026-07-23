"""
Deterministic Anvil E2E — RSendsRouterV2 money-path (fee-less, ownerless).

Twin of test_money_path_anvil.py (which STAYS as the v1 pin). Same loop —
create intent → build_onchain_payment → pay on-chain → indexer ingests +
finalizes → invoice paid — but through the v2 router: ONE transfer per
payment, payer parts with exactly `amount`, and the assertions that define
P3's acceptance:

  - merchant delta == +amount, payer delta == -amount (exact)
  - feeCollector delta == 0 (no fee leg exists)
  - router balance == 0 (never holds funds)
  - settlement row fee == 0; webhook matches the fee-less golden contract

Scenarios:
  A. USDC via payWithPermit (permit value == exactly amount, 8-arg call)
  B. USDT via approve(amount) + 4-arg pay
  C. negative: short amount → settlement rejected, invoice not paid, no webhook

Run:  make e2e-anvil   (or: pytest -m e2e tests/e2e -v)
"""

import json
import secrets as pysecrets
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from web3 import Web3

from tests.e2e.conftest import ANVIL_ACCOUNTS, CHAIN_ID
from tests.e2e.test_money_path_anvil import (
    _anvil_mine,
    _completed_webhooks,
    _drive,
    _hdr,
    _intent_status,
    _send,
    _settlement_status,
    _sign_permit,
    _w3_contract,
)

pytestmark = pytest.mark.e2e


# ── backend wiring fixture (v2-only chain — the mainnet shape) ───────────────
@pytest_asyncio.fixture
async def wired_v2(deployed, webhook_receiver, anvil, monkeypatch):
    """Wire the backend at the deployed Anvil stack with ONLY the v2 router
    configured for the chain — the exact mainnet-cutover configuration."""
    import fakeredis.aioredis as fr

    import app.services.cache_service as cache
    import app.services.payment_indexer as pidx
    import app.services.router_registry as rr
    import app.services.rpc_manager as rpcm
    from app.config import get_settings
    from app.db.session import engine, async_session
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import MerchantWebhook

    w3 = Web3(Web3.HTTPProvider(anvil))

    fake = fr.FakeRedis()
    await fake.flushdb()

    async def _get_redis():
        return fake
    monkeypatch.setattr(pidx, "get_redis", _get_redis)
    monkeypatch.setattr(cache, "get_redis", _get_redis)

    class AnvilRPC:
        def __init__(self, url):
            self.url = url

        async def call(self, method, params, timeout=10):
            async with httpx.AsyncClient() as c:
                r = await c.post(
                    self.url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    timeout=timeout,
                )
            d = r.json()
            if "error" in d:
                raise RuntimeError(f"RPC {method}: {d['error']}")
            return d.get("result")

    monkeypatch.setattr(rpcm, "get_rpc_manager", lambda chain_id=CHAIN_ID: AnvilRPC(anvil))

    monkeypatch.setitem(rr.CHAIN_IDS, "anvil", CHAIN_ID)
    monkeypatch.setitem(
        rr.TOKEN_REGISTRY, "anvil",
        {
            "USDC": (deployed["usdc"].lower(), 6),
            "USDT": (deployed["usdt"].lower(), 6),
        },
    )

    s = get_settings()
    # v2-ONLY: the v1 map is empty for this chain — proves the mainnet shape
    # (a v1-less chain must still create intents, index and settle).
    monkeypatch.setattr(s, "rsends_router_addresses_json", "")
    monkeypatch.setattr(
        s, "rsends_router_v2_addresses_json",
        json.dumps({str(CHAIN_ID): deployed["router_v2"]}),
    )
    monkeypatch.setattr(s, "indexer_use_finalized_tag", False)
    monkeypatch.setattr(s, "indexer_confirmations", 1)
    monkeypatch.setattr(s, "indexer_reorg_safety_depth", 1)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    merchant_id = "m_e2e_v2"
    secret = "whsec_" + pysecrets.token_hex(16)
    async with async_session() as db:
        db.add(MerchantWebhook(
            merchant_id=merchant_id,
            url=webhook_receiver["url"],
            secret=secret,
            events=["payment.completed", "payment.reversed"],
            is_active=True,
        ))
        await db.commit()

    return {
        "w3": w3,
        "router_v2": deployed["router_v2"],
        "usdc": deployed["usdc"],
        "usdt": deployed["usdt"],
        "merchant_id": merchant_id,
        "secret": secret,
        "captured": webhook_receiver["captured"],
        "router_v2_c": _w3_contract(w3, deployed["router_v2"], "RSendsRouterV2.sol", "RSendsRouterV2"),
        "usdc_c": _w3_contract(w3, deployed["usdc"], "E2EMocks.sol", "MockUSDC6"),
        "usdt_c": _w3_contract(w3, deployed["usdt"], "E2EMocks.sol", "MockUSDT6"),
    }


async def _create_intent_v2(wired_v2, currency, amount):
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent, IntentStatus
    from app.services.router_registry import derive_invoice_id, build_onchain_payment

    ref = pysecrets.token_hex(8)
    iid = f"pi_{pysecrets.token_hex(8)}"
    merchant = ANVIL_ACCOUNTS["merchant"]["address"].lower()
    async with async_session() as db:
        intent = PaymentIntent(
            intent_id=iid,
            reference_id=ref,
            merchant_id=wired_v2["merchant_id"],
            amount=amount,
            currency=currency,
            chain="anvil",
            recipient=merchant,
            onchain_invoice_id=derive_invoice_id(ref, CHAIN_ID),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(intent)
        await db.commit()
        onchain = await build_onchain_payment(intent)
    assert onchain is not None, "onchain payload unavailable"
    # The P3 payload contract: v2, fee "0", no maxFee, never feeUnavailable.
    assert onchain["routerVersion"] == 2
    assert onchain["router"].lower() == wired_v2["router_v2"].lower()
    assert onchain["fee"] == "0"
    assert onchain["total"] == onchain["amount"]
    assert onchain["maxFee"] is None
    assert onchain["feeUnavailable"] is False
    return iid, onchain


def _assert_one_signed_completed_feeless(wired_v2, oc):
    from app.services.webhook_service import verify_webhook_signature

    completed = _completed_webhooks(wired_v2["captured"])
    assert len(completed) == 1, f"expected exactly one payment.completed, got {len(completed)}"
    d = completed[0]
    ts = _hdr(d["headers"], "X-RSend-Timestamp")
    sig = _hdr(d["headers"], "X-RSend-Signature")
    assert ts and sig
    assert verify_webhook_signature(wired_v2["secret"], ts, d["body"], sig), "bad webhook signature"

    payload = json.loads(d["body"])
    assert payload["event"] == "payment.completed"
    assert payload["onchain_invoice_id"].lower() == oc["invoiceId"].lower()
    assert "fee" not in payload
    assert "network" not in payload and "merchant_id" not in payload
    assert payload["chain_id"] is not None
    assert payload["tx_hash"], "settlement tx_hash missing from payload"


# ═══════════════════════════════════════════════════════════════════════════
#  A. USDC via payWithPermit — permit value == exactly amount
# ═══════════════════════════════════════════════════════════════════════════
async def test_v2_usdc_paywithpermit_single_transfer(wired_v2):
    from decimal import Decimal

    from sqlalchemy import select

    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired_v2["w3"]
    watcher = PaymentWatcher(CHAIN_ID, router_v2_address=wired_v2["router_v2"])
    await watcher._tick()  # initialize indexer position BEFORE the payment

    intent_id, oc = await _create_intent_v2(wired_v2, "USDC", 100.0)
    amount = int(oc["amount"])

    merchant = Web3.to_checksum_address(ANVIL_ACCOUNTS["merchant"]["address"])
    fee_collector = Web3.to_checksum_address(ANVIL_ACCOUNTS["feeCollector"]["address"])
    payer = Web3.to_checksum_address(ANVIL_ACCOUNTS["payer"]["address"])
    bal = wired_v2["usdc_c"].functions.balanceOf
    merchant_before = bal(merchant).call()
    payer_before = bal(payer).call()
    collector_before = bal(fee_collector).call()

    deadline = int(time.time()) + 3600
    v, r, s = _sign_permit(
        w3, wired_v2["usdc_c"],
        ANVIL_ACCOUNTS["payer"]["key"], ANVIL_ACCOUNTS["payer"]["address"],
        wired_v2["router_v2"], amount, deadline,   # permit EXACTLY amount — no fee term
    )
    _send(
        w3,
        wired_v2["router_v2_c"].functions.payWithPermit(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            amount, deadline, v, r, s,             # 8 args — no maxFee
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)
    assert await _drive(watcher, w3, intent_id, want="paid"), "invoice not paid"

    # Single-transfer conservation: exactly one leg moved.
    assert bal(merchant).call() == merchant_before + amount
    assert bal(payer).call() == payer_before - amount
    assert bal(fee_collector).call() == collector_before, "fee collector must receive NOTHING"
    assert bal(Web3.to_checksum_address(wired_v2["router_v2"])).call() == 0
    assert w3.eth.get_balance(Web3.to_checksum_address(wired_v2["router_v2"])) == 0

    async with async_session() as db:
        stl = (await db.execute(
            select(PaymentSettlement).where(
                PaymentSettlement.invoice_id == oc["invoiceId"].lower()
            )
        )).scalars().all()
        assert stl and all(x.fee == Decimal(0) for x in stl)

    _assert_one_signed_completed_feeless(wired_v2, oc)


# ═══════════════════════════════════════════════════════════════════════════
#  B. USDT via approve + pay — approve exactly amount, 4-arg pay
# ═══════════════════════════════════════════════════════════════════════════
async def test_v2_usdt_approve_pay_single_transfer(wired_v2):
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired_v2["w3"]
    watcher = PaymentWatcher(CHAIN_ID, router_v2_address=wired_v2["router_v2"])
    await watcher._tick()

    intent_id, oc = await _create_intent_v2(wired_v2, "USDT", 250.0)
    amount = int(oc["amount"])

    merchant = Web3.to_checksum_address(ANVIL_ACCOUNTS["merchant"]["address"])
    fee_collector = Web3.to_checksum_address(ANVIL_ACCOUNTS["feeCollector"]["address"])
    bal = wired_v2["usdt_c"].functions.balanceOf
    merchant_before = bal(merchant).call()
    collector_before = bal(fee_collector).call()

    _send(
        w3,
        wired_v2["usdt_c"].functions.approve(
            Web3.to_checksum_address(wired_v2["router_v2"]), amount  # exactly amount
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )
    _send(
        w3,
        wired_v2["router_v2_c"].functions.pay(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            amount,                                # 4 args — no maxFee
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)
    assert await _drive(watcher, w3, intent_id, want="paid"), "invoice not paid"

    assert bal(merchant).call() == merchant_before + amount
    assert bal(fee_collector).call() == collector_before, "fee collector must receive NOTHING"
    assert bal(Web3.to_checksum_address(wired_v2["router_v2"])).call() == 0

    _assert_one_signed_completed_feeless(wired_v2, oc)


# ═══════════════════════════════════════════════════════════════════════════
#  C. negative — short amount → rejected, not paid, no webhook
# ═══════════════════════════════════════════════════════════════════════════
async def test_v2_short_amount_rejected_no_webhook(wired_v2):
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired_v2["w3"]
    watcher = PaymentWatcher(CHAIN_ID, router_v2_address=wired_v2["router_v2"])
    await watcher._tick()

    intent_id, oc = await _create_intent_v2(wired_v2, "USDC", 100.0)
    short = 40_000_000  # 40 USDC < expected 100 USDC

    _send(
        w3,
        wired_v2["usdc_c"].functions.approve(
            Web3.to_checksum_address(wired_v2["router_v2"]), short
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )
    _send(
        w3,
        wired_v2["router_v2_c"].functions.pay(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            short,
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)
    for _ in range(6):
        await watcher._tick()
        _anvil_mine(w3, 1)

    status = await _intent_status(intent_id)
    assert status != "paid", f"short payment wrongly paid (status={status})"
    settlements = await _settlement_status(oc["invoiceId"])
    assert "rejected" in settlements, f"expected a rejected settlement, got {settlements}"
    assert "final" not in settlements
    assert _completed_webhooks(wired_v2["captured"]) == [], "no webhook expected for rejected payment"
