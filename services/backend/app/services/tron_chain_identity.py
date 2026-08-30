"""TRON chain identity — PROVEN from the genesis block, not declared.

A TRON node URL carries no proof of which network it serves. Everything the
watch-only poller will derive from that node — its cursor, the test/live stamp,
the address a payer is told to send funds to — assumes mainnet, and a node on
Nile answers every one of those questions in the same shape, plausibly and
wrongly. So the network is proven once, against a value that cannot move: the
genesis block.

This module is deliberately NOT part of `rpc_manager`. That module speaks
`eth_*` JSON-RPC; TRON's is an HTTP API with its own request shape. The two
share a posture, not a transport.

`tron_poller` calls this once per configured node, per network, before it
reads a cursor or makes a single TronGrid call.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Pinned genesis block ids
# ═══════════════════════════════════════════════════════════════
#
# TRON mainnet genesis blockID
#   00000000000000001ebf88508a03865c71d452e25f4d51194196a1d22b6653dc
#
# Verified 2026-08-28 against three independent sources, byte-identical:
#   - TronGrid    POST https://api.trongrid.io/wallet/getblockbynum {"num":0}
#   - TronStack   POST https://api.tronstack.io/wallet/getblockbynum {"num":0}
#   - tronscan.org/block/0  (Block Hash field)
# Cross-checks holding across sources: parentHash
# e58f33f9baf9305dc6f82b9f1934ea8f0ade2defb951258d50167028c780351f;
# block time 2018-06-25 01:51:00 UTC (mainnet launch); last 4 bytes
# 2b6653dc = 728126428, TRON's chain id, which derives from this hash and was
# independently confirmed via eth_chainId on a fourth node.
#
# That provenance block is the point: it lets the next person re-verify this
# number in two minutes instead of trusting it.

TRON_MAINNET_GENESIS_BLOCK_ID = (
    "00000000000000001ebf88508a03865c71d452e25f4d51194196a1d22b6653dc"
)

# TRON Nile testnet genesis blockID
#   0000000000000000d698d4192c56cb6be724a558448e2684802de4d6cd8690dc
#
# Verified 2026-08-29 against ONE source:
#   - TronGrid    POST https://nile.trongrid.io/wallet/getblockbynum {"num":0}
# Internal cross-checks: the first 8 bytes are height 0, and the last 4 bytes
# cd8690dc = 3448148188, Nile's chain id, which derives from this hash.
#
# One source, where mainnet has three. That is a deliberate, bounded
# concession, not an oversight: the only public Nile node operator IS TronGrid,
# so a second "independent" source would be the same node behind a different
# name. It is acceptable HERE and would not be on mainnet, because of what a
# wrong constant costs. A wrong value makes every Nile node fail the guard and
# the poller refuse to start — loud, immediate, and harmless. It cannot make
# the poller index the wrong chain, which is the failure this module exists to
# prevent. Re-verify with the curl above before trusting it further than that.
TRON_NILE_GENESIS_BLOCK_ID = (
    "0000000000000000d698d4192c56cb6be724a558448e2684802de4d6cd8690dc"
)

# A second network is a NEW ENTRY here, not a refactor — which is why Nile
# appears as one more key and nothing else changed shape. Shasta is still
# deliberately absent: an unverified testnet genesis is worse than an absent
# one, because it would make the guard pass for the wrong reason. Add one only
# with its own provenance block, verified the same way.
TRON_GENESIS_BLOCK_IDS: dict[str, str] = {
    "mainnet": TRON_MAINNET_GENESIS_BLOCK_ID,
    "nile": TRON_NILE_GENESIS_BLOCK_ID,
}

# A TRON blockID is 32 bytes: the block NUMBER big-endian in the first 8, then
# the hash of the block header. Height 0 is therefore structural — the first 16
# hex characters of a genesis blockID are zeros on every TRON network.
_BLOCK_ID_HEX_LEN = 64
_HEIGHT_PREFIX_LEN = 16

# One attempt, bounded. A guard that retries until success is a guard that
# hangs a boot instead of refusing one.
TRON_IDENTITY_TIMEOUT_SECONDS = 10.0


class TronChainIdentityError(RuntimeError):
    """The TRON network behind a node URL could not be proven, or was disproven.

    There is deliberately no "probably fine" branch and no bool return: an
    unproven chain is not a safe chain, and a guard whose result can be ignored
    will be ignored.
    """


async def assert_tron_chain_identity(
    node_url: str,
    network: str,
    timeout: float = TRON_IDENTITY_TIMEOUT_SECONDS,
) -> None:
    """Prove that the TRON node at `node_url` serves `network`, by reading its
    genesis block. Raise `TronChainIdentityError` if it does not, or if the
    question could not be answered. Return None on success.

    `network` is a key of `TRON_GENESIS_BLOCK_IDS`. Both it and the node URL
    arrive as ARGUMENTS, and no configuration is read: no environment variable,
    and no matching on the host string. The deleted `useTronWallet.ts` decided
    which network it was on by inspecting the URL it was handed, which proves
    only what the caller already believed. This makes the caller state its
    expectation and then asks the network whether it holds.

    An unregistered `network` raises rather than raising `KeyError`, so a
    caller's `except TronChainIdentityError` covers a typo too.

    Exactly one POST of `{"num": 0}` to `/wallet/getblockbynum` is made.

    Every failure is the same failure. Unreachable host, timeout, non-200,
    unparseable body, absent `blockID`, a `blockID` that is not 32 bytes of
    hex, a `blockID` that is not at height 0, and a well-formed `blockID`
    belonging to another network all raise identically. This deliberately
    INVERTS the convention in `webhook_service.check_webhook_egress`, where a
    host that cannot be resolved is treated as safe — correctly, because a host
    that cannot be reached cannot reach anything internal either. The reasoning
    does not carry over: a node that cannot be reached has proven nothing, and
    proving nothing is exactly the state this guard exists to refuse.

    It has no off switch, by design — see
    `tests/test_tron_chain_identity.py::test_no_configuration_surface_can_disable_tron_chain_identity`.
    """
    try:
        expected = TRON_GENESIS_BLOCK_IDS[network]
    except KeyError as exc:
        raise TronChainIdentityError(
            f"TRON node {node_url}: no genesis block is registered for network "
            f"{network!r} (known: {sorted(TRON_GENESIS_BLOCK_IDS)}), so the "
            f"network cannot be proven."
        ) from exc

    endpoint = f"{node_url.rstrip('/')}/wallet/getblockbynum"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json={"num": 0})
    except Exception as exc:
        raise TronChainIdentityError(
            f"TRON node {node_url}: could not be asked for its genesis block "
            f"({exc!r}). An unreachable node proves nothing, and an unproven "
            f"chain is not a safe chain."
        ) from exc

    if response.status_code != 200:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) with HTTP "
            f"{response.status_code}, so the network is unproven."
        )

    try:
        body = response.json()
    except Exception as exc:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) with a body that "
            f"is not JSON ({exc!r}), so the network is unproven."
        ) from exc

    if not isinstance(body, dict) or "blockID" not in body:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) without a "
            f"blockID, so the network is unproven."
        )

    block_id = body["blockID"]
    if not isinstance(block_id, str) or len(block_id) != _BLOCK_ID_HEX_LEN:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) with blockID "
            f"{block_id!r}, which is not 32 bytes of hex."
        )
    try:
        int(block_id, 16)
    except ValueError as exc:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) with blockID "
            f"{block_id!r}, which is not hex."
        ) from exc

    if block_id[:_HEIGHT_PREFIX_LEN] != "0" * _HEIGHT_PREFIX_LEN:
        raise TronChainIdentityError(
            f"TRON node {node_url}: answered getblockbynum(0) with blockID "
            f"{block_id!r}, whose leading 8 bytes are not block height 0. The "
            f"node did not answer the question that was asked."
        )

    if block_id.lower() != expected:
        raise TronChainIdentityError(
            f"TRON node {node_url}: genesis block is {block_id}, not "
            f"{expected} — this node does not serve TRON {network}. Watching "
            f"it would key the cursor, the environment stamp and the payee "
            f"address to the wrong network."
        )

    logger.info(
        "[tron-chain-identity] node %s proven to serve TRON %s (genesis %s).",
        node_url,
        network,
        block_id,
    )
