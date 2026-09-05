"""The hand-written ABI, pinned against selectors computed from the compiled
contract.

`RSendsAutoSplit.sol` is NOT on main — it lives on `feat/auto-split-contract`,
so this service cannot read `packages/contracts/out/` at build time and carries
its own minimal ABI instead. That is the right shape for a standalone service,
but it means a typo in a signature string would be caught by nothing until a
live call reverted for the wrong reason.

The expected values below are LITERALS, taken from the compiled artifact's
`methodIdentifiers` (packages/contracts/out/RSendsAutoSplit.sol/…json on that
branch). Recomputing them from the same signature strings the ABI declares would
be circular and would pin nothing.

When `feat/auto-split-contract` merges, this file is the place to switch to
reading the forge artifact directly.
"""

from eth_utils import keccak

from keeper.abi import AUTO_SPLIT_ABI, ERC20_ABI

# From `forge build` output, not recomputed here.
EXPECTED_SELECTORS = {
    "executeSplit(address,address)": "307f752f",
    "getPolicy(address,address)": "317eaaa3",
    "previewSplit(address,address)": "e34412df",
}
# The two canonical ERC-20 selectors, which every reader already knows by sight.
EXPECTED_ERC20_SELECTORS = {
    "balanceOf(address)": "70a08231",
    "allowance(address,address)": "dd62ed3e",
}


def _signature(entry) -> str:
    return entry["name"] + "(" + ",".join(i["type"] for i in entry["inputs"]) + ")"


def _selectors(abi) -> dict:
    return {
        _signature(e): keccak(text=_signature(e))[:4].hex()
        for e in abi
        if e.get("type") == "function"
    }


def test_auto_split_selectors_match_the_compiled_contract():
    assert _selectors(AUTO_SPLIT_ABI) == EXPECTED_SELECTORS


def test_erc20_selectors_match():
    assert _selectors(ERC20_ABI) == EXPECTED_ERC20_SELECTORS


def test_the_three_reachable_custom_errors_are_declared():
    """Only these three are reachable from `_plan`, and they are declared for
    `chain._ERRORS_BY_SELECTOR` to decode with — web3 7.16 hands back the raw
    selector and never reads this ABI. `BelowMinAmount` is the only one carrying
    arguments, which makes it the one useful log line — so its inputs must be
    right, not just its name."""
    errors = {e["name"]: e for e in AUTO_SPLIT_ABI if e.get("type") == "error"}

    assert set(errors) == {"NoPolicy", "ZeroAmount", "BelowMinAmount"}
    assert [i["type"] for i in errors["BelowMinAmount"]["inputs"]] == [
        "uint256",
        "uint256",
    ]
    assert [i["name"] for i in errors["BelowMinAmount"]["inputs"]] == [
        "amount",
        "minAmount",
    ]


def test_the_keeper_declares_no_state_changing_method_but_executeSplit():
    """The authority boundary, stated in the ABI itself: a method the keeper
    cannot name is a method it cannot call. `setPolicy` and `clearPolicy` exist
    on the contract and are deliberately absent here — they belong to the
    merchant's key."""
    writes = [
        e["name"]
        for e in AUTO_SPLIT_ABI
        if e.get("type") == "function"
        and e.get("stateMutability") not in ("view", "pure")
    ]

    assert writes == ["executeSplit"]


def test_getPolicy_and_previewSplit_return_shapes_match_the_contract():
    by_name = {e["name"]: e for e in AUTO_SPLIT_ABI if e.get("type") == "function"}

    assert [o["type"] for o in by_name["getPolicy"]["outputs"]] == [
        "address[]",
        "uint16[]",
        "uint256",
    ]
    assert [o["type"] for o in by_name["previewSplit"]["outputs"]] == [
        "uint256",
        "uint256[]",
    ]
