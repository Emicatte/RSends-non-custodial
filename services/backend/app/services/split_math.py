"""Split math — backend mirror of RSendsSplitRouter._computeAmounts.

amounts[i] = total * shares_bps[i] // 10000 (floor), remainder to index 0 (the
"primary"). Conservation is exact: sum(amounts) == total, always.

MUST stay bit-identical to the contract
(packages/contracts/src/RSendsSplitRouter.sol): the indexer recomputes the
per-leg amounts from the on-chain totalAmount and the stored BPS, and REJECTS a
settlement whose event amounts differ. Don't change one side without the other.
"""

MAX_RECIPIENTS = 20
BPS_DENOMINATOR = 10_000


def compute_split_amounts(total_base_units: int, shares_bps: list[int]) -> list[int]:
    """Per-leg base-unit amounts for a split, or raise ValueError.

    Rejects (same shapes the contract reverts on): non-positive total, fewer
    than 2 or more than 20 legs, any non-positive bps, and — the load-bearing
    invariant — a bps sum that is not EXACTLY 10000.
    """
    if total_base_units <= 0:
        raise ValueError("split total must be positive")
    n = len(shares_bps)
    if n < 2 or n > MAX_RECIPIENTS:
        raise ValueError(f"split needs 2..{MAX_RECIPIENTS} recipients, got {n}")
    for bps in shares_bps:
        if bps <= 0:
            raise ValueError("every split share must be a positive bps value")
    if sum(shares_bps) != BPS_DENOMINATOR:
        raise ValueError(
            f"split shares must sum to exactly {BPS_DENOMINATOR} bps, "
            f"got {sum(shares_bps)}"
        )

    amounts = [(total_base_units * bps) // BPS_DENOMINATOR for bps in shares_bps]
    amounts[0] += total_base_units - sum(amounts)  # remainder → primary
    return amounts
