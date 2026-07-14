"""
RSends Backend — On-Chain Payment Indexer (NON-CUSTODIAL).

Replaces the custodial deposit-address poller/sweeper. Instead of watching
RSends-controlled deposit addresses and sweeping funds, this service watches
the `RSendsRouter` smart contract for `PaymentMade` events on each configured
chain. Processing is two-phase and reorg-safe:

  INGEST (every tick): persist each PaymentMade log as a PENDING settlement
    (idempotent on chain+tx+logIndex, with block number AND block hash). Match
    the event's invoiceId to the off-chain PaymentIntent and validate it
    (merchant/token/amount); validation failures are recorded `rejected` and the
    intent flagged for review. Nothing is marked paid here.
  FINALIZE / RECONCILE (every tick): once a settlement's block is final (the
    chain's finalized tag, or latest - confirmations) AND its stored hash is
    still canonical, promote it to FINAL — mark the intent paid and fire the
    merchant HMAC webhook (payment.completed) exactly once. If a settlement's
    block hash is no longer canonical (reorg / re-inclusion), mark it REORGED
    and reverse its effect (un-pay the intent; signal payment.reversed if the
    webhook already fired).

RSends never holds keys or funds — funds move payer -> merchant atomically
inside the contract call. This indexer is purely an observer.

Event (RSendsRouter):
  PaymentMade(
    bytes32 indexed invoiceId,   # topic[1]
    address indexed merchant,    # topic[2]
    address indexed payer,       # topic[3]
    address token,               # data word 0 (address(0) == native ETH)
    uint256 amount,              # data word 1
    uint256 fee,                 # data word 2 (paid payer -> feeCollector)
    uint256 blockTimestamp       # data word 3
  )

Config (see app/config.py):
  - settings.rsends_router_addresses : {chain_id: "0xRouter", ...}
  - settings.indexer_rpc_urls        : {chain_id: "https://rpc", ...} (optional;
                                        falls back to rpc_manager)
  - settings.indexer_confirmations   : block confirmations before processing

Checkpointing uses Redis (survives restarts), mirroring the old poller.
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, or_, select, update

from app.config import get_settings
from app.services.cache_service import get_redis

logger = logging.getLogger("payment_indexer")

# ── Constants ────────────────────────────────────────────────
POLL_INTERVAL = 5                # seconds between ticks
MAX_BLOCKS_PER_TICK = 500        # getLogs range cap per tick
DEFAULT_CONFIRMATIONS = 2

REDIS_LAST_BLOCK_KEY = "indexer:last_block:{chain_id}"

ZERO_ADDRESS = "0x" + "0" * 40

# keccak256("PaymentMade(bytes32,address,address,address,uint256,uint256,uint256)")
# Computed at import when eth_utils is available; the literal is the canonical
# fallback so the indexer still works in minimal environments.
# NOTE: the trailing uint256 is `fee` — added when the router started emitting it.
_PAYMENT_MADE_SIG = "PaymentMade(bytes32,address,address,address,uint256,uint256,uint256)"


def _payment_made_topic() -> str:
    try:
        from eth_utils import keccak  # type: ignore

        return "0x" + keccak(text=_PAYMENT_MADE_SIG).hex()
    except Exception:  # pragma: no cover - fallback for minimal envs
        # NOTE: if you change the event signature, recompute this constant.
        return "0xUNRESOLVED_RECOMPUTE_TOPIC"


PAYMENT_MADE_TOPIC = _payment_made_topic()


# ── Redis checkpoint helpers ─────────────────────────────────
async def _get_last_block(chain_id: int) -> Optional[int]:
    r = await get_redis()
    if r is None:
        return None
    val = await r.get(REDIS_LAST_BLOCK_KEY.format(chain_id=chain_id))
    return int(val) if val else None


async def _set_last_block(chain_id: int, block_number: int) -> None:
    r = await get_redis()
    if r is None:
        return
    await r.set(REDIS_LAST_BLOCK_KEY.format(chain_id=chain_id), str(block_number))


# ── Decoding ─────────────────────────────────────────────────
def _addr_from_topic(topic: str) -> str:
    """Last 20 bytes of a 32-byte topic → 0x address (lowercased)."""
    return ("0x" + topic[-40:]).lower()


def _decode_payment_made(log: dict) -> Optional[dict]:
    """Decode a PaymentMade log into a dict, or None if it isn't one."""
    topics = log.get("topics", [])
    if len(topics) < 4:
        return None
    if topics[0].lower() != PAYMENT_MADE_TOPIC.lower():
        return None

    invoice_id = topics[1]                       # bytes32 hex (0x...)
    merchant = _addr_from_topic(topics[2])
    payer = _addr_from_topic(topics[3])

    data = (log.get("data") or "0x")[2:]
    # 4 non-indexed words: token (address), amount (uint256), fee (uint256), blockTimestamp
    if len(data) < 64 * 4:
        return None
    token = "0x" + data[0:64][-40:]
    amount = int(data[64:128], 16)
    fee = int(data[128:192], 16)
    block_ts = int(data[192:256], 16)

    return {
        "invoice_id": invoice_id,
        "merchant": merchant,
        "payer": payer,
        "token": token.lower(),
        "amount": amount,
        "fee": fee,
        "block_timestamp": block_ts,
        "tx_hash": (log.get("transactionHash") or "").lower(),
        "log_index": int(log.get("logIndex", "0x0"), 16),
        "block_number": int(log.get("blockNumber", "0x0"), 16),
        "block_hash": (log.get("blockHash") or "").lower(),
    }


