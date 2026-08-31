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

**Amount is deliberately NOT a SELECTION criterion.** Selecting on it would make
an underpayment unmatchable, and an unmatched underpayment is a payment that
silently disappears — the money is already at the merchant on TRON, with no
router and no escrow to bounce it. A LONE candidate is therefore never filtered
by amount; amount is read afterwards and decides only how that intent closes.

Amount IS the tiebreak among SEVERAL candidates, and only there. Two open
invoices on one address is an ordinary merchant state, and refusing a
settlement when exactly one of those invoices asks for the amount that arrived
strands real money at the merchant that nothing will ever reconcile. So with
more than one candidate, base units are compared exactly (no tolerance):

  - exactly one candidate matches exactly → it wins, and closes as it would
    have if it had been alone
  - zero match exactly → AMBIGUOUS. A partial payment against several open
    invoices belongs to none of them provably.
  - more than one matches exactly → AMBIGUOUS. Two invoices for the same amount
    are indistinguishable by the only evidence a settlement carries.

Zero candidates is normal: a transfer to a merchant's address that belongs to
no invoice. Ambiguity picks nothing — this module never picks a winner it
cannot prove, because picking wrong credits one merchant's payment to another
merchant's invoice.

AMBIGUITY IS UNRESOLVED, NOT REFUSED. The settlement is left `pending` with
`intent_id` NULL — the state the scan below already selects — so every later
tick tries again. Ambiguity is temporary by construction: the competing
invoices expire on their own timers, and the tick on which exactly one remains
closes a payment that has been in the merchant's wallet the whole time.
Marking it `rejected` (the behaviour before this) orphaned that money for good,
because nothing in the system re-reads a rejected settlement. Leaving it
`pending` holds no invoice hostage either: the settlement hold correlates on
`intent_id` (`intent_service.settlement_hold_exists`), which is NULL here.

`rejected` therefore means EXACTLY ONE thing now — the event did not validate
against its intent — and such a row must never be re-attempted. It is not: the
scan requires `pending` AND `intent_id IS NULL`, and a validation rejection
fails both. Ambiguity and invalidity are no longer the same state, so nothing
on the row has to tell them apart.

A settlement that stays ambiguous until every candidate expires simply stays
`pending` forever with zero candidates — the same resting state as any TRON
transfer that belongs to no invoice.

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
from typing import Optional

from sqlalchemy import func, select, update

from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.settlement_models import PaymentSettlement, SettlementStatus
from app.services.chain_access import is_watch_only_testnet
from app.services.payment_indexer import _finalize_settlement
from app.services.router_registry import from_base_units, to_base_units, token_for
from app.services.tron_poller import TronNetwork

logger = logging.getLogger("tron_matcher")

TRON_CURRENCY = "USDT"


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _tron_environment(network: TronNetwork) -> str:
    """"test" or "live" for a settlement on `network`.

    Derived, not hardcoded — but from the chain NAME, not the chain id. The
    id-keyed `is_testnet_chain` cannot answer here: neither TRON chain id is in
    its EVM table and it is fail-closed to mainnet, which is the right answer
    for TRON mainnet and the wrong one for Nile. `is_watch_only_testnet` is the
    name-keyed arm, and is fail-closed the same way: a network nobody listed
    there stamps "live".

    This stamp scopes the intent search below AND the outbound webhook, so
    getting it wrong does not error — it just never matches anything.
    """
    return "test" if is_watch_only_testnet(network.chain_name) else "live"


def _token_units(base_units: int, decimals: int) -> str:
    """Base units rendered in TOKEN units, as a decimal string.

    `_build_payload` emits `"amount": str(intent.amount)` in token units, and
    `amount_received` / `overpaid_amount` / `underpaid_amount` sit directly
    beside it in the same payload. Writing base units into those columns would
    have merchants comparing "10.0" against "10000000".

    `Decimal` throughout — never float — and `:f` so a large or small value can
    never come out in scientific notation. The formatter itself lives beside
    its inverse in `router_registry`, so the public checkout view renders the
    exact same decimal this matcher writes.
    """
    return from_base_units(base_units, decimals)


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

