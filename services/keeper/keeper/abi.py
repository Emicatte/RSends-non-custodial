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

The three custom errors are declared for the keeper's OWN decoder, not for
web3's. web3 7.16 does not decode a custom error: it re-raises the node's error
`data` as both the message and `.data` and never consults this ABI, so a revert
arrives as four bytes of selector. `chain._ERRORS_BY_SELECTOR` is built from the
entries below and is what turns those bytes into `NoPolicy()` or
`BelowMinAmount(amount, minAmount)` — without that pair, a skip and an outage
would log identically and the keeper could not tell "this merchant has no
policy" from "the node is broken". Only these three are reachable from `_plan`,
the shared guard behind both `previewSplit` and `executeSplit`.

Function selectors are pinned against the compiled artifact in
tests/test_abi.py; the error selectors, which only matter once something looks
them up, are pinned beside that lookup in tests/test_chain_and_client.py.
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
