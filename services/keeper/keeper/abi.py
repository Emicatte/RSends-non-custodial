"""The minimal ABI the keeper needs — hand-written, and deliberately minimal.

`RSendsAutoSplit.sol` is not on main (it lives on `feat/auto-split-contract`),
so this service cannot read `packages/contracts/out/` at build time. Carrying its
own ABI is the right shape for a standalone service anyway: the keeper's Docker
image would need a fallback regardless.

Minimal is a security property here, not tidiness. `setPolicy` and
`clearPolicy` exist on the contract and are absent below on purpose — they
belong to the merchant's key. A method the keeper cannot name is a method it
cannot call, and `tests/test_abi.py` pins that the only state-changing entry
here is `executeSplit`.

Declaring the three custom errors is what lets web3 decode a revert BY NAME.
Without them a skip and an outage both arrive as opaque bytes, and the keeper
cannot tell "this merchant has no policy" from "the node is broken". Only these
three are reachable from `_plan`, the shared guard behind both `previewSplit`
and `executeSplit`.

Selectors are pinned against the compiled artifact in tests/test_abi.py.
"""

AUTO_SPLIT_ABI = [
    {
        "type": "function",
        "name": "previewSplit",
        "inputs": [
            {"name": "merchant", "type": "address"},
            {"name": "token", "type": "address"},
        ],
        "outputs": [
            {"name": "total", "type": "uint256"},
            {"name": "amounts", "type": "uint256[]"},
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "getPolicy",
        "inputs": [
            {"name": "merchant", "type": "address"},
            {"name": "token", "type": "address"},
        ],
        "outputs": [
            {"name": "recipients", "type": "address[]"},
            {"name": "bps", "type": "uint16[]"},
            {"name": "minAmount", "type": "uint256"},
        ],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "executeSplit",
        "inputs": [
            {"name": "merchant", "type": "address"},
            {"name": "token", "type": "address"},
        ],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    # ── The three reverts `_plan` can produce ──
    {"type": "error", "name": "NoPolicy", "inputs": []},
    {"type": "error", "name": "ZeroAmount", "inputs": []},
    {
        "type": "error",
        "name": "BelowMinAmount",
        "inputs": [
            {"name": "amount", "type": "uint256"},
            {"name": "minAmount", "type": "uint256"},
        ],
    },
]

#: Reads only. The keeper never calls `approve` or `transfer` — the allowance is
#: the merchant's to grant and to revoke (`approve(spender, 0)` is their
#: trustless brake, and the keeper must not be able to undo or re-grant it).
ERC20_ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "allowance",
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
]