# ── Validation: the on-chain event must match the stored invoice ──
def _validate_event_against_intent(ev: dict, intent) -> list:
    """Return human-readable mismatch reasons between a PaymentMade event and the
    stored intent (empty == valid). Checks: correct merchant, correct token, and
    on-chain amount >= invoice amount. If the token isn't in the registry we can't
    compute the expected token/amount, so those checks are skipped (merchant still
    applies)."""
    from app.services.router_registry import token_for, to_base_units

    reasons = []

    expected_merchant = (intent.recipient or "").lower()
    if not expected_merchant:
        # FAIL-CLOSED (Phase B): an intent with no recipient/settlement wallet
        # cannot be validated against a payee. Post-gate this can only be a
        # pre-gate legacy row (its /pay link never worked) — record it rejected
        # rather than silently settling against an arbitrary merchant.
        reasons.append("intent has no recipient/settlement wallet — cannot validate merchant")
    elif ev["merchant"].lower() != expected_merchant:
        reasons.append(f"merchant {ev['merchant']} != expected {expected_merchant}")

    tok = token_for(intent.chain or "base", intent.currency)
    if tok is not None:
        expected_token, decimals = tok
        if ev["token"].lower() != expected_token.lower():
            reasons.append(f"token {ev['token']} != expected {expected_token}")
        expected_amount = to_base_units(intent.amount, decimals)
        if ev["amount"] < expected_amount:
            reasons.append(f"amount {ev['amount']} < expected {expected_amount}")

    return reasons


# ── Finality helpers ─────────────────────────────────────────
async def _finalized_head(rpc, settings, latest: int) -> int:
    """Block number that is considered FINAL. Prefers the chain's finalized/safe
    tag (Base/Ethereum support it); falls back to `latest - indexer_confirmations`."""
    if getattr(settings, "indexer_use_finalized_tag", True):
        tag = getattr(settings, "indexer_finalized_tag", "finalized") or "finalized"
        try:
            blk = await rpc.call("eth_getBlockByNumber", [tag, False])
            num = (blk or {}).get("number")
            if num is not None:
                return int(num, 16)
        except Exception:  # pragma: no cover - tag unsupported / RPC hiccup
            pass
    conf = getattr(settings, "indexer_confirmations", DEFAULT_CONFIRMATIONS)
    return latest - conf


async def _canonical_block_hash(rpc, block_number: int, cache: dict) -> Optional[str]:
    """Canonical block hash at `block_number` (cached per tick). None if the
    block can't be resolved (RPC gap / not yet known) — caller must NOT treat
    None as a reorg, only a hash that differs from what we stored."""
    if block_number in cache:
        return cache[block_number]
    h = None
    try:
        blk = await rpc.call("eth_getBlockByNumber", [hex(block_number), False])
        raw = (blk or {}).get("hash")
        h = raw.lower() if raw else None
    except Exception:  # pragma: no cover - RPC failure
        h = None
    cache[block_number] = h
    return h


