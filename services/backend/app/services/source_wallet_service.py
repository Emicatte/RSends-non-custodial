"""Source-wallet registration gates and on-chain reads for RSendsAutoSplit.

RSendsAutoSplit is ownerless: no on-chain token whitelist, no owner, no pause.
Its header states the consequence plainly — enforcement is the CALLER's job,
because the contract's empty-to-zero invariant only holds for a standard,
non-fee-on-transfer, non-rebasing ERC-20. This module is where that enforcement
lives, as three gates run in a fixed order:

    chain_is_supported(chain)          -> 400 UNSUPPORTED_CHAIN
    auto_split_address_for(chain)      -> 422 AUTO_SPLIT_UNAVAILABLE
    token_is_enabled(chain, symbol)    -> 400 UNSUPPORTED_TOKEN

The order is not cosmetic. The token gate alone cannot hold this surface:
`token_is_enabled("tron", "USDT")` is True — TRON USDT is a real, enabled,
chargeable token — but TRON is `settlement: watch_only`, its addresses are
base58check, and AutoSplit is an EVM contract that was never deployed there. A
registration passing only the token gate would put the keeper to work on a
chain where the policy cannot exist. So the AutoSplit gate runs first and
answers a different question: not "is this token real?" but "is there a
contract here at all?".

Error-code convention follows the intent path: 400 for "shape was fine, the
registry says no" and 422 for "the feature is not configured on this chain",
mirroring `SPLIT_UNAVAILABLE`.
"""

import logging
from typing import Optional

from fastapi import HTTPException

from app.services.chain_access import is_testnet_chain
from app.services.router_registry import (
    _enc_addr,
    _selector,
    chain_id_for,
    chain_is_supported,
    token_for,
    token_is_enabled,
)

logger = logging.getLogger(__name__)


def auto_split_address_for(chain: str) -> Optional[str]:
    """The deployed RSendsAutoSplit for `chain`, or None if there is none.

    THE SEAM, and deliberately fail-closed: it returns None for every chain
    today, so no source wallet can be registered anywhere until an operator
    wires the address map. That is the correct default for a feature whose
    contract is deployed on exactly one testnet — "not configured" and "not
    deployed" should be indistinguishable from the API's side.

    The map itself (`AUTO_SPLIT_ADDRESSES_JSON`, `{chain_id: address}`,
    following the `SPLIT_ROUTER_ADDRESSES_JSON` three-layer pattern: raw
    settings field -> parsed property -> resolver) is NOT wired here yet; that
    is a separate, operator-facing change. When it lands, only this function
    body changes.

    One hard constraint for whoever wires it: the AutoSplit address must NEVER
    be added to any `RSENDS_ROUTER_*_ADDRESSES_JSON` map. The indexer builds
    its log filters from those chain sets, so it would fetch every
    `SplitExecuted` and then drop it with a WARNING per execution.
    """
    return None


def resolve_registration_context(chain: str, token_symbol: str) -> dict:
    """Run the three gates and return the server-derived registration context.

    Everything in the returned dict is derived here, never accepted from the
    client: the chain id, the environment the row is stamped with, the
    AutoSplit address, and the token's on-chain address and decimals.
    """
    if not chain_is_supported(chain):
        raise HTTPException(
            400,
            {
                "error": "UNSUPPORTED_CHAIN",
                "message": f"Chain {chain} is not supported.",
            },
        )

    auto_split = auto_split_address_for(chain)
    if auto_split is None:
        raise HTTPException(
            422,
            {
                "error": "AUTO_SPLIT_UNAVAILABLE",
                "message": f"Auto Split is not available on chain {chain}.",
            },
        )

    if not token_is_enabled(chain, token_symbol):
        raise HTTPException(
            400,
            {
                "error": "UNSUPPORTED_TOKEN",
                "message": (
                    f"Token {token_symbol} is not enabled on chain {chain}."
                ),
            },
        )

    chain_id = chain_id_for(chain)
    # In production the gate above guarantees this resolves: TOKEN_REGISTRY and
    # FEE_POLICY are built in the same loader pass, so an enabled token always
    # has an address. The None guard is still explicit — the same shape
    # `intent_service` uses around its own `token_for` — because the
    # alternative is an unpacking TypeError the moment the two maps ever
    # disagree, and a 500 would blame the wrong layer. Nothing downstream of
    # registration needs the address anyway: it is re-resolved from the
    # registry at each use site, so the row never carries it.
    token = token_for(chain, token_symbol)

    return {
        "chain_id": chain_id,
        "environment": "test" if is_testnet_chain(chain_id) else "live",
        "auto_split_address": auto_split,
        "token_address": token[0] if token else None,
        "token_decimals": token[1] if token else None,
    }


