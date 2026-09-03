"""Is this transaction the payment this intent is waiting for?

The payer's browser tells us a hash. This module decides, on chain, whether that
hash is the transfer the intent expects — and it is deliberately the only part
of the hint pipeline that has no database in it. No hint table, no settlement
write, no matcher. It answers a question; callers decide what to do with the
answer.

THREE ANSWERS, AND THE DIFFERENCE MATTERS.

    Verified   this is the payment, and here is the (transfer, event) pair
               `tron_poller._record_settlement` already knows how to write
    Pending    ask again later
    Rejected   this hash is not that payment, and here is which check said so

`Pending` covers two situations that CANNOT be told apart from here: a
transaction that has not solidified yet, and a hash that does not exist at all.
`walletsolidity/gettransactioninfobyid` answers `{}` to both. Reporting either as
`Rejected` would be a guess, and the guess that costs money is the one that
declares a real payment fake seconds before it solidifies.

WHY THE SOLIDITY ENDPOINTS AND THE EVENTS ENDPOINT, BOTH.

The solidity node answers only for solidified transactions, which is what makes
it the finality check — the same standard `only_confirmed=true` gives the poller,
reached a different way. But its `log[]` array is a DIFFERENT INDEX SPACE from
`event_index`: `event_index` counts every VM event in the transaction, including
other contracts', while `log[]` is a receipt-local list. Deriving `log_index`
from a position in `log[]` would produce a different number for the same
transfer than the poller produces, and `uq_settlement_onchain_log
(chain_id, tx_hash, log_index)` would then admit BOTH as separate settlements:
one payment, booked twice.

So `log_index` comes from exactly one place, here as in the poller — the events
endpoint, paired by `_pair_transfer_to_event`. The receipt is read for
solidification and success and for nothing else.

WHAT THE CLIENT IS TRUSTED FOR: nothing. `submitted_payer` is compared against
the sender in the log and used only if it matches; it exists because the log
gives addresses in hex and a settlement row stores base58, and taking the base58
the chain already confirmed is better than adding a second base58 encoder whose
failure mode is crediting an address nobody controls. Recipient, amount, token
and network all come from the intent and the network descriptor.

REJECTING A HINT NEVER LOSES A PAYMENT. If this says `Rejected("wrong_amount")`
because the payer sent 2.4 on a 2.5 invoice, the transfer is still on chain and
the poller still records it on its own scan, where `tron_matcher._close_partial`
gives it the partial treatment it deserves. The hint is an accelerator. Refusing
to accelerate is always safe; accelerating the wrong thing is not.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Union

from app.security.input_validator import tron_address_to_evm_hex
from app.services.router_registry import to_base_units, token_for
from app.services.tron_poller import (
    TronEnrichmentError,
    TronNetwork,
    _pair_transfer_to_event,
    poller_for_chain,
)

logger = logging.getLogger("tron_verifier")

SOLIDITY_INFO_PATH = "/walletsolidity/gettransactioninfobyid"
SOLIDITY_TX_PATH = "/walletsolidity/gettransactionbyid"

#: Every reason this module may refuse a hash. Closed on purpose: a caller
#: storing one of these in a column, and a payer reading copy derived from it,
#: both need the set to be enumerable rather than free text.
REJECTION_REASONS = frozenset({
    "wrong_network",
    "reverted",
    "out_of_energy",
    "failed_other",
    "no_transfer_log",
    "wrong_contract",
    "wrong_recipient",
    "wrong_amount",
    "sender_mismatch",
    "unenrichable",
})

#: Receipt results that are not SUCCESS, mapped to their reason.
_FAILURE_REASONS = {"REVERT": "reverted", "OUT_OF_ENERGY": "out_of_energy"}


@dataclass(frozen=True)
class Verified:
    """The payment, with everything the settlement writer needs."""

    transfer: dict
    event: dict

    @property
    def settlement_input(self) -> tuple[dict, dict]:
        """Exactly the arguments `tron_poller._record_settlement` takes.

        Returned as a pair rather than a new shape so the hint path and the
        scan path write through one function. A second writer is how two rows
        for one payment start.
        """
        return self.transfer, self.event


@dataclass(frozen=True)
class Pending:
    """Not yet solidified, or no such transaction. Indistinguishable; both wait."""

    reason: str = "not_found_or_unsolidified"


@dataclass(frozen=True)
class Rejected:
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.reason not in REJECTION_REASONS:
            raise ValueError(f"{self.reason!r} is not a known rejection reason")


VerifyResult = Union[Verified, Pending, Rejected]


class TronSource(Protocol):
    """The three reads this module makes. Injectable so tests use fixtures."""

    async def transaction_info(self, tx_hash: str) -> dict: ...
    async def transaction(self, tx_hash: str) -> dict: ...
    async def events(self, tx_hash: str) -> list: ...


class PollerSource:
    """Reads through a running poller, and therefore through PROVEN nodes.

    Every node in that poller's list answered `getblockbynum 0` with the pinned
    genesis blockID at boot or the process exited. Borrowing the poller inherits
    that proof; dialling our own nodes would discard it, and a verifier reading
    an unproven node is a verifier that can be told anything.
    """

    def __init__(self, poller: Any) -> None:
        self._poller = poller

    async def transaction_info(self, tx_hash: str) -> dict:
        return await self._poller._post_json(SOLIDITY_INFO_PATH, {"value": tx_hash})

    async def transaction(self, tx_hash: str) -> dict:
        return await self._poller._post_json(SOLIDITY_TX_PATH, {"value": tx_hash})

    async def events(self, tx_hash: str) -> list:
        return await self._poller._fetch_events(tx_hash)


def _transfer_events(events: list) -> list:
    return [e for e in (events or []) if e.get("event_name") == "Transfer"]


def _result_of(event: dict) -> dict:
    return event.get("result") or {}


async def verify_transfer(
    network: TronNetwork,
    tx_hash: str,
    intent: Any,
    submitted_payer: Optional[str],
    *,
    source: Optional[TronSource] = None,
) -> VerifyResult:
    """Decide whether `tx_hash` is the transfer `intent` is waiting for.

    Checks run in a fixed order, and the order is the diagnosis: each one
    assumes its predecessors passed, so the reason that comes back names the
    first thing that was actually wrong rather than the last thing checked.
    """
    # 1. Network. A hash is only meaningful on the chain the intent lives on,
    #    and reading the wrong chain's node could match a lookalike transfer.
    if (getattr(intent, "chain", "") or "").lower() != network.chain_name:
        return Rejected(
            "wrong_network",
            f"intent is on {getattr(intent, 'chain', None)!r}, "
            f"asked to verify against {network.chain_name}",
        )

    if source is None:
        poller = poller_for_chain(network.chain_name)
        if poller is None:
            # Nothing proven is running, so nothing can be verified right now.
            # Not the transaction's fault, and not a reason to refuse it.
            return Pending("no_proven_node")
        source = PollerSource(poller)

    # 2. Solidification. The solidity node answers only for solidified
    #    transactions, so a body at all IS the finality proof.
    try:
        info = await source.transaction_info(tx_hash)
    except TronEnrichmentError as exc:
        return Pending(f"node unavailable: {exc}")
    if not info or info.get("blockNumber") is None:
        return Pending()

    # 3. Success. Note that `receipt.result` is ABSENT for a transaction with no
    #    VM execution — a plain TRX transfer has only `net_usage` — and absent
    #    is not failure. That case is a successful transaction which simply is
    #    not a TRC-20 transfer, and it is caught by the log check below, where
    #    the honest reason lives.
    receipt_result = (info.get("receipt") or {}).get("result")
    if receipt_result is not None and receipt_result != "SUCCESS":
        return Rejected(
            _FAILURE_REASONS.get(receipt_result, "failed_other"), str(receipt_result)
        )

    try:
        tx = await source.transaction(tx_hash)
    except TronEnrichmentError as exc:
        return Pending(f"node unavailable: {exc}")
    contract_ret = ((tx.get("ret") or [{}])[0] or {}).get("contractRet")
    if contract_ret is not None and contract_ret != "SUCCESS":
        return Rejected(
            _FAILURE_REASONS.get(contract_ret, "failed_other"), str(contract_ret)
        )

    try:
        events = await source.events(tx_hash)
    except TronEnrichmentError as exc:
        return Pending(f"node unavailable: {exc}")

    transfers = _transfer_events(events)
    if not transfers:
        return Rejected("no_transfer_log", "no Transfer event in this transaction")

    # 4. Contract. A Transfer of a different token is a different payment.
    on_contract = [
        e for e in transfers if e.get("contract_address") == network.usdt_contract
    ]
    if not on_contract:
        seen = sorted({str(e.get("contract_address")) for e in transfers})
        return Rejected("wrong_contract", f"transfers are on {seen}")

    # 5. Recipient, compared in ONE canonical form. base58 and hex are both
    #    correct spellings of the same account, and only the shared decoder is
    #    allowed to bridge them.
    recipient_hex = tron_address_to_evm_hex(getattr(intent, "recipient", None))
    if recipient_hex is None:
        return Rejected("wrong_recipient", "the intent has no decodable recipient")
    to_recipient = [
        e for e in on_contract
        if str(_result_of(e).get("to", "")).lower() == recipient_hex
    ]
    if not to_recipient:
        return Rejected("wrong_recipient", "no Transfer credits this intent's recipient")

    # 6. Amount, in base units, exactly. The matcher has no tolerance, so
    #    neither does this.
    token = token_for(network.chain_name, "USDT")
    if token is None:
        return Rejected("wrong_contract", f"{network.chain_name} has no USDT in the registry")
    expected = to_base_units(getattr(intent, "amount", 0), token[1])
    exact = [
        e for e in to_recipient if str(_result_of(e).get("value")) == str(expected)
    ]
    if not exact:
        seen = sorted({str(_result_of(e).get("value")) for e in to_recipient})
        return Rejected("wrong_amount", f"expected {expected}, transaction carries {seen}")

    # 7. Sender. The client's claim is checked against the chain, then used —
    #    never the other way round.
    payer_hex = tron_address_to_evm_hex(submitted_payer)
    if payer_hex is None:
        return Rejected("sender_mismatch", "the submitted payer is not a TRON address")
    from_payer = [
        e for e in exact if str(_result_of(e).get("from", "")).lower() == payer_hex
    ]
    if not from_payer:
        return Rejected("sender_mismatch", "the transfer was not sent by the submitted payer")

    expected_sender = getattr(intent, "expected_sender", None)
    if expected_sender:
        expected_hex = tron_address_to_evm_hex(expected_sender)
        if expected_hex != payer_hex:
            return Rejected(
                "sender_mismatch", "the payer is not the sender this intent expects"
            )

    # 8. The real log index, from the enrichment and nowhere else.
    #
    #    The transfer dict is assembled from values the chain has now confirmed:
    #    `to` and `from` in base58 because a settlement row stores base58, and
    #    `value` from the EVENT rather than from the intent — if the amount
    #    check above is ever loosened, the row must still record what actually
    #    moved, not what was invoiced.
    matched = from_payer[0]
    transfer = {
        "transaction_id": tx_hash,
        "token_info": {"address": network.usdt_contract},
        "to": getattr(intent, "recipient"),
        "from": submitted_payer,
        "value": str(_result_of(matched).get("value")),
        "block_timestamp": info.get("blockTimeStamp"),
        "type": "Transfer",
    }
    try:
        event = _pair_transfer_to_event(transfer, events)
    except TronEnrichmentError as exc:
        # Ambiguity included: two indistinguishable transfers mean the index is
        # a coin flip, and the poller refuses that too.
        return Rejected("unenrichable", str(exc))

    return Verified(transfer=transfer, event=event)