# ── Settlement persistence (INGEST) ──────────────────────────
async def _record_settlement(chain_id: int, ev: dict) -> str:
    """INGEST a PaymentMade log as a PENDING settlement (idempotent).

    NEVER marks an invoice paid — that happens only in _finalize_and_reconcile
    once the block is final AND its hash is still canonical. Validation failures
    (wrong merchant/token/under-amount) are persisted as `rejected` and the
    intent is flagged for review; they never settle.

    Returns: "new" (first sight), "reconciled" (re-included in a different
    block → updated), or "duplicate" (same log+hash already stored).
    """
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement, SettlementStatus
    from app.models.merchant_models import PaymentIntent, IntentStatus

    async with async_session() as db:
        existing = (await db.execute(
            select(PaymentSettlement).where(
                PaymentSettlement.chain_id == chain_id,
                PaymentSettlement.tx_hash == ev["tx_hash"],
                PaymentSettlement.log_index == ev["log_index"],
            )
        )).scalar_one_or_none()

        # ── Match the off-chain intent by on-chain invoiceId ──
        intent = (await db.execute(
            select(PaymentIntent).where(
                PaymentIntent.onchain_invoice_id == ev["invoice_id"].lower()
            )
        )).scalar_one_or_none()
        mismatches = _validate_event_against_intent(ev, intent) if intent is not None else []

        block_dt = (
            datetime.fromtimestamp(ev["block_timestamp"], tz=timezone.utc)
            if ev["block_timestamp"] else None
        )
        new_hash = (ev.get("block_hash") or "").lower() or None

        if existing is not None:
            # Same log already recorded in the same block → true duplicate.
            if (existing.block_hash or "").lower() == (new_hash or "").lower():
                return "duplicate"
            # Different block hash for the same (chain, tx, logIndex): the log was
            # re-included in a new block after a reorg. Reconcile instead of
            # deduping so we never double-count and never strand a stale row.
            if existing.status == SettlementStatus.final and existing.webhook_fired_at:
                # A previously FINAL log moved — finalized assumption broken.
                logger.error(
                    "[indexer] ALERT finalized settlement re-included in a new block "
                    "(tx=%s old_hash=%s new_hash=%s) — reversing",
                    ev["tx_hash"][:16], existing.block_hash, new_hash,
                )
                await _reverse_settlement(db, existing)
            existing.block_number = ev["block_number"]
            existing.block_hash = new_hash
            existing.block_timestamp = block_dt
            existing.finalized_at = None
            existing.status = (
                SettlementStatus.rejected if mismatches else SettlementStatus.pending
            )
            await db.commit()
            return "reconciled"

        # ── First sight: persist as pending (or rejected on mismatch) ──
        status = SettlementStatus.rejected if mismatches else SettlementStatus.pending
        db.add(PaymentSettlement(
            invoice_id=ev["invoice_id"].lower(),
            merchant=ev["merchant"],
            payer=ev["payer"],
            token=ev["token"],
            amount=Decimal(ev["amount"]),
            fee=Decimal(ev.get("fee", 0)),
            block_timestamp=block_dt,
            chain_id=chain_id,
            tx_hash=ev["tx_hash"],
            log_index=ev["log_index"],
            block_number=ev["block_number"],
            block_hash=new_hash,
            status=status,
            intent_id=intent.intent_id if intent else None,
        ))

        if intent is None:
            logger.warning(
                "[indexer] PaymentMade with no matching intent: invoiceId=%s tx=%s",
                ev["invoice_id"][:18], ev["tx_hash"][:16],
            )
        elif mismatches:
            # Correct invoiceId but wrong merchant/token/under-amount: flag for
            # manual review, never auto-settle, no webhook.
            if intent.status == IntentStatus.pending:
                intent.status = IntentStatus.review
                intent.matched_tx_hash = ev["tx_hash"]
                intent.matched_at = datetime.now(timezone.utc)
            logger.warning(
                "[indexer] ALERT PaymentMade failed validation for intent %s (tx=%s): %s "
                "— recorded rejected, no settlement",
                intent.intent_id, ev["tx_hash"][:16], "; ".join(mismatches),
            )

        await db.commit()
        return "new"


