"""TRON matching — one settlement, one intent, and the invoice closes.

Phase 1, slice 3. The poller records TRON settlements with `intent_id = NULL`
and draws no conclusion from them. This module draws the conclusion: it matches
a recorded settlement to exactly one pending intent, closes that intent, and
fires the webhook that already exists.

It runs as a SEPARATE step in the poller's tick, after the settlement rows are
written and after the cursor is advanced, wrapped so that no failure here can
prevent a settlement from being recorded or hold the cursor. A matching bug
must never cost us the observation.

────────────────────────────────────────────────────────────────────────
WHY THIS IS A NEW MATCHER AND NOT THE OLD ONE
────────────────────────────────────────────────────────────────────────

`webhook_service.match_transaction_to_intent` and `finalize_match` are dead
custodial-era code with zero callers repo-wide, and they stay dead. Three
reasons, each checkable:

  - Their candidate query lowercases the recipient, and the code says so
    itself: "EVM-only: .lower() corrupts a base58check address (base58 has no
    0 O I l), so this matches zero rows for a TRON recipient. Do NOT wire for
    watch-only" (`webhook_service.py:717-720`).
  - The scorer bands on a FLOAT ratio with a 1% tolerance
    (`webhook_service.py:749-768`), over `PaymentIntent.amount`, which is a
    `Float` column. Base units and exact integers are available; a tolerance
    band is a way to be wrong quietly.
  - Its own docstring names the tie bug it inherited ("Bug 2 — Tie a pari
    score → status 'ambiguous', non FIFO"), and the legacy sibling it replaced
    still resolves ties by whichever row the database happened to return first.

────────────────────────────────────────────────────────────────────────
THE RULE
────────────────────────────────────────────────────────────────────────

A settlement matches an intent when ALL of these hold:

    chain is tron · intent is pending · recipient == merchant (EXACT, case
    sensitive) · token is the registry USDT · environments agree · the
    settlement's block_timestamp is inside [created_at, expires_at]

**Amount is deliberately NOT a match criterion.** Matching on it would make an
underpayment unmatchable, and an unmatched underpayment is a payment that
silently disappears — the money is already at the merchant on TRON, with no
router and no escrow to bounce it. Amount is checked AFTER a unique match, and
decides only how the intent closes.

Zero candidates is normal: a transfer to a merchant's address that belongs to
no invoice. More than one is refused outright — this module never picks a
winner, because picking wrong credits one merchant's payment to another
merchant's invoice.

NO PARTIAL ACCUMULATION. Two underpayments summing to the invoice do not close
it in this slice: the first moves the intent to `partial`, and the second finds
no `pending` candidate. Accumulation is deliberately out of scope.

EXPIRED INTENTS ARE NOT MATCHED, and that is a DIVERGENCE from the EVM path,
which treats `expired` as payable ("money on-chain wins over the timer",
`payment_indexer.py:826-832`). Here an intent that expires between payment and
matching gets zero candidates forever: the settlement stays unmatched and
nothing in the product says so. The settlement hold cannot prevent it either,
because that hold keys on `intent_id`, which is NULL until this module runs.
Recorded as a known follow-up in CLAUDE.md.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update

from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.services.chain_access import is_testnet_chain
from app.services.payment_indexer import _finalize_settlement
from app.services.router_registry import to_base_units, token_for
from app.services.tron_poller import TRON_CHAIN_ID

logger = logging.getLogger("tron_matcher")

TRON_CURRENCY = "USDT"


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _tron_environment() -> str:
    """"test" or "live" for a TRON settlement.

    Derived, not hardcoded. `is_testnet_chain` is fail-closed — any chain id it
    does not know is mainnet — and TRON's 728126428 is deliberately in none of
    its tables, so this resolves to "live", which is also the only environment
    a TRON intent can have (`intent_service._MAINNET_CHAINS`).
    """
    return "test" if is_testnet_chain(TRON_CHAIN_ID) else "live"


def _token_units(base_units: int, decimals: int) -> str:
    """Base units rendered in TOKEN units, as a decimal string.

    `_build_payload` emits `"amount": str(intent.amount)` in token units, and
    `amount_received` / `overpaid_amount` / `underpaid_amount` sit directly
    beside it in the same payload. Writing base units into those columns would
    have merchants comparing "10.0" against "10000000".

    `Decimal` throughout — never float — and `:f` so a large or small value can
    never come out in scientific notation.
    """
    return f"{Decimal(base_units) / (Decimal(10) ** decimals):f}"


async def _fire_once(db, settlement, intent, event: str, extra: dict) -> bool:
    """Dispatch `event` for this settlement at most once, ever.

    The same atomic claim `_fire_completed_webhook` uses: only the caller that
    flips `webhook_fired_at` NULL→now sends, so a re-run cannot double-fire. On
    dispatch failure the claim is RELEASED and `redrive_tron_webhooks` retries —
    the EVM redrive sweep is chain-scoped and would never see a TRON row.
    """
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
        return False
    settlement.webhook_fired_at = now

    try:
        from app.services.webhook_service import send_webhook

        await send_webhook(
            db,
            merchant_id=intent.merchant_id,
            event=event,
            intent=intent,
            extra_payload=extra,
        )
        return True
    except Exception:
        await db.execute(
            update(PaymentSettlement)
            .where(PaymentSettlement.id == settlement.id)
            .values(webhook_fired_at=None)
        )
        settlement.webhook_fired_at = None
        logger.exception(
            "[tron-matcher] %s dispatch failed for intent %s — claim released, "
            "the redrive will retry", event, intent.intent_id,
        )
        return False


# ═══════════════════════════════════════════════════════════════
#  The matcher
# ═══════════════════════════════════════════════════════════════

async def _candidates(db, settlement, environment: str) -> list:
    """Every pending TRON intent this settlement could be paying.

    `PaymentIntent.recipient == settlement.merchant` is an EXACT comparison
    with no folding on either side — `=` is case-sensitive on both Postgres and
    SQLite, and a base58check address differing in case is a different address.

    The window is closed on both ends: a transfer that predates the invoice
    cannot be paying it, and one that arrives after it expired is what the
    expiry timer exists to refuse.
    """
    return (await db.execute(
        select(PaymentIntent)
        .where(
            func.lower(PaymentIntent.chain) == "tron",
            PaymentIntent.status == IntentStatus.pending,
            PaymentIntent.recipient == settlement.merchant,
            PaymentIntent.environment == environment,
            PaymentIntent.created_at <= settlement.block_timestamp,
            PaymentIntent.expires_at >= settlement.block_timestamp,
        )
        .order_by(PaymentIntent.created_at, PaymentIntent.intent_id)
    )).scalars().all()


async def _record_ambiguous(db, settlement, candidates: list) -> None:
    """Refuse to choose, say so loudly, and tell the merchant.

    The settlement is marked `rejected` — the one terminal status that
    deliberately does NOT hold an intent (`intent_service.SETTLEMENT_HOLD_STATUSES`),
    so an ambiguous payment cannot freeze several invoices out of expiry and
    cancellation. `intent_id` stays NULL: no intent is chosen, touched, or
    implied.

    The payload is built from the earliest candidate because `_build_payload`
    needs an intent to describe. That intent is REPRESENTATIVE, not selected —
    the full candidate list rides in the extras, and nothing about it changes.
    """
    ids = [c.intent_id for c in candidates]
    settlement.status = SettlementStatus.rejected
    logger.error(
        "[tron-matcher] AMBIGUOUS settlement tx=%s (%s to %s) matches %d pending "
        "intents %s — refusing to choose; no intent was touched and the "
        "settlement is marked rejected",
        settlement.tx_hash, settlement.amount, settlement.merchant,
        len(ids), ids,
    )
    await db.flush()
    await _fire_once(
        db, settlement, candidates[0], "payment.ambiguous",
        {
            "tx_hash": settlement.tx_hash,
            "settlement": "onchain",
            "candidate_intent_ids": ids,
        },
    )


async def _close_partial(db, settlement, intent, received: int, expected: int,
                         decimals: int) -> None:
    """An underpayment: record it, do NOT reject it, do NOT mark it paid.

    This is the branch that cannot reuse `_finalize_settlement`: its validator
    fails `amount < expected` (`payment_indexer.py:485`), and that failure path
    marks the settlement `rejected` and leaves the intent untouched — which on
    TRON means a real payment, already sitting in the merchant's wallet,
    vanishes from the merchant's view. So the close is done here; the atomic
    webhook claim is still the shared one.

    The settlement becomes `final` and the intent becomes `partial`. `final`
    describes the SETTLEMENT — observed, canonical, fully processed — not the
    invoice, whose own status says plainly that it is not satisfied.
    """
    now = datetime.now(timezone.utc)
    intent.underpaid_amount = _token_units(expected - received, decimals)
    settlement.intent_id = intent.intent_id
    settlement.status = SettlementStatus.final
    settlement.finalized_at = now
    intent.status = IntentStatus.partial
    intent.matched_tx_hash = settlement.tx_hash
    intent.matched_at = now
    # Deliberately NOT completed_at: it is not completed.
    await db.flush()

    logger.warning(
        "[tron-matcher] UNDERPAID intent %s: received %s of %s base units "
        "(tx=%s) — intent marked partial, payment recorded",
        intent.intent_id, received, expected, settlement.tx_hash,
    )
    await _fire_once(
        db, settlement, intent, "payment.partial",
        {"tx_hash": settlement.tx_hash, "settlement": "onchain"},
    )


async def _match_one(db, settlement) -> str:
    """Match and close a single settlement. Returns the outcome bucket."""
    token = token_for("tron", TRON_CURRENCY)
    if token is None:  # registry gone — refuse rather than guess
        logger.error("[tron-matcher] no registry entry for (tron, USDT)")
        return "unmatched"
    token_address, decimals = token

    if settlement.token != token_address:
        return "unmatched"
    if settlement.block_timestamp is None:
        # Without a timestamp the validity window is unanswerable. Fail closed.
        logger.error(
            "[tron-matcher] settlement tx=%s has no block_timestamp; cannot "
            "apply the intent validity window", settlement.tx_hash,
        )
        return "unmatched"

    candidates = await _candidates(db, settlement, _tron_environment())
    if not candidates:
        return "unmatched"
    if len(candidates) > 1:
        await _record_ambiguous(db, settlement, candidates)
        return "ambiguous"

    intent = candidates[0]
    expected = to_base_units(intent.amount, decimals)
    received = int(settlement.amount)

    # Written before finalization: `_finalize_settlement` flushes and then
    # fires, so the payload picks these up.
    intent.amount_received = _token_units(received, decimals)

    if received < expected:
        await _close_partial(db, settlement, intent, received, expected, decimals)
        return "partial"

    if received > expected:
        intent.overpaid_amount = _token_units(received - expected, decimals)
        logger.info(
            "[tron-matcher] OVERPAID intent %s by %s base units — invoice "
            "satisfied, excess recorded", intent.intent_id, received - expected,
        )

    settlement.intent_id = intent.intent_id
    # Reused unchanged: it pays the intent, stamps the row final and fires
    # payment.completed through its own atomic claim. Its `chain_id` parameter
    # is unused in its body; TRON_CHAIN_ID is passed for honesty.
    await _finalize_settlement(db, settlement, TRON_CHAIN_ID)
    return "matched"


async def match_pending_tron_settlements() -> dict:
    """Match every unmatched TRON settlement. One session per settlement.

    The selection — TRON chain, `intent_id IS NULL`, still `pending` — is what
    makes three properties structural rather than checked: an EVM settlement is
    never considered, an already-matched one is never re-matched, and one
    already refused as ambiguous (now `rejected`) is not retried blindly.
    """
    from app.db.session import async_session

    async with async_session() as db:
        ids = (await db.execute(
            select(PaymentSettlement.id)
            .where(
                PaymentSettlement.chain_id == TRON_CHAIN_ID,
                PaymentSettlement.intent_id.is_(None),
                PaymentSettlement.status == SettlementStatus.pending,
            )
            .order_by(PaymentSettlement.id)
        )).scalars().all()

    counts = {"matched": 0, "partial": 0, "ambiguous": 0, "unmatched": 0}
    for settlement_id in ids:
        # A session each: one settlement's failure must not roll back another's.
        async with async_session() as db:
            settlement = await db.get(PaymentSettlement, settlement_id)
            if settlement is None:
                continue
            try:
                outcome = await _match_one(db, settlement)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "[tron-matcher] failed to match settlement id=%s; it stays "
                    "unmatched and will be retried", settlement_id,
                )
                continue
        counts[outcome] += 1
    return counts


# ═══════════════════════════════════════════════════════════════
#  Redrive
# ═══════════════════════════════════════════════════════════════

async def redrive_tron_webhooks() -> int:
    """Re-fire settlement webhooks whose dispatch failed. Returns how many.

    `_fire_once` (and `_fire_completed_webhook`) release the claim when dispatch
    raises, on the assumption that a sweep retries it. The EVM sweep
    (`payment_indexer.py:1108-1127`) is `chain_id == chain_id` scoped inside a
    watcher that never runs for TRON, so without this a paid merchant would
    simply never be told. Runs every tick; a paid merchant MUST eventually hear.
    """
    from app.db.session import async_session

    fired = 0
    async with async_session() as db:
        rows = (await db.execute(
            select(PaymentSettlement, PaymentIntent)
            .join(PaymentIntent,
                  PaymentIntent.intent_id == PaymentSettlement.intent_id)
            .where(
                PaymentSettlement.chain_id == TRON_CHAIN_ID,
                PaymentSettlement.status == SettlementStatus.final,
                PaymentSettlement.webhook_fired_at.is_(None),
                PaymentSettlement.reversal_fired_at.is_(None),
                PaymentIntent.status.in_(
                    (IntentStatus.paid, IntentStatus.partial)
                ),
                PaymentIntent.matched_tx_hash == PaymentSettlement.tx_hash,
            )
        )).all()

        for settlement, intent in rows:
            event = ("payment.completed" if intent.status == IntentStatus.paid
                     else "payment.partial")
            if await _fire_once(
                db, settlement, intent, event,
                {"tx_hash": settlement.tx_hash, "settlement": "onchain"},
            ):
                fired += 1
        await db.commit()

    if fired:
        logger.info("[tron-matcher] redrove %d undelivered webhook(s)", fired)
    return fired
