"""Decide locally, then make the contract agree.

`RSendsAutoSplit._plan` is the shared guard behind BOTH `previewSplit` and
`executeSplit`. Mirroring it here is what lets the keeper skip without spending
gas, and the contract's own docstring states the contract: "una eth_call che
passa qui è una executeSplit che non brucia gas invano".

The reference implementation is
`packages/contracts/script/verify-autosplit-sepolia.sh --dry-run`. The order of
the three skip reasons below is `_plan`'s order, not a convenient one, so a
disagreement between this and the script is a real signal rather than an
artefact of sequencing.

Two things this file must NOT do:

  • Reuse `split_math.py` from the backend. That module mirrors
    `RSendsSplitRouter`, which puts the division remainder on the FIRST leg.
    `RSendsAutoSplit` puts it on the LAST — that is what closes the wallet to
    exactly zero. Both source files carry mirror-image warnings against
    deduplicating the two.

  • Narrow any integer. A MAX-uint256 allowance is normal (it is what
    `approve(spender, MAX)` leaves behind), and the reference script shells out
    to python3 precisely because that value overflows bash's 64-bit arithmetic.
    Python ints are arbitrary precision; nothing here may cast them.
"""

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

log = logging.getLogger(__name__)

BPS_DENOMINATOR = 10_000

# ── Skip reasons ──────────────────────────────────────────────
# The first three mirror the reverts `_plan` itself can produce.
SKIP_NO_POLICY = "no_policy"
SKIP_ZERO_AMOUNT = "zero_amount"
SKIP_BELOW_MIN_AMOUNT = "below_min_amount"
#: No counterpart in `_plan` — the on-chain SelfRecipient guard is not
#: retroactive, so this is the keeper's to enforce. See `preflight`.
SKIP_SELF_RECIPIENT = "self_recipient"
#: The contract said no, whatever we computed.
SKIP_PREVIEW_REVERTED = "preview_reverted"
#: We and the contract disagree about the money. Never execute on that.
SKIP_PREVIEW_DISAGREES = "preview_disagrees"
#: We could not see the chain. Never execute on an assumption.
SKIP_RPC_UNAVAILABLE = "rpc_unavailable"


class RpcUnavailable(Exception):
    """The node could not be reached, or answered with a transport fault.

    Distinct from a revert: this says nothing about the merchant's state, so the
    right response is to try again next tick, not to conclude anything.
    """


class PreviewReverted(Exception):
    """`previewSplit` reverted — a DECISION, not an error.

    Carries the custom error that `chain._revert_detail` decoded from the raw
    selector web3 returns (`NoPolicy()`, `BelowMinAmount(amount, minAmount)`),
    which is the difference between a log line that explains itself and one that
    says "call failed".
    """


@dataclass(frozen=True)
class Policy:
    recipients: tuple
    bps: tuple
    min_amount: int


@dataclass(frozen=True)
class Decision:
    execute: bool
    reason: str
    total: Optional[int] = None
    detail: str = ""


def expected_amounts(total: int, bps: Sequence[int]) -> list:
    """Floor per leg, remainder to the LAST — the RSendsAutoSplit convention.

    Deliberately NOT `split_math.py`: that mirrors RSendsSplitRouter, which puts
    the remainder on the first leg. Using the wrong one would disagree with
    `previewSplit` on every amount that does not divide evenly, which is most of
    them.
    """
    amounts = [(total * b) // BPS_DENOMINATOR for b in bps[:-1]]
    amounts.append(total - sum(amounts))
    return amounts


def preflight(chain, wallet) -> Decision:
    """Should the keeper call `executeSplit` for this wallet right now?

    Returns a Decision either way; raises nothing. Every path that cannot prove
    a split is due returns `execute=False`, because the failure mode of a wrong
    "yes" is a transaction and the failure mode of a wrong "no" is a delay.
    """
    try:
        policy = chain.get_policy(wallet)
        balance = chain.balance_of(wallet)
        allowance = chain.allowance(wallet)
    except RpcUnavailable as exc:
        return Decision(False, SKIP_RPC_UNAVAILABLE, detail=str(exc))

    # 1. NoPolicy — an unset policy decodes to empty arrays, which is "not
    #    configured", not "configured with nobody".
    if policy is None or not policy.recipients:
        return Decision(False, SKIP_NO_POLICY)

    # 2. ZeroAmount — the wallet is empty, OR the merchant revoked the approval.
    #    `_plan` collapses both into one revert, so the decision cannot tell them
    #    apart and should not try. The log line must: an idle wallet is nothing
    #    happening, while `approve(spender, 0)` on a funded wallet is the
    #    merchant pulling their trustless brake. Neither escalates, so if this
    #    string does not separate them nothing else ever will.
    total = min(balance, allowance)
    if total == 0:
        return Decision(
            False,
            SKIP_ZERO_AMOUNT,
            total=0,
            detail=f"min(balance={balance}, allowance={allowance}) = 0",
        )

    # 3. BelowMinAmount — the merchant's own floor, so a split is worth its gas.
    if total < policy.min_amount:
        return Decision(
            False,
            SKIP_BELOW_MIN_AMOUNT,
            total=total,
            detail=f"{total} < minAmount {policy.min_amount}",
        )

    # 4. The one the contract cannot tell us. `SelfRecipient` was added to
    #    RSendsAutoSplit later and is NOT retroactive, so a policy registered
    #    against an earlier deployment can still pay the source wallet itself.
    #    Such a policy previews and executes perfectly — and leaves the wallet
    #    non-empty, so the next tick re-splits the residue and the merchant's
    #    share erodes with every pass. The contract comment names the vector
    #    exactly: "non serve un attaccante, è la normale cadenza del keeper".
    wallet_addr = wallet.address.lower()
    if any(r.lower() == wallet_addr for r in policy.recipients):
        return Decision(
            False,
            SKIP_SELF_RECIPIENT,
            total=total,
            detail=(
                f"policy for {wallet.address} pays the source wallet itself; "
                "refusing to execute (legacy pre-SelfRecipient policy)"
            ),
        )

    # 5. Now ask the contract. A revert here is its answer, not a fault.
    try:
        preview_total, preview_amounts = chain.preview_split(wallet)
    except PreviewReverted as exc:
        return Decision(False, SKIP_PREVIEW_REVERTED, total=total, detail=str(exc))
    except RpcUnavailable as exc:
        return Decision(False, SKIP_RPC_UNAVAILABLE, total=total, detail=str(exc))

    # 6. Agreement. Disagreement means a stale read or the wrong contract
    #    address — either way our model of the money is wrong, and this is the
    #    last moment we can discover that for free.
    expected = expected_amounts(total, policy.bps)
    if preview_total != total or list(preview_amounts) != expected:
        return Decision(
            False,
            SKIP_PREVIEW_DISAGREES,
            total=total,
            detail=(
                f"local total={total} legs={expected} but previewSplit says "
                f"total={preview_total} legs={list(preview_amounts)}"
            ),
        )

    return Decision(True, "execute", total=total)