# ── Finalization + reorg reconciliation ──────────────────────
async def _finalize_settlement(db, settlement, chain_id: int) -> None:
    """Promote a canonical, finalized PENDING settlement to FINAL: mark the
    matched intent paid and fire the payment.completed webhook exactly once."""
    from app.models.settlement_models import PaymentSettlement, SettlementStatus
    from app.models.merchant_models import PaymentIntent, IntentStatus

    settlement.status = SettlementStatus.final
    settlement.finalized_at = datetime.now(timezone.utc)

    if not settlement.intent_id:
        return  # orphan settlement (no off-chain invoice) — recorded, nothing to pay

    intent = (await db.execute(
        select(PaymentIntent).where(PaymentIntent.intent_id == settlement.intent_id)
    )).scalar_one_or_none()
    if intent is None or intent.status != IntentStatus.pending:
        return  # already handled / not payable

    ev = {
        "merchant": settlement.merchant,
        "token": settlement.token,
        "amount": int(settlement.amount),
    }
    if _validate_event_against_intent(ev, intent):
        intent.status = IntentStatus.review  # defensive: should already be rejected
        return

    intent.status = IntentStatus.paid
    intent.matched_tx_hash = settlement.tx_hash
    intent.matched_at = datetime.now(timezone.utc)
    intent.completed_at = datetime.now(timezone.utc)
    await db.flush()

    # Fire the merchant webhook exactly once. Atomic claim: only the finalize that
    # flips webhook_fired_at NULL→now wins; concurrent finalizations of the same
    # settlement see rowcount 0 and skip, so the webhook can't double-fire.
    now = datetime.now(timezone.utc)
    claim = await db.execute(
        update(PaymentSettlement)
        .where(
            PaymentSettlement.id == settlement.id,
            PaymentSettlement.webhook_fired_at.is_(None),
        )
        .values(webhook_fired_at=now)
    )
    if claim.rowcount != 1:
        return  # another finalize already claimed the fire → do not double-send
    settlement.webhook_fired_at = now

    try:
        from app.services.webhook_service import send_webhook

        await send_webhook(
            db,
            merchant_id=intent.merchant_id,
            event="payment.completed",
            intent=intent,
            extra_payload={
                "chain_id": chain_id,
                "tx_hash": settlement.tx_hash,
                "fee": str(settlement.fee or 0),
                "settlement": "onchain",
            },
        )
    except Exception:
        # Release the claim so the next reconcile retries the dispatch.
        await db.execute(
            update(PaymentSettlement)
            .where(PaymentSettlement.id == settlement.id)
            .values(webhook_fired_at=None)
        )
        settlement.webhook_fired_at = None
        logger.exception(
            "[indexer] webhook dispatch failed for intent %s (settlement final)",
            intent.intent_id,
        )


