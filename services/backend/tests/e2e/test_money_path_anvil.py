"""
Deterministic Anvil E2E — full payment money-path.

Reproduces the pay page's on-chain flow programmatically against a local Anvil
node and asserts the whole loop: create intent → build on-chain payload (the exact
function the API response uses) → pay on-chain → indexer ingests + finalizes →
invoice paid, balances correct, exactly one valid signed webhook.

Scenarios:
  A. USDC via payWithPermit (EIP-2612)
  B. USDT via approve + pay (no-bool-return token)
  C. negative: short amount → settlement rejected, invoice not paid, no webhook

Run:  make e2e-anvil   (or: pytest -m e2e tests/e2e -v)
"""

import json
import secrets as pysecrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from eth_abi import encode as abi_encode
from eth_account import Account
from web3 import Web3

from tests.e2e.conftest import ANVIL_ACCOUNTS, CHAIN_ID, CONTRACTS_DIR

pytestmark = pytest.mark.e2e

PERMIT_TYPEHASH_TEXT = (
    "Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
)


# ── ABI loading from forge artifacts ─────────────────────────────────────────
def _abi(sol_file: str, contract: str) -> list:
    art = json.loads((CONTRACTS_DIR / "out" / sol_file / f"{contract}.json").read_text())
    return art["abi"]


def _w3_contract(w3, addr, sol_file, contract):
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=_abi(sol_file, contract))


# ── tx helper: build → sign with a specific dev key → send → wait ────────────
def _send(w3, fn, key, value=0):
    acct = Account.from_key(key)
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": CHAIN_ID,
        "value": value,
    })
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    assert rcpt.status == 1, f"tx reverted: {rcpt}"
    return rcpt


def _sign_permit(w3, token, owner_key, owner_addr, spender, value, deadline):
    """EIP-2612 permit signature built from the token's live domain — mirrors the
    Foundry _signPermit helper and the pay page's signTypedData."""
    nonce = token.functions.nonces(Web3.to_checksum_address(owner_addr)).call()
    domain_sep = token.functions.DOMAIN_SEPARATOR().call()
    type_hash = w3.keccak(text=PERMIT_TYPEHASH_TEXT)
    struct_hash = w3.keccak(
        abi_encode(
            ["bytes32", "address", "address", "uint256", "uint256", "uint256"],
            [type_hash,
             Web3.to_checksum_address(owner_addr),
             Web3.to_checksum_address(spender),
             value, nonce, deadline],
        )
    )
    digest = w3.keccak(b"\x19\x01" + bytes(domain_sep) + struct_hash)
    sig = Account.unsafe_sign_hash(digest, private_key=owner_key)
    return sig.v, sig.r.to_bytes(32, "big"), sig.s.to_bytes(32, "big")


def _anvil_mine(w3, n=1):
    w3.provider.make_request("anvil_mine", [hex(n)])


def _hdr(headers: dict, name: str) -> str:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return ""


# ── backend wiring fixture ───────────────────────────────────────────────────
@pytest_asyncio.fixture
async def wired(deployed, webhook_receiver, anvil, monkeypatch):
    """Wire the backend (indexer registry + settings + RPC pointer + webhook row)
    at the deployed Anvil stack. Pure config — no logic edits."""
    import app.services.router_registry as rr
    import app.services.payment_indexer as pidx
    import app.services.cache_service as cache
    import app.services.rpc_manager as rpcm
    from app.config import get_settings
    from app.db.session import engine, async_session
    from app.models.db_models import Base
    import app.models.merchant_models  # noqa: F401 — register tables
    import app.models.settlement_models  # noqa: F401
    from app.models.merchant_models import MerchantWebhook

    w3 = Web3(Web3.HTTPProvider(anvil))

    # ── shared fakeredis: indexer last-block persistence + webhook idempotency ──
    import fakeredis.aioredis as fr
    fake = fr.FakeRedis()
    await fake.flushdb()

    async def _get_redis():
        return fake
    monkeypatch.setattr(pidx, "get_redis", _get_redis)
    monkeypatch.setattr(cache, "get_redis", _get_redis)

    # ── point the indexer/quoteFee RPC at Anvil ──
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

    # ── register the local Anvil chain + deployed token addresses (data/config) ──
    monkeypatch.setitem(rr.CHAIN_IDS, "anvil", CHAIN_ID)
    monkeypatch.setitem(
        rr.TOKEN_REGISTRY, "anvil",
        {
            "USDC": (deployed["usdc"].lower(), 6),
            "USDT": (deployed["usdt"].lower(), 6),
        },
    )

    # ── fast-finalization settings + router address ──
    s = get_settings()
    monkeypatch.setattr(s, "rsends_router_addresses_json", json.dumps({str(CHAIN_ID): deployed["router"]}))
    monkeypatch.setattr(s, "indexer_use_finalized_tag", False)
    monkeypatch.setattr(s, "indexer_confirmations", 1)
    monkeypatch.setattr(s, "indexer_reorg_safety_depth", 1)

    # ── tables + a merchant webhook pointed at the local receiver ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    merchant_id = "m_e2e"
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
        "router": deployed["router"],
        "usdc": deployed["usdc"],
        "usdt": deployed["usdt"],
        "merchant_id": merchant_id,
        "secret": secret,
        "captured": webhook_receiver["captured"],
        "router_c": _w3_contract(w3, deployed["router"], "RSendsRouter.sol", "RSendsRouter"),
        "usdc_c": _w3_contract(w3, deployed["usdc"], "E2EMocks.sol", "MockUSDC6"),
        "usdt_c": _w3_contract(w3, deployed["usdt"], "E2EMocks.sol", "MockUSDT6"),
    }


