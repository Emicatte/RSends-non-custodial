"""The preflight: decide locally, then make the contract agree.

`RSendsAutoSplit._plan` is the shared guard behind BOTH `previewSplit` and
`executeSplit`, so mirroring it locally is what lets the keeper skip without
spending gas. The reference implementation is
`packages/contracts/script/verify-autosplit-sepolia.sh --dry-run`, whose own
header calls itself "the reference implementation of the keeper's eth_call
preflight"; the order of the three skip reasons here is `_plan`'s order, not a
convenient one.

The fourth reason has no counterpart in `_plan` and is the point of §8 of the
plan: `SelfRecipient` was added to the contract later and is NOT retroactive, so
a policy registered against an earlier deployment can still pay the source
wallet itself. The contract's own comment names the keeper as the vector —
"non serve un attaccante, è la normale cadenza del keeper" — because each tick
re-splits the residue and erodes the merchant's share.
"""

import pytest

from keeper.models import Wallet
from keeper.preflight import (
    SKIP_BELOW_MIN_AMOUNT,
    SKIP_NO_POLICY,
    SKIP_PREVIEW_DISAGREES,
    SKIP_PREVIEW_REVERTED,
    SKIP_RPC_UNAVAILABLE,
    SKIP_SELF_RECIPIENT,
    SKIP_ZERO_AMOUNT,
    Policy,
    PreviewReverted,
    RpcUnavailable,
    expected_amounts,
    preflight,
)

WALLET_ADDR = "0x" + "a" * 40
REC_A = "0x" + "b" * 40
REC_B = "0x" + "c" * 40

WALLET = Wallet(
    id="sw-1",
    org_id="org-1",
    chain="base_sepolia",
    chain_id=84532,
    address=WALLET_ADDR,
    token_symbol="USDC",
    token_address="0x" + "d" * 40,
    token_decimals=6,
    auto_split="0x" + "5" * 40,
)

POLICY = Policy(recipients=(REC_A, REC_B), bps=(5000, 5000), min_amount=100_000)


class FakeChain:
    """Records what it was asked, so the tests can assert on the questions as
    well as the answers."""

    def __init__(
        self,
        *,
        policy=POLICY,
        balance=0,
        allowance=0,
        preview=None,
        preview_raises=None,
        reads_raise=None,
    ):
        self._policy = policy
        self._balance = balance
        self._allowance = allowance
        self._preview = preview
        self._preview_raises = preview_raises
        self._reads_raise = reads_raise
        self.preview_calls = 0

    def get_policy(self, wallet):
        if self._reads_raise:
            raise self._reads_raise
        return self._policy

    def balance_of(self, wallet):
        if self._reads_raise:
            raise self._reads_raise
        return self._balance

    def allowance(self, wallet):
        if self._reads_raise:
            raise self._reads_raise
        return self._allowance

    def preview_split(self, wallet):
        self.preview_calls += 1
        if self._preview_raises:
            raise self._preview_raises
        return self._preview


# ═══════════════════════════════════════════════════════════════
#  The three reasons _plan itself can revert with
# ═══════════════════════════════════════════════════════════════


def test_no_policy_is_skipped_without_asking_the_contract():
    """An unset policy decodes to empty arrays — "not configured", not
    "configured with nobody"."""
    chain = FakeChain(policy=None, balance=10_000_000, allowance=10_000_000)

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_NO_POLICY
    assert chain.preview_calls == 0, "no reason to spend an eth_call on a known skip"


def test_nothing_distributable_is_skipped():
    """min(balance, allowance) == 0 — the wallet is empty, or the merchant
    revoked the approval (their trustless brake)."""
    for balance, allowance in ((0, 10_000_000), (10_000_000, 0), (0, 0)):
        chain = FakeChain(balance=balance, allowance=allowance)

        d = preflight(chain, WALLET)

        assert d.execute is False
        assert d.reason == SKIP_ZERO_AMOUNT
        assert chain.preview_calls == 0


def test_below_min_amount_is_skipped():
    chain = FakeChain(balance=99_999, allowance=10_000_000)

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_BELOW_MIN_AMOUNT
    assert d.total == 99_999


def test_the_executable_total_is_the_smaller_of_balance_and_allowance():
    chain = FakeChain(balance=500_000, allowance=300_000, preview=(300_000, [150_000, 150_000]))

    d = preflight(chain, WALLET)

    assert d.execute is True
    assert d.total == 300_000


def test_a_max_uint256_allowance_does_not_overflow():
    """The reference script shells out to python3 for this exact min(): a MAX
    allowance overflows bash's 64-bit arithmetic. Python ints are arbitrary
    precision, so the pin is that nothing narrows them on the way through."""
    max_uint = 2**256 - 1
    chain = FakeChain(
        balance=1_000_000, allowance=max_uint, preview=(1_000_000, [500_000, 500_000])
    )

    d = preflight(chain, WALLET)

    assert d.execute is True
    assert d.total == 1_000_000