async def _reverse_settlement(db, settlement) -> None:
    """Reverse a settlement whose block is no longer canonical: mark it reorged,
    un-pay the intent it settled, and signal a reversal if a webhook already fired."""
    from app.models.settlement_models import PaymentSettlement, SettlementStatus
    from app.models.merchant_models import PaymentIntent, IntentStatus

    already_final = settlement.status == SettlementStatus.final
    fired = settlement.webhook_fired_at is not None
    settlement.status = SettlementStatus.reorged
    settlement.finalized_at = None

    intent = None
    if settlement.intent_id:
        intent = (await db.execute(
            select(PaymentIntent).where(PaymentIntent.intent_id == settlement.intent_id)
        )).scalar_one_or_none()

    if intent is not None and intent.matched_tx_hash == settlement.tx_hash:
        # This settlement is what marked the intent paid/review — roll it back.
        intent.status = IntentStatus.pending
        intent.matched_tx_hash = None
        intent.matched_at = None
        intent.completed_at = None
        await db.flush()

    logger.error(
        "[indexer] ALERT reorg: settlement tx=%s block=%s un-finalized (was_final=%s, webhook_fired=%s)",
        settlement.tx_hash[:16], settlement.block_number, already_final, fired,
    )

    if fired and intent is not None:
        # The merchant was already told "paid" — signal the reversal exactly once.
        # Atomic claim mirrors the paid path: only the reconcile that flips
        # reversal_fired_at NULL→now sends, so concurrent reconciles can't
        # double-fire payment.reversed.
        now = datetime.now(timezone.utc)
        claim = await db.execute(
            update(PaymentSettlement)
            .where(
                PaymentSettlement.id == settlement.id,
                PaymentSettlement.reversal_fired_at.is_(None),
            )
            .values(reversal_fired_at=now)
        )
        if claim.rowcount != 1:
            return  # another reconcile already fired the reversal
        settlement.reversal_fired_at = now

        try:
            from app.services.webhook_service import send_webhook

            await send_webhook(
                db,
                merchant_id=intent.merchant_id,
                event="payment.reversed",
                intent=intent,
                extra_payload={
                    "tx_hash": settlement.tx_hash,
                    "reason": "reorg",
                    "settlement": "onchain",
                },
            )
        except Exception:
            # Release the claim so the next reconcile retries the dispatch.
            await db.execute(
                update(PaymentSettlement)
                .where(PaymentSettlement.id == settlement.id)
                .values(reversal_fired_at=None)
            )
            settlement.reversal_fired_at = None
            logger.exception(
                "[indexer] reversal webhook dispatch failed for intent %s",
                settlement.intent_id,
            )


async def _finalize_and_reconcile(chain_id: int, rpc, final_head: int) -> dict:
    """Reconcile recorded settlements against the canonical chain:

      - PENDING + canonical hash + block <= final_head  → FINAL (pay + webhook once)
      - PENDING/FINAL + hash no longer canonical         → REORGED (reverse effect)
      - PENDING above final_head with canonical hash     → leave pending

    We re-verify recently-FINAL rows (within indexer_reorg_safety_depth of the
    final head) so a deeper-than-expected reorg of an already-paid log is still
    caught and reversed.
    """
    from app.db.session import async_session
    from app.models.settlement_models import PaymentSettlement, SettlementStatus

    settings = get_settings()
    safety = getattr(settings, "indexer_reorg_safety_depth", 64)
    finalized = reorged = 0

    async with async_session() as db:
        rows = (await db.execute(
            select(PaymentSettlement).where(
                PaymentSettlement.chain_id == chain_id,
                or_(
                    PaymentSettlement.status == SettlementStatus.pending,
                    and_(
                        PaymentSettlement.status == SettlementStatus.final,
                        PaymentSettlement.block_number >= final_head - safety,
                    ),
                ),
            )
        )).scalars().all()

        cache: dict = {}
        for s in rows:
            canon = await _canonical_block_hash(rpc, s.block_number, cache)
            if canon is None:
                continue  # can't verify right now — never reorg on an unknown block
            if s.block_hash and canon == s.block_hash.lower():
                # Still canonical.
                if s.status == SettlementStatus.pending and s.block_number <= final_head:
                    await _finalize_settlement(db, s, chain_id)
                    finalized += 1
            else:
                # Stored hash no longer matches the canonical block → reorged out.
                await _reverse_settlement(db, s)
                reorged += 1

        await db.commit()

    return {"finalized": finalized, "reorged": reorged}