# ── On-chain reads (never persisted — the chain is the source of truth) ────


def _decode_words(result: str) -> list[bytes]:
    raw = bytes.fromhex(result[2:] if result.startswith("0x") else result)
    return [raw[i : i + 32] for i in range(0, len(raw) - 31, 32)]


def _word_int(word: bytes) -> int:
    return int.from_bytes(word, "big")


def _decode_dynamic_array(words: list[bytes], head_index: int) -> list[int]:
    """Read a dynamic array whose 32-byte offset sits at `head_index`."""
    offset_words = _word_int(words[head_index]) // 32
    length = _word_int(words[offset_words])
    return [_word_int(w) for w in words[offset_words + 1 : offset_words + 1 + length]]


def _as_address(value: int) -> str:
    return "0x" + f"{value:040x}"


async def read_onchain_state(
    *, chain: str, chain_id: int, auto_split: str, token_address: str, wallet: str
) -> dict:
    """Live `getPolicy` + `allowance` + `balanceOf` for the dashboard panel.

    Read on demand and never stored. The policy belongs to the merchant's own
    key: they can rewrite it on chain without touching this API, so any cached
    copy would be wrong with no way to know it. `previewSplit` is deliberately
    NOT called here — it reverts by design when there is no policy, when the
    balance is zero, or when the total is below `minAmount`, and a revert is
    not an error worth surfacing as one. The executable total is the same
    `min(balance, allowance)` the contract itself plans with, computed here
    from the two values already fetched.

    Every field degrades to None on RPC failure rather than raising: a
    dashboard panel that cannot reach the chain should say so, not 500.
    """
    from app.services.rpc_manager import get_rpc_manager

    rpc = get_rpc_manager(chain_id)

    async def _call(to: str, data: str) -> Optional[str]:
        try:
            result = await rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
            return None if not result or result == "0x" else result
        except Exception as exc:  # pragma: no cover — network failure path
            logger.warning(
                "source-wallet eth_call failed (chain=%s to=%s): %s", chain, to, exc
            )
            return None

    policy_data = (
        "0x"
        + _selector("getPolicy(address,address)").hex()
        + _enc_addr(wallet)
        + _enc_addr(token_address)
    )
    allowance_data = (
        "0x"
        + _selector("allowance(address,address)").hex()
        + _enc_addr(wallet)
        + _enc_addr(auto_split)
    )
    balance_data = (
        "0x" + _selector("balanceOf(address)").hex() + _enc_addr(wallet)
    )

    policy_raw = await _call(auto_split, policy_data)
    allowance_raw = await _call(token_address, allowance_data)
    balance_raw = await _call(token_address, balance_data)

    policy = None
    if policy_raw:
        try:
            words = _decode_words(policy_raw)
            recipients = [_as_address(v) for v in _decode_dynamic_array(words, 0)]
            bps = _decode_dynamic_array(words, 1)
            min_amount = _word_int(words[2])
            # An unset policy decodes to empty arrays, which is "not
            # configured", not "configured with nobody".
            policy = (
                {
                    "recipients": recipients,
                    "bps": bps,
                    "min_amount": str(min_amount),
                }
                if recipients
                else None
            )
        except (IndexError, ValueError) as exc:  # pragma: no cover
            logger.warning("getPolicy decode failed (chain=%s): %s", chain, exc)

    allowance = _word_int(_decode_words(allowance_raw)[0]) if allowance_raw else None
    balance = _word_int(_decode_words(balance_raw)[0]) if balance_raw else None
    executable = (
        str(min(allowance, balance))
        if allowance is not None and balance is not None
        else None
    )

    return {
        "auto_split": auto_split,
        "token_address": token_address,
        "policy_configured": policy is not None,
        "policy": policy,
        "allowance": None if allowance is None else str(allowance),
        "balance": None if balance is None else str(balance),
        "executable_amount": executable,
    }
