"""Chain reads, and the three-way outcome the backend's transport cannot express.

`rpc_manager._raw_rpc_call` stringifies a JSON-RPC error into a `RuntimeError`
and drops the `data` field, so the backend cannot tell `NoPolicy` from
`BelowMinAmount` from a dead node. That is fine there — nothing in the backend
calls a function that reverts on purpose. It is not fine here: `previewSplit`
signals "skip" BY reverting, so collapsing a revert into a transport error would
make every skip and every outage log identically.

So a call has three outcomes, not two:

    revert with data  →  a DECISION      →  PreviewReverted (named, if decodable)
    transient fault   →  try again       →  RpcUnavailable
    permanent fault   →  bad config      →  PermanentRpcError

The transient/permanent split mirrors `rpc_manager._is_permanent_rpc_error`,
including its `_TRANSIENT_OVERRIDE_PATTERNS`. That override list is not
decoration: the 2026-08-22 incident was a quota 429 classified as permanent, so
the circuit breaker never opened, nothing alerted, and a dead provider kept
being asked for days. The wordings below all contain "exceed", which the
permanent patterns match for an unrelated reason (the getLogs range limit).
"""

import logging

from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError

from keeper.abi import AUTO_SPLIT_ABI, ERC20_ABI
from keeper.preflight import Policy, PreviewReverted, RpcUnavailable

log = logging.getLogger(__name__)

# Availability faults that arrive wearing a permanent-looking code or wording.
_TRANSIENT_OVERRIDE_PATTERNS = (
    "beyond current head",
    "rate limit",
    "capacity",
    "compute unit",
    "quota",
    "request count",
    "too many requests",
    "throttl",
)
_PERMANENT_PATTERNS = ("invalid param", "method not found", "does not exist")


class PermanentRpcError(Exception):
    """The request is wrong, not the moment — retrying changes nothing."""


def _classify(exc: Exception) -> Exception:
    message = str(exc).lower()
    if any(p in message for p in _TRANSIENT_OVERRIDE_PATTERNS):
        return RpcUnavailable(str(exc))
    if any(p in message for p in _PERMANENT_PATTERNS):
        return PermanentRpcError(str(exc))
    return RpcUnavailable(str(exc))


class Chain:
    """Reads for one wallet's chain. Holds no key and cannot send."""

    def __init__(self, w3: Web3):
        self._w3 = w3

    def _auto_split(self, wallet):
        return self._w3.eth.contract(
            address=Web3.to_checksum_address(wallet.auto_split), abi=AUTO_SPLIT_ABI
        )

    def _token(self, wallet):
        return self._w3.eth.contract(
            address=Web3.to_checksum_address(wallet.token_address), abi=ERC20_ABI
        )

    def get_policy(self, wallet, block_identifier=None):
        try:
            recipients, bps, min_amount = (
                self._auto_split(wallet)
                .functions.getPolicy(
                    Web3.to_checksum_address(wallet.address),
                    Web3.to_checksum_address(wallet.token_address),
                )
                .call(block_identifier=block_identifier)
            )
        except Exception as exc:
            raise _classify(exc) from exc
        # Empty arrays mean "not configured", not "configured with nobody".
        if not recipients:
            return None
        return Policy(
            recipients=tuple(recipients), bps=tuple(bps), min_amount=int(min_amount)
        )

    def balance_of(self, wallet, block_identifier=None):
        try:
            return int(
                self._token(wallet)
                .functions.balanceOf(Web3.to_checksum_address(wallet.address))
                .call(block_identifier=block_identifier)
            )
        except Exception as exc:
            raise _classify(exc) from exc

    def allowance(self, wallet, block_identifier=None):
        try:
            return int(
                self._token(wallet)
                .functions.allowance(
                    Web3.to_checksum_address(wallet.address),
                    Web3.to_checksum_address(wallet.auto_split),
                )
                .call(block_identifier=block_identifier)
            )
        except Exception as exc:
            raise _classify(exc) from exc

    def preview_split(self, wallet, block_identifier=None):
        """`previewSplit`, whose revert is an answer rather than a failure."""
        try:
            total, amounts = (
                self._auto_split(wallet)
                .functions.previewSplit(
                    Web3.to_checksum_address(wallet.address),
                    Web3.to_checksum_address(wallet.token_address),
                )
                .call(block_identifier=block_identifier)
            )
            return int(total), [int(a) for a in amounts]
        except (ContractCustomError, ContractLogicError) as exc:
            # Named because the ABI declares the three errors `_plan` can throw.
            # BelowMinAmount carries (amount, minAmount) — the one genuinely
            # informative revert, and the reason declaring them was worth it.
            raise PreviewReverted(str(exc)) from exc
        except Exception as exc:
            raise _classify(exc) from exc