# ── create intent + build the exact on-chain payload the pay page consumes ────
async def _create_intent(wired, currency, amount):
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
            merchant_id=wired["merchant_id"],
            amount=amount,
            currency=currency,
            chain="anvil",
            recipient=merchant,
            onchain_invoice_id=derive_invoice_id(ref),
            status=IntentStatus.pending,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        db.add(intent)
        await db.commit()
        onchain = await build_onchain_payment(intent)
    assert onchain and not onchain["feeUnavailable"], f"onchain payload unavailable: {onchain}"
    return iid, onchain


async def _intent_status(intent_id):
    from sqlalchemy import select
    from app.db.session import async_session
    from app.models.merchant_models import PaymentIntent
    async with async_session() as db:
        r = await db.execute(select(PaymentIntent).where(PaymentIntent.intent_id == intent_id))
        i = r.scalar_one()
        return i.status.value


async def _settlement_status(invoice_id):
    from sqlalchemy import select
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement
    async with async_session() as db:
        r = await db.execute(
            select(PaymentSettlement).where(PaymentSettlement.invoice_id == invoice_id.lower())
        )
        rows = r.scalars().all()
        return [x.status.value for x in rows]


async def _drive(watcher, w3, intent_id, *, want, max_iter=20):
    """Mine + tick until the invoice reaches `want` (or timeout)."""
    for _ in range(max_iter):
        await watcher._tick()
        if await _intent_status(intent_id) == want:
            return True
        _anvil_mine(w3, 1)
    return await _intent_status(intent_id) == want