# ═══════════════════════════════════════════════════════════════
#  The reason the contract cannot tell us
# ═══════════════════════════════════════════════════════════════


def test_a_policy_leg_paying_the_source_wallet_is_skipped_and_surfaced():
    """The on-chain SelfRecipient guard is not retroactive. Such a policy
    previews and executes perfectly well — and leaves the wallet non-empty, so
    the next tick re-splits the residue. Refusing is the keeper's job."""
    self_paying = Policy(
        recipients=(REC_A, WALLET_ADDR), bps=(5000, 5000), min_amount=100_000
    )
    chain = FakeChain(
        policy=self_paying,
        balance=1_000_000,
        allowance=1_000_000,
        preview=(1_000_000, [500_000, 500_000]),
    )

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_SELF_RECIPIENT
    assert WALLET_ADDR.lower() in d.detail.lower(), "the log line must name the address"


def test_self_recipient_is_matched_case_insensitively():
    """Registry addresses are lowercased; a policy read off-chain is not."""
    self_paying = Policy(
        recipients=(REC_A, WALLET_ADDR.upper().replace("0X", "0x")),
        bps=(5000, 5000),
        min_amount=0,
    )
    chain = FakeChain(policy=self_paying, balance=1_000_000, allowance=1_000_000)

    assert preflight(chain, WALLET).reason == SKIP_SELF_RECIPIENT


# ═══════════════════════════════════════════════════════════════
#  previewSplit as the cross-check
# ═══════════════════════════════════════════════════════════════


def test_preview_reverting_means_skip_never_execute_anyway():
    """A revert is the contract saying no. Whatever we computed locally, the
    call that would follow is the one that reverts."""
    chain = FakeChain(
        balance=1_000_000,
        allowance=1_000_000,
        preview_raises=PreviewReverted("NoPolicy()"),
    )

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_PREVIEW_REVERTED


def test_preview_disagreeing_with_the_local_plan_means_skip():
    """Disagreement means a stale read or the wrong contract address. Either
    way the local model of the money is wrong, which is the last moment we can
    still find that out for free."""
    chain = FakeChain(
        balance=1_000_000,
        allowance=1_000_000,
        preview=(999_999, [500_000, 499_999]),  # total != our min(balance, allowance)
    )

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_PREVIEW_DISAGREES


def test_preview_disagreeing_on_the_legs_means_skip():
    chain = FakeChain(
        balance=1_000_000,
        allowance=1_000_000,
        preview=(1_000_000, [600_000, 400_000]),  # not the 50/50 the policy says
    )

    assert preflight(chain, WALLET).reason == SKIP_PREVIEW_DISAGREES


def test_agreement_executes():
    chain = FakeChain(
        balance=1_000_000, allowance=1_000_000, preview=(1_000_000, [500_000, 500_000])
    )

    d = preflight(chain, WALLET)

    assert d.execute is True
    assert d.total == 1_000_000


# ═══════════════════════════════════════════════════════════════
#  The chain being unreachable is never a reason to assume
# ═══════════════════════════════════════════════════════════════


def test_rpc_unreachable_means_skip_never_execute_on_an_assumption():
    chain = FakeChain(reads_raise=RpcUnavailable("connection refused"))

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_RPC_UNAVAILABLE


def test_rpc_unreachable_during_preview_also_skips():
    chain = FakeChain(
        balance=1_000_000,
        allowance=1_000_000,
        preview_raises=RpcUnavailable("timeout"),
    )

    d = preflight(chain, WALLET)

    assert d.execute is False
    assert d.reason == SKIP_RPC_UNAVAILABLE


# ═══════════════════════════════════════════════════════════════
#  The split maths — remainder to the LAST leg
# ═══════════════════════════════════════════════════════════════


def test_remainder_goes_to_the_last_recipient():
    """RSendsAutoSplit puts the remainder on the LAST leg; RSendsSplitRouter
    puts it on the FIRST. Both source files carry mirror-image warnings against
    deduplicating the two — split_math.py mirrors the SplitRouter ONLY and must
    never be reused here."""
    # 1000 at 3333/3333/3334: floors are 333/333/333, remainder 1 → last.
    assert expected_amounts(1000, (3333, 3333, 3334)) == [333, 333, 334]


def test_amounts_always_sum_to_the_total():
    for total in (1, 7, 999, 1_000_000, 10**18 + 7):
        for bps in ((5000, 5000), (3333, 3333, 3334), (1, 9999)):
            assert sum(expected_amounts(total, bps)) == total