async def _candidates(db, settlement, environment: str, network: TronNetwork) -> list:
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
            func.lower(PaymentIntent.chain) == network.chain_name,
            PaymentIntent.status == IntentStatus.pending,
            PaymentIntent.recipient == settlement.merchant,
            PaymentIntent.environment == environment,
            PaymentIntent.created_at <= settlement.block_timestamp,
            PaymentIntent.expires_at >= settlement.block_timestamp,
        )
        .order_by(PaymentIntent.created_at, PaymentIntent.intent_id)
    )).scalars().all()


def _sole_exact_match(candidates: list, received: int, decimals: int):
    """The one candidate asking for EXACTLY what arrived, or None.

    Consulted ONLY when there is more than one candidate — it is a tiebreak,
    never a filter. Comparison is exact integers in base units, no tolerance,
    the same arithmetic the close below already does.

    Two outcomes decline to choose, both on purpose:

      - ZERO exact matches. The transfer is a partial payment against several
        open invoices; it belongs to none of them provably, and attributing it
        would mark one invoice `partial` on nothing but proximity.
      - MORE THAN ONE. Two invoices for the same amount are indistinguishable
        by amount, which is the only evidence this settlement carries.
    """
    exact = [c for c in candidates
             if to_base_units(c.amount, decimals) == received]
    return exact[0] if len(exact) == 1 else None


# Which candidate set we have already ANNOUNCED at ERROR, per settlement id.
#
# Derived state, deliberately not a column. An unresolved ambiguity is now
# re-attempted on every 60s tick, and an operator does not need the same
# sentence every 60s until an invoice expires — but they DO need it again if
# the field of candidates changes, because that is new information.
#
# Consequences, all accepted: it is per-process, so each worker announces once
# and a restart announces once more; and it is memory, so entries are dropped
# the moment a settlement stops being ambiguous (below). Nothing depends on it
# for correctness — worst case is a duplicate log line.
_ANNOUNCED_AMBIGUITY: dict[int, tuple] = {}


