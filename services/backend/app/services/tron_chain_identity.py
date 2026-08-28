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

Nothing calls this yet — the poller will, in the next slice.
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

# A second network is a NEW ENTRY here, not a refactor. There is deliberately
# no Nile or Shasta entry: an unverified testnet genesis is worse than an
# absent one, because it would make the guard pass for the wrong reason. Add
# one only with its own provenance block, verified the same way.
TRON_GENESIS_BLOCK_IDS: dict[str, str] = {
    "mainnet": TRON_MAINNET_GENESIS_BLOCK_ID,
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
    node_url: str, timeout: float = TRON_IDENTITY_TIMEOUT_SECONDS
) -> None:
    """Prove that the TRON node at `node_url` serves mainnet, by reading its
    genesis block. Raise `TronChainIdentityError` if it does not, or if the
    question could not be answered. Return None on success.

    The node URL arrives as an ARGUMENT and no configuration is read: no
    network flag, no environment variable, no matching on the host string. The
    deleted `useTronWallet.ts` decided mainnet-vs-testnet by inspecting the URL
    it was handed, which proves only what the caller already believed. This
    asks the network instead.

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

    if block_id.lower() != TRON_MAINNET_GENESIS_BLOCK_ID:
        raise TronChainIdentityError(
            f"TRON node {node_url}: genesis block is {block_id}, not "
            f"{TRON_MAINNET_GENESIS_BLOCK_ID} — this node does not serve TRON "
            f"mainnet. Watching it would key the cursor, the environment stamp "
            f"and the payee address to the wrong network."
        )

    logger.info(
        "[tron-chain-identity] node %s proven to serve TRON mainnet "
        "(genesis %s).",
        node_url,
        block_id,
    )