def _completed_webhooks(captured):
    out = []
    for d in captured:
        try:
            if json.loads(d["body"]).get("event") == "payment.completed":
                out.append(d)
        except Exception:
            pass
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  A. USDC via payWithPermit
# ═══════════════════════════════════════════════════════════════════════════
async def test_usdc_paywithpermit_full_loop(wired):
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired["w3"]
    watcher = PaymentWatcher(CHAIN_ID, wired["router"])
    await watcher._tick()  # initialize indexer position BEFORE the payment

    intent_id, oc = await _create_intent(wired, "USDC", 100.0)
    amount, fee, max_fee = int(oc["amount"]), int(oc["fee"]), int(oc["maxFee"])
    assert fee == 600_000  # €0.60 below threshold

    deadline = int(time.time()) + 3600
    v, r, s = _sign_permit(
        w3, wired["usdc_c"],
        ANVIL_ACCOUNTS["payer"]["key"], ANVIL_ACCOUNTS["payer"]["address"],
        wired["router"], amount + max_fee, deadline,
    )
    _send(
        w3,
        wired["router_c"].functions.payWithPermit(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            amount, max_fee, deadline, v, r, s,
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)  # past confirmation depth
    assert await _drive(watcher, w3, intent_id, want="paid"), "invoice not paid"

    # On-chain balances: merchant got amount, feeCollector got fee.
    merchant = ANVIL_ACCOUNTS["merchant"]["address"]
    fee_collector = ANVIL_ACCOUNTS["feeCollector"]["address"]
    assert wired["usdc_c"].functions.balanceOf(Web3.to_checksum_address(merchant)).call() == amount
    assert wired["usdc_c"].functions.balanceOf(Web3.to_checksum_address(fee_collector)).call() == fee

    _assert_one_signed_completed(wired, oc, fee)


# ═══════════════════════════════════════════════════════════════════════════
#  B. USDT via approve + pay
# ═══════════════════════════════════════════════════════════════════════════
async def test_usdt_approve_pay_full_loop(wired):
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired["w3"]
    watcher = PaymentWatcher(CHAIN_ID, wired["router"])
    await watcher._tick()

    intent_id, oc = await _create_intent(wired, "USDT", 250.0)
    amount, fee, max_fee = int(oc["amount"]), int(oc["fee"]), int(oc["maxFee"])

    # approve(router, amount + maxFee) then pay(...)
    _send(
        w3,
        wired["usdt_c"].functions.approve(Web3.to_checksum_address(wired["router"]), amount + max_fee),
        ANVIL_ACCOUNTS["payer"]["key"],
    )
    _send(
        w3,
        wired["router_c"].functions.pay(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            amount, max_fee,
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)
    assert await _drive(watcher, w3, intent_id, want="paid"), "invoice not paid"

    merchant = ANVIL_ACCOUNTS["merchant"]["address"]
    fee_collector = ANVIL_ACCOUNTS["feeCollector"]["address"]
    assert wired["usdt_c"].functions.balanceOf(Web3.to_checksum_address(merchant)).call() == amount
    assert wired["usdt_c"].functions.balanceOf(Web3.to_checksum_address(fee_collector)).call() == fee

    _assert_one_signed_completed(wired, oc, fee)


# ═══════════════════════════════════════════════════════════════════════════
#  C. negative — short amount → rejected, not paid, no webhook
# ═══════════════════════════════════════════════════════════════════════════
async def test_short_amount_rejected_no_webhook(wired):
    from app.services.payment_indexer import PaymentWatcher

    w3 = wired["w3"]
    watcher = PaymentWatcher(CHAIN_ID, wired["router"])
    await watcher._tick()

    # Invoice expects 100 USDC; payer pays only 40 for the same invoiceId.
    intent_id, oc = await _create_intent(wired, "USDC", 100.0)
    short = 40_000_000  # 40 USDC < expected 100 USDC
    short_fee = wired["router_c"].functions.quoteFee(
        Web3.to_checksum_address(oc["token"]), short
    ).call()

    _send(
        w3,
        wired["usdc_c"].functions.approve(Web3.to_checksum_address(wired["router"]), short + short_fee),
        ANVIL_ACCOUNTS["payer"]["key"],
    )
    _send(
        w3,
        wired["router_c"].functions.pay(
            Web3.to_bytes(hexstr=oc["invoiceId"]),
            Web3.to_checksum_address(oc["merchant"]),
            Web3.to_checksum_address(oc["token"]),
            short, short_fee,
        ),
        ANVIL_ACCOUNTS["payer"]["key"],
    )

    _anvil_mine(w3, 3)
    # Drive several ticks; invoice must NOT become paid.
    for _ in range(6):
        await watcher._tick()
        _anvil_mine(w3, 1)

    status = await _intent_status(intent_id)
    assert status != "paid", f"short payment wrongly paid (status={status})"
    settlements = await _settlement_status(oc["invoiceId"])
    assert "rejected" in settlements, f"expected a rejected settlement, got {settlements}"
    assert "final" not in settlements
    assert _completed_webhooks(wired["captured"]) == [], "no webhook expected for rejected payment"


# ── shared webhook assertion ─────────────────────────────────────────────────
def _assert_one_signed_completed(wired, oc, fee):
    from app.services.webhook_service import verify_webhook_signature

    completed = _completed_webhooks(wired["captured"])
    assert len(completed) == 1, f"expected exactly one payment.completed, got {len(completed)}"
    d = completed[0]
    ts = _hdr(d["headers"], "X-RSend-Timestamp")
    sig = _hdr(d["headers"], "X-RSend-Signature")
    assert ts and sig
    assert verify_webhook_signature(wired["secret"], ts, d["body"], sig), "bad webhook signature"

    payload = json.loads(d["body"])
    assert payload["event"] == "payment.completed"
    assert payload["event_id"].startswith("evt_")
    assert payload["onchain_invoice_id"].lower() == oc["invoiceId"].lower()
    assert int(payload["fee"]) == fee
