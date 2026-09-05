"""Source-wallet registration gates and on-chain reads for RSendsAutoSplit.

RSendsAutoSplit is ownerless: no on-chain token whitelist, no owner, no pause.
Its header states the consequence plainly — enforcement is the CALLER's job,
because the contract's empty-to-zero invariant only holds for a standard,
non-fee-on-transfer, non-rebasing ERC-20. This module is where that enforcement
lives, as three gates run in a fixed order:

    chain_is_supported(chain)          -> 400 UNSUPPORTED_CHAIN
    auto_split_address_for(chain)      -> 422 AUTO_SPLIT_UNAVAILABLE
    token_is_enabled(chain, symbol)    -> 400 UNSUPPORTED_TOKEN

The order is not cosmetic. The token gate alone cannot hold this surface: it
answers "is this token real?", and a registration that passes only it would put
the keeper to work on a chain where no AutoSplit contract exists. The AutoSplit
gate runs first and answers the different question, "is there a contract here
at all?" — which is a fact about deployment, so the operator's address map is
what decides it.

AutoSplit is NOT EVM-only. It compiles under the tronprotocol solc fork and
executes on TRON (proved on Nile against real USDT), so `tron` and `tron_nile`
are eligible chains exactly as `base` and `base_sepolia` are, and which of them
is actually live is decided by `AUTO_SPLIT_ADDRESSES_JSON` alone. Do NOT
re-add a `is_watch_only_chain` refusal here: that field is about settlement
ROUTING for the payment path — the payer sends TRC-20 straight to the merchant,
with no router — and it says nothing about whether a merchant can point a
keeper at their own wallet on the same chain. Those are different capabilities
on the same chain.

Error-code convention follows the intent path: 400 for "shape was fine, the
registry says no" and 422 for "the feature is not configured on this chain",
mirroring `SPLIT_UNAVAILABLE`.
"""

import logging
from typing import Optional

from fastapi import HTTPException

from app.config import get_settings
from app.services.chain_access import is_testnet_chain, is_watch_only_testnet
from app.services.router_registry import (
    _enc_addr,
    _selector,
    chain_id_for,
    chain_is_supported,
    token_for,
    token_is_enabled,
)

logger = logging.getLogger(__name__)


def _address_in_any_router_map(address: str, settings) -> bool:
    """True iff `address` appears in ANY router address map, on any chain.

    The constraint is flat, not per-chain: an address the indexer watches on
    base is not made safe by being registered for base_sepolia, because the
    watcher set is a union and the filters are built from it.
    """
    wanted = address.lower()
    for attr in (
        "rsends_router_addresses",
        "rsends_router_v2_addresses",
        "split_router_addresses",
    ):
        for configured in (getattr(settings, attr, {}) or {}).values():
            if isinstance(configured, str) and configured.lower() == wanted:
                return True
    return False


def auto_split_address_for(chain: str) -> Optional[str]:
    """The deployed RSendsAutoSplit for `chain`, or None if there is none.

    Reads `AUTO_SPLIT_ADDRESSES_JSON` through the
    `SPLIT_ROUTER_ADDRESSES_JSON` three-layer pattern: raw settings field ->
    parsed property -> this resolver. Fail-closed everywhere it can be — unset,
    malformed, unknown chain and unconfigured chain are one answer, None, and
    a source wallet cannot be registered on a chain that gives it.

    Keyed by chain NAME (`{chain_name: address}`), unlike the three router maps,
    which key by EVM chain id. AutoSplit runs on TRON as well as Base, and TRON
    has no EVM chain id to key by — nor may it be given a synthetic one, since
    `728126428` in an EVM chain table starts a PaymentWatcher against a non-EVM
    node and SystemExits the boot (`test_tron_poller.py:790`). The name is the
    registry's own vocabulary: `token_registry.json` already keys `tron` and
    `tron_nile` that way.

    THE MAP IS THE GATE. There is deliberately no `is_watch_only_chain` refusal
    here. That field describes settlement ROUTING for the payment path — the
    payer sends TRC-20 straight to the merchant, with no router — and says
    nothing about whether a merchant may point a keeper at their own wallet on
    the same chain. Auto Split is a separate capability, the contract does run
    on TRON, and which chains are actually live is decided by what the operator
    put in the map and nothing else.

    Two guards the router resolvers do not have, because this one is reached by
    a registration surface rather than by the payment builder:

    1. `chain_is_supported` — the map is operator-supplied text, so a key that
       names no chain this system has a settlement path for must not resolve.
       `chain_is_supported("arbitrum")` is False even though `CHAIN_IDS` knows
       42161, so an `"arbitrum"` entry gives back nothing.

    2. `_address_in_any_router_map` — the address must NEVER also live in a
       `RSENDS_ROUTER_*` or `SPLIT_ROUTER` map. The indexer builds its log
       filters from those chain sets, so it would fetch every `SplitExecuted`
       and then drop it with a WARNING per execution. A colliding address is
       refused and the collision is logged, because otherwise the only symptom
       is that per-execution warning in a log nobody is reading.
    """
    if not chain_is_supported(chain):
        return None

    settings = get_settings()
    addresses = getattr(settings, "auto_split_addresses", {}) or {}
    address = addresses.get(chain)
    if address is None:
        return None

    if _address_in_any_router_map(address, settings):
        logger.error(
            "AUTO_SPLIT_ADDRESSES_JSON: %s (chain %s) is ALSO configured in a "
            "RSENDS_ROUTER_*/SPLIT_ROUTER address map. Refusing to use it — the "
            "indexer would ingest every SplitExecuted from it and then discard "
            "each one. Remove the address from the router map.",
            address, chain,
        )
        return None

    return address


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

    # In production the gate above guarantees this resolves: TOKEN_REGISTRY and
    # FEE_POLICY are built in the same loader pass, so an enabled token always
    # has an address. The None guard is still explicit — the same shape
    # `intent_service` uses around its own `token_for` — because the
    # alternative is an unpacking TypeError the moment the two maps ever
    # disagree, and a 500 would blame the wrong layer. Nothing downstream of
    # registration needs the address anyway: it is re-resolved from the
    # registry at each use site, so the row never carries it.
    token = token_for(chain, token_symbol)

    # Testnet-ness is asked TWICE because a chain can carry it two ways, and
    # neither question answers the other. `is_testnet_chain` is keyed by EVM
    # chain id, which a watch-only chain does not have (it classifies None as
    # mainnet); `is_watch_only_testnet` is keyed by NAME, which is the only
    # identifier such a chain has. `tron_nile` is a testnet and would otherwise
    # be stamped `live` — putting a TRON chain id in TESTNET_CHAIN_IDS to fix
    # that is forbidden: the EVM boot guard reads that table and would
    # eth_chainId a TRON node. Both helpers fail closed to mainnet, so the
    # `or` can only ever widen to `test` on a chain that explicitly claims it.
    is_test = is_testnet_chain(chain_id_for(chain)) or is_watch_only_testnet(chain)

    return {
        # The chain NAME. The EVM id is derived at the call sites that need one
        # (SIWE), because not every supported chain has one.
        "chain": chain,
        "environment": "test" if is_test else "live",
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