# ── Per-chain watcher ────────────────────────────────────────
class PaymentWatcher:
    """Watches RSendsRouter.PaymentMade on a single chain via eth_getLogs."""

    def __init__(self, chain_id: int, router_address: str) -> None:
        self.chain_id = chain_id
        self.router_address = router_address.lower()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "[indexer] watching RSendsRouter %s on chain %d",
            self.router_address, self.chain_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[indexer] stopped chain %d", self.chain_id)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[indexer] tick failed (chain=%d): %s", self.chain_id, exc)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> dict:
        from app.services.rpc_manager import get_rpc_manager

        settings = get_settings()
        rpc = get_rpc_manager(self.chain_id)
        latest = int(await rpc.call("eth_blockNumber", []), 16)
        final_head = await _finalized_head(rpc, settings, latest)

        last = await _get_last_block(self.chain_id)
        if last is None:
            # First run — start from the final head (don't replay all history).
            # Override via settings.indexer_start_blocks[chain_id] if backfilling.
            start_blocks = getattr(settings, "indexer_start_blocks", {}) or {}
            start = int(start_blocks.get(str(self.chain_id), max(final_head, 0)))
            await _set_last_block(self.chain_id, start)
            logger.info("[indexer] chain %d initialized at block %d", self.chain_id, start)
            return {"processed": 0}

        # ── INGEST ── Scan up to `latest` (logs are recorded PENDING, never paid
        # here). Always re-scan the *unfinalized* tail (down to final_head+1) so a
        # reorg's re-inclusion / disappearance is observed; this re-scan is cheap
        # and idempotent (dedupe by chain+tx+logIndex+block_hash).
        processed = 0
        start_block = min(last + 1, final_head + 1)
        if start_block <= latest:
            end_block = min(latest, start_block + MAX_BLOCKS_PER_TICK - 1)
            # Providers cap the getLogs range (Alchemy free tier: 10 blocks on
            # Base Sepolia) — scan the window in chunks the provider accepts.
            # The cursor advances PER CHUNK, so a mid-window failure keeps the
            # completed chunks and the next tick resumes at the exact failure
            # point instead of retrying the same oversized range forever.
            max_range = max(
                1, int(getattr(settings, "indexer_getlogs_max_range", 10))
            )
            chunk_start = start_block
            while chunk_start <= end_block:
                chunk_end = min(end_block, chunk_start + max_range - 1)
                logs = await rpc.call(
                    "eth_getLogs",
                    [{
                        "fromBlock": hex(chunk_start),
                        "toBlock": hex(chunk_end),
                        "address": self.router_address,
                        "topics": [PAYMENT_MADE_TOPIC],
                    }],
                ) or []

                for log in logs:
                    # Source authenticity (defence-in-depth on the address filter
                    # above): only trust logs emitted by THIS chain's RSendsRouter.
                    if (log.get("address") or "").lower() != self.router_address:
                        logger.warning(
                            "[indexer] dropping PaymentMade from non-router address %s (chain=%d)",
                            log.get("address"), self.chain_id,
                        )
                        continue
                    ev = _decode_payment_made(log)
                    if ev is None:
                        continue
                    try:
                        action = await _record_settlement(self.chain_id, ev)
                        if action == "new":
                            processed += 1
                            logger.info(
                                "[indexer] PaymentMade invoiceId=%s amount=%s tx=%s (pending)",
                                ev["invoice_id"][:18], ev["amount"], ev["tx_hash"][:16],
                            )
                    except Exception:
                        logger.exception(
                            "[indexer] failed to ingest settlement tx=%s", ev["tx_hash"][:16]
                        )
                await _set_last_block(self.chain_id, chunk_end)
                chunk_start = chunk_end + 1

        # ── FINALIZE / RECONCILE ── Promote canonical+final rows to paid, reverse
        # reorged ones. This is where invoices are marked paid and webhooks fire.
        recon = await _finalize_and_reconcile(self.chain_id, rpc, final_head)

        return {"processed": processed, "final_head": final_head, **recon}


# ── Module-level lifecycle (used by app lifespan) ────────────
_watchers: list[PaymentWatcher] = []


async def start_indexer_if_needed() -> list[PaymentWatcher]:
    """Start one PaymentWatcher per configured chain.

    No-op (returns []) when no RSendsRouter addresses are configured — keeps
    dev/test boot clean exactly like the old poller did without a webhook secret.
    """
    global _watchers
    if _watchers:
        return _watchers

    settings = get_settings()
    routers = getattr(settings, "rsends_router_addresses", {}) or {}
    if not routers:
        logger.info("[indexer] no RSENDS_ROUTER addresses configured — indexer disabled")
        return []

    for chain_id_str, addr in routers.items():
        if not addr:
            continue
        try:
            chain_id = int(chain_id_str)
        except (TypeError, ValueError):
            logger.warning("[indexer] bad chain id in config: %r", chain_id_str)
            continue
        watcher = PaymentWatcher(chain_id=chain_id, router_address=addr)
        await watcher.start()
        _watchers.append(watcher)

    return _watchers


async def stop_indexer() -> None:
    global _watchers
    for w in _watchers:
        await w.stop()
    _watchers = []
