"""One wallet, one tick: lock, preflight, send, confirm, release.

The ordering here is the whole safety argument, so it is worth stating plainly:

  backed off?  →  lock  →  preflight  →  send  →  confirm at the receipt block

The lock is taken BEFORE the preflight and held ACROSS the send, and it is
released on every path including failure. `webhook_service.py` records a Redis
pre-claim being *removed* because it outlived the rollback it was guarding — a
claim that survives a failed send would suppress retries until its TTL while the
money had not moved. A Redis claim is never the record of an on-chain fact.
"""

import logging
from dataclasses import dataclass

from keeper.preflight import (
    SKIP_SELF_RECIPIENT,
    RpcUnavailable,
    preflight,
)

log = logging.getLogger(__name__)

OUTCOME_EXECUTED = "executed"
OUTCOME_SKIPPED = "skipped"
OUTCOME_LOCKED_OUT = "locked_out"
OUTCOME_FAILED = "failed"
OUTCOME_BACKED_OFF = "backed_off"


@dataclass(frozen=True)
class Outcome:
    kind: str
    reason: str = ""
    detail: str = ""


def process_wallet(wallet, *, chain, executor, state) -> Outcome:
    if state.is_backed_off(wallet):
        return Outcome(OUTCOME_BACKED_OFF)

    handle = state.acquire(wallet)
    if handle is None:
        # Another tick (or another instance) already has this wallet. Not an
        # error and not a failure — say so and let it work.
        log.debug("keeper: wallet %s is locked by another tick", wallet.id)
        return Outcome(OUTCOME_LOCKED_OUT)

    try:
        decision = preflight(chain, wallet)

        if not decision.execute:
            if decision.reason == SKIP_SELF_RECIPIENT:
                # Not a routine skip: this policy erodes the merchant's share a
                # little on every tick that a keeper WOULD have run, and it can
                # only be fixed by the merchant re-registering the policy.
                log.critical(
                    "KEEPER_SELF_RECIPIENT_POLICY wallet=%s org=%s chain=%s token=%s "
                    "— %s",
                    wallet.id,
                    wallet.org_id,
                    wallet.chain,
                    wallet.token_symbol,
                    decision.detail,
                )
            else:
                log.info(
                    "keeper: skipping wallet=%s reason=%s %s",
                    wallet.id,
                    decision.reason,
                    decision.detail,
                )
            # A skip is the normal state of an idle wallet, NOT a failure. If
            # skips counted, every quiet wallet would back itself off.
            return Outcome(OUTCOME_SKIPPED, decision.reason, decision.detail)

        receipt = executor.execute_split(wallet)

        # A returned transaction hash is not success. status == 0 means the
        # transaction mined and reverted — the gas is spent and nothing moved.
        if getattr(receipt, "status", 1) != 1:
            reason = f"executeSplit reverted on chain (block {receipt.blockNumber})"
            state.record_failure(wallet, reason)
            return Outcome(OUTCOME_FAILED, reason)

        block = receipt.blockNumber

        # Confirm at the RECEIPT's block, never at "latest". A load-balanced
        # provider can answer "latest" from a replica behind the block that
        # included this transaction — observed three times in manual testing. A
        # node that has the receipt has the block, so this is consistent by
        # construction rather than a retry loop hoping to outlast the lag.
        residual = chain.balance_of(wallet, block_identifier=block)
        log.info(
            "keeper: executed wallet=%s org=%s total=%s block=%s residual_balance=%s",
            wallet.id,
            wallet.org_id,
            decision.total,
            block,
            residual,
        )

        state.record_success(wallet, block)
        return Outcome(OUTCOME_EXECUTED)

    except RpcUnavailable as exc:
        # The chain was reachable enough to start and not to finish. Retry next
        # tick; do not conclude anything about the merchant's state.
        state.record_failure(wallet, f"rpc unavailable: {exc}")
        return Outcome(OUTCOME_FAILED, "rpc_unavailable", str(exc))
    except Exception as exc:  # noqa: BLE001 — a tick must not kill the loop
        state.record_failure(wallet, str(exc))
        return Outcome(OUTCOME_FAILED, type(exc).__name__, str(exc))
    finally:
        state.release(handle)