async def _record_ambiguous(db, settlement, candidates: list) -> None:
    """Choose nothing, say so once, and leave the settlement RETRYABLE.

    Reached only AFTER `_sole_exact_match` declined: either no candidate asks
    for the amount that arrived, or several do. What is left is not a tie the
    matcher is too timid to break — it is a tie with no evidence in it.

    THE ROW IS NOT MUTATED. It stays `pending` with `intent_id` NULL, which is
    exactly what `match_pending_tron_settlements` scans, so the next tick tries
    again for free. That matters because ambiguity is TEMPORARY: the competing
    invoices expire on their own timers, and the tick on which only one is left
    reconciles a payment that is already sitting in the merchant's wallet.
    Marking it `rejected` — the old behaviour — orphaned that money forever,
    because nothing anywhere re-reads a rejected settlement.

    Leaving it `pending` holds no intent. The hold correlates on `intent_id`
    (`intent_service.settlement_hold_exists`), which is NULL here, so `pending`
    freezes nothing and the competing invoices stay free to expire and to be
    cancelled — which is precisely the mechanism this retry depends on.

    `rejected` therefore now carries EXACTLY ONE meaning on this path: the
    event did not validate against its intent (`_finalize_settlement`). Such a
    row must never be re-attempted, and is not — the scan excludes it on both
    predicates. The old conflation of "unattributable" with "invalid" is gone,
    and with it the need for anything on the row to tell them apart.

    The payload is built from the earliest candidate because `_build_payload`
    needs an intent to describe. That intent is REPRESENTATIVE, not selected —
    the full candidate list rides in the extras, and nothing about it changes.
    """
    ids = [c.intent_id for c in candidates]

    if _ANNOUNCED_AMBIGUITY.get(settlement.id) == tuple(ids):
        logger.debug(
            "[tron-matcher] settlement tx=%s still ambiguous between %s — "
            "unchanged since the last tick, already announced",
            settlement.tx_hash, ids,
        )
    else:
        _ANNOUNCED_AMBIGUITY[settlement.id] = tuple(ids)
        logger.error(
            "[tron-matcher] AMBIGUOUS settlement tx=%s (%s to %s) matches %d "
            "pending intents %s and no single one of them asks for exactly that "
            "amount — choosing nothing; no intent was touched and the settlement "
            "stays pending, so it is re-attempted as the field narrows",
            settlement.tx_hash, settlement.amount, settlement.merchant,
            len(ids), ids,
        )

    # NOT `_fire_once`. That claims `webhook_fired_at` NULL→now for the whole
    # settlement, and releases it only when dispatch RAISES — so a merchant
    # with no registered endpoint (send_webhook returns 0, quietly) consumed
    # the claim too. The later, successful match then found the claim taken:
    # `_fire_completed_webhook` saw rowcount 0 and returned SILENTLY, and
    # neither redrive sweep could rescue it because both require
    # `webhook_fired_at IS NULL`. Intent paid, settlement final, merchant never
    # told. The claim belongs to the event that CLOSES the invoice; ambiguity
    # must not spend it.
    #
    # Idempotency instead comes from the delivery layer, which is durable and
    # already exists: `send_webhook` dedupes on
    # `{intent_id}:{event}:{webhook_id}` against `webhook_deliveries` (UNIQUE),
    # inside this same transaction. Re-firing every tick therefore notifies the
    # merchant exactly once — and re-announces only if the representative
    # candidate changes, which is a genuinely different ambiguity.
    from app.services.webhook_service import send_webhook

    await send_webhook(
        db,
        merchant_id=candidates[0].merchant_id,
        event="payment.ambiguous",
        intent=candidates[0],
        extra_payload={
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


async def _match_one(db, settlement, network: TronNetwork) -> str:
    """Match and close a single settlement. Returns the outcome bucket."""
    token = token_for(network.chain_name, TRON_CURRENCY)
    if token is None:  # registry gone — refuse rather than guess
        logger.error(
            "[tron-matcher] no registry entry for (%s, %s)",
            network.chain_name, TRON_CURRENCY,
        )
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

    candidates = await _candidates(
        db, settlement, _tron_environment(network), network
    )
    if not candidates:
        return "unmatched"

    received = int(settlement.amount)
    if len(candidates) > 1:
        # Amount is a TIEBREAK here and nowhere else. A lone candidate is never
        # filtered by it: doing that would make an underpayment unmatchable.
        chosen = _sole_exact_match(candidates, received, decimals)
        if chosen is None:
            await _record_ambiguous(db, settlement, candidates)
            return "ambiguous"
        candidates = [chosen]

    # Resolved: the ambiguity, if there ever was one, is over. Drop the
    # announcement memo so it cannot outlive the row it describes.
    _ANNOUNCED_AMBIGUITY.pop(settlement.id, None)

    intent = candidates[0]
    expected = to_base_units(intent.amount, decimals)

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
    # is unused in its body; the network's chain id is passed for honesty.
    await _finalize_settlement(db, settlement, network.chain_id)
    return "matched"


async def match_pending_tron_settlements(network: TronNetwork) -> dict:
    """Match every unmatched settlement ON `network`. One session per settlement.

    The selection — this network's chain id, `intent_id IS NULL`, still
    `pending` — is what makes four properties structural rather than checked: an
    EVM settlement is never considered, the OTHER TRON network's settlements are
    never considered, an already-matched one is never re-matched, and one
    `rejected` for failing validation against its intent is never re-attempted.

    Deliberately UNCHANGED by the ambiguity retry: an ambiguous settlement is
    retried because it still satisfies this scan, not because the scan was
    widened. Widening it is what would put a terminal row back in play.
    """
    from app.db.session import async_session

    async with async_session() as db:
        ids = (await db.execute(
            select(PaymentSettlement.id)
            .where(
                PaymentSettlement.chain_id == network.chain_id,
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
                outcome = await _match_one(db, settlement, network)
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

async def redrive_tron_webhooks(network: TronNetwork) -> int:
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
                PaymentSettlement.chain_id == network.chain_id,
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
        logger.info(
            "[tron-matcher/%s] redrove %d undelivered webhook(s)",
            network.key, fired,
        )
    return fired
