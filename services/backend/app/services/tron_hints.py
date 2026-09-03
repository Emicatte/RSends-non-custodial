"""Acting on a submitted hash: one implementation, two callers.

The endpoint runs this once, immediately, so a payer who submits a hash that has
already solidified sees their invoice close without waiting for a tick. The
poller runs it every tick for everything still undecided. Both go through
`apply_result`, because a hint that the endpoint verifies and a hint the tick
verifies must leave the database in the same state.

WHY THE PASS HAS TWO QUERIES, NOT ONE.

The fetch loop only looks at hints whose intent is still payable — asking a node
about an invoice that has already been paid or cancelled is work with no
possible consequence. But that filter would also hide every hint whose intent
has since expired, which is exactly the population the give-up rule exists to
clear: those rows would sit in `pending` forever, costing nothing but claiming
something untrue.

So the give-up sweep runs first and does not filter on intent status, and the
fetch loop runs second and does. A hint being abandoned is never fetched, which
is why the give-up test can assert zero node calls.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from sqlalchemy import func, select

from app.models.merchant_models import IntentStatus, PaymentIntent
from app.models.tron_hint_models import HintState, TronPaymentHint
from app.services import tron_poller as tp
from app.services.tron_verifier import (
    Pending,
    Rejected,
    TronSource,
    Verified,
    VerifyResult,
    PollerSource,
    verify_transfer,
)

logger = logging.getLogger("tron_hints")

#: How long past `expires_at` a hint is still worth asking about.
#:
#: Solidification takes about a minute, so this is not a wait for the chain. It
#: is that an expired intent drops out of the poller's address scan, which
#: filters `status == pending` — so abandoning its hint is the moment that
#: payment becomes invisible again, and that is the gap the hint exists to
#: close. A long TronGrid outage must not cost a real payment its only record.
LATE_PAYMENT_WINDOW = timedelta(hours=24)

#: A bounded amount of node work per tick, so a backlog cannot starve the
#: observation pass that shares the same TronGrid quota.
MAX_HINTS_PER_PASS = 20

#: Intents a hint can still do something for.
PAYABLE = (IntentStatus.pending, IntentStatus.partial)


def _source_for_network(network: tp.TronNetwork) -> Optional[TronSource]:
    poller = tp.poller_for_chain(network.chain_name)
    return PollerSource(poller) if poller else None


async def apply_result(
    network: tp.TronNetwork, hint_id: int, result: VerifyResult
) -> None:
    """Write a verdict to the hint row, and settle when it is Verified.

    Settlement goes through `tron_poller._record_settlement` — the same writer
    the address scan uses, with the same `(chain_id, tx_hash, log_index)`
    idempotency. It is called BEFORE the hint row is touched, because it opens
    its own session and commits, and holding a write transaction across that is
    how SQLite and Postgres both find something to complain about.
    """
    from app.db.session import async_session

    now = datetime.now(timezone.utc)

    if isinstance(result, Verified):
        transfer, event = result.settlement_input
        await tp._record_settlement(transfer, event, network)

    async with async_session() as db:
        hint = await db.get(TronPaymentHint, hint_id)
        if hint is None:  # pragma: no cover - deleted mid-pass
            return
        hint.last_checked_at = now
        if isinstance(result, Verified):
            hint.state = HintState.verified
            hint.verified_at = now
        elif isinstance(result, Rejected):
            hint.state = HintState.rejected
            hint.rejection_reason = result.reason
        # Pending: nothing but `last_checked_at`, so a stuck hint is visible.
        await db.commit()

    if isinstance(result, Verified):
        # Recording a settlement is not closing an invoice. The matcher decides
        # that, with the same rules it applies to a scanned transfer.
        await tp._run_matching_pass(network)


async def verify_hint(
    network: tp.TronNetwork,
    *,
    tx_hash: str,
    payer_address: Optional[str],
    intent,
    source: Optional[TronSource] = None,
) -> VerifyResult:
    """One verification, with the node source resolved if not supplied."""
    if source is None:
        source = _source_for_network(network)
        if source is None:
            # Nothing proven is running; not the transaction's fault.
            return Pending("no_proven_node")
    return await verify_transfer(
        network, tx_hash, intent, payer_address, source=source
    )


async def _give_up_on_stale_hints(network: tp.TronNetwork, now: datetime) -> int:
    """Close out hints for intents nobody can pay any more. No node calls.

    Deliberately NOT filtered on intent status: the whole point is to reach the
    rows the fetch loop's payable filter hides.
    """
    from app.db.session import async_session

    cutoff = now - LATE_PAYMENT_WINDOW
    async with async_session() as db:
        rows = (await db.execute(
            select(TronPaymentHint)
            .join(PaymentIntent, PaymentIntent.id == TronPaymentHint.intent_id)
            .where(
                TronPaymentHint.state == HintState.pending,
                func.lower(PaymentIntent.chain) == network.chain_name,
                PaymentIntent.expires_at < cutoff,
            )
        )).scalars().all()
        for hint in rows:
            hint.state = HintState.rejected
            hint.rejection_reason = "not_found"
            hint.last_checked_at = now
        if rows:
            await db.commit()
    return len(rows)


async def run_hint_pass(
    network: tp.TronNetwork,
    *,
    source_for: Optional[Callable[[object], TronSource]] = None,
) -> dict:
    """One pass over this network's undecided hints. Never raises.

    `source_for` is a test seam: given the hint, return the node source to read
    through. Production passes nothing and reads through the running poller.
    """
    now = datetime.now(timezone.utc)
    counts = {"given_up": 0, "verified": 0, "rejected": 0, "still_pending": 0}

    counts["given_up"] = await _give_up_on_stale_hints(network, now)

    from app.db.session import async_session

    async with async_session() as db:
        rows = (await db.execute(
            select(TronPaymentHint, PaymentIntent)
            .join(PaymentIntent, PaymentIntent.id == TronPaymentHint.intent_id)
            .where(
                TronPaymentHint.state == HintState.pending,
                # The intent state belongs IN the query. Checking it after a
                # fetch would still have spent the node call.
                PaymentIntent.status.in_(PAYABLE),
                func.lower(PaymentIntent.chain) == network.chain_name,
            )
            .order_by(TronPaymentHint.id)
            .limit(MAX_HINTS_PER_PASS)
        )).all()
        # Snapshot before the session closes: each hint is then processed in its
        # own session, so one failure cannot roll back another's verdict.
        work = [
            (hint.id, hint.tx_hash, hint.payer_address, intent)
            for hint, intent in rows
        ]
        for _, _, _, intent in work:
            db.expunge(intent)

    for hint_id, tx_hash, payer_address, intent in work:
        try:
            result = await verify_hint(
                network,
                tx_hash=tx_hash,
                payer_address=payer_address,
                intent=intent,
                source=source_for(hint_id) if source_for else None,
            )
            await apply_result(network, hint_id, result)
            if isinstance(result, Verified):
                counts["verified"] += 1
            elif isinstance(result, Rejected):
                counts["rejected"] += 1
            else:
                counts["still_pending"] += 1
        except Exception:
            logger.exception(
                "[tron-hints] %s: hint %s failed to verify; it stays pending "
                "and the address scan is unaffected",
                network.chain_name, hint_id,
            )
    return counts
