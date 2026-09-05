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

Naming the revert is this module's job, not web3's. web3 7.16 re-raises the
node's error `data` as BOTH the exception message and `.data`
(`error_formatters_utils.raise_contract_logic_error_on_revert`) without ever
consulting the contract ABI, so `str(exc)` is `"('0xcefa6b05', '0xcefa6b05')"` —
four bytes of selector and no name. `_ERRORS_BY_SELECTOR` below is the lookup
web3 does not do, built from the error entries `abi.py` declares.

The transient/permanent split mirrors `rpc_manager._is_permanent_rpc_error`,
including its `_TRANSIENT_OVERRIDE_PATTERNS`. That override list is not
decoration: the 2026-08-22 incident was a quota 429 classified as permanent, so
the circuit breaker never opened, nothing alerted, and a dead provider kept
being asked for days. The wordings below all contain "exceed", which the
permanent patterns match for an unrelated reason (the getLogs range limit).
"""

import logging

from eth_abi import decode as abi_decode
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


def _error_table(abi) -> dict:
    """selector → (name, argument names, argument types), from the ABI's errors.

    Built once, from the same declarations `abi.py` carries for this purpose.
    A renamed or mistyped error here changes a selector and stops matching —
    `tests/test_chain_and_client.py` pins all three against the contract.
    """
    table = {}
    for entry in abi:
        if entry.get("type") != "error":
            continue
        arg_names = [i["name"] for i in entry["inputs"]]
        arg_types = [i["type"] for i in entry["inputs"]]
        signature = f"{entry['name']}({','.join(arg_types)})"
        selector = bytes(Web3.keccak(text=signature))[:4].hex()
        table[selector] = (entry["name"], arg_names, arg_types)
    return table


_ERRORS_BY_SELECTOR = _error_table(AUTO_SPLIT_ABI)


def _named(raw: str):
    """`0x12d7693c…` → `BelowMinAmount(amount=50000, minAmount=100000)`.

    None when the string is not revert data we can name — the caller then keeps
    what web3 gave it rather than inventing a decoding.
    """
    body = raw[2:] if raw[:2].lower() == "0x" else raw
    known = _ERRORS_BY_SELECTOR.get(body[:8].lower())
    if known is None:
        return None
    name, arg_names, arg_types = known
    if not arg_types:
        return f"{name}()"
    try:
        values = abi_decode(arg_types, bytes.fromhex(body[8:]))
    except Exception:
        # The selector matched, so the name is still the useful half.
        return f"{name}(<undecodable args: 0x{body[8:]}>)"
    return f"{name}(" + ", ".join(f"{n}={v}" for n, v in zip(arg_names, values)) + ")"


def _revert_detail(exc: Exception) -> str:
    """What the revert SAYS, decoded here because web3 7.16 does not decode it.

    `BelowMinAmount(amount, minAmount)` is the reason declaring the errors was
    worth it: it is the one revert that carries the numbers, and "the merchant's
    floor is 0.10 USDC and 0.04 arrived" is a different operational fact from
    "no policy". Falls back to web3's own text — never raises, and never turns
    an unknown selector into a guess.
    """
    fallback = None
    for candidate in (getattr(exc, "data", None), getattr(exc, "message", None)):
        if not isinstance(candidate, str):
            continue
        named = _named(candidate)
        if named is not None:
            return named
        if fallback is None:
            fallback = candidate
    return fallback if fallback is not None else str(exc)


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
            # Named HERE: web3 hands back the raw selector, so the ABI's error
            # declarations only become a name once `_revert_detail` looks them
            # up. An unknown selector keeps web3's text rather than a guess.
            raise PreviewReverted(_revert_detail(exc)) from exc
        except Exception as exc:
            raise _classify(exc) from exc
