"""Split math — the backend mirror of RSendsSplitRouter._computeAmounts.

The indexer recomputes per-leg amounts from the on-chain totalAmount and the
stored BPS via `compute_split_amounts`, and rejects a settlement whose event
amounts differ. The math MUST therefore be bit-identical to the contract:
floor division per leg, remainder to index 0 (the primary). Don't change one
side without the other (packages/contracts/src/RSendsSplitRouter.sol).
"""

import pytest

from app.services.split_math import compute_split_amounts


def test_conservation_and_remainder():
    """101 / [33.33%, 33.33%, 34.34%(sic 33.34%)]: floors are 33+33+33 = 99,
    remainder 2 goes to index 0 — total conserved exactly."""
    amounts = compute_split_amounts(101, [3333, 3333, 3334])
    assert amounts == [35, 33, 33]
    assert sum(amounts) == 101


def test_exact_division_no_remainder():
    amounts = compute_split_amounts(100_000_000, [5000, 3000, 2000])
    assert amounts == [50_000_000, 30_000_000, 20_000_000]


def test_mirrors_contract_floor_semantics():
    """Property sweep: for many (total, bps) pairs — conservation holds, every
    non-primary leg is the exact floor, the primary is floor + remainder."""
    cases = [
        (1, [1, 9999]),
        (7, [5000, 5000]),
        (999_999_999_999, [1, 1, 9998]),
        (10**18, [3333, 3333, 3334]),
        (12345678901234567890, [123, 4567, 5310]),
    ]
    for total, bps in cases:
        amounts = compute_split_amounts(total, bps)
        assert sum(amounts) == total, (total, bps)
        for i in range(1, len(bps)):
            assert amounts[i] == (total * bps[i]) // 10_000, (total, bps, i)
        assert amounts[0] >= (total * bps[0]) // 10_000, (total, bps)


def test_rejects_bps_sum_not_10000():
    with pytest.raises(ValueError):
        compute_split_amounts(100, [5000, 4999])
    with pytest.raises(ValueError):
        compute_split_amounts(100, [5000, 5001])


def test_rejects_bad_shapes():
    """Defense-in-depth: the indexer feeds this stored DB rows — reject any
    shape the contract would reject (count bounds, zero bps, zero total)."""
    with pytest.raises(ValueError):
        compute_split_amounts(100, [10000])          # < 2 recipients
    with pytest.raises(ValueError):
        compute_split_amounts(100, [476] * 20 + [480])  # > 20 recipients
    with pytest.raises(ValueError):
        compute_split_amounts(100, [10000, 0])       # zero-bps leg
    with pytest.raises(ValueError):
        compute_split_amounts(0, [5000, 5000])       # zero total


# ─── RSendsAutoSplit divergence pin ──────────────────────────────────────────
#
# Two dust rules coexist ON PURPOSE and must never be unified:
#   - SplitRouter / compute_split_amounts: remainder → index 0 (the primary).
#     The indexer recomputes event amounts with this rule and REJECTS mismatches.
#   - RSendsAutoSplit.executeSplit: remainder → LAST recipient, which is what
#     lands the merchant wallet at exactly zero after a distribution.
# A contributor "fixing the duplication" in either direction silently breaks
# one of those invariants. The tests below make that unification loud.


def contract_convention_remainder_to_last(
    total_base_units: int, shares_bps: list[int]
) -> list[int]:
    """Test-local reference of RSendsAutoSplit.executeSplit's dust rule.

    Floor division for every leg but the last; the last leg takes
    total - sum(previous floors) (packages/contracts/src/RSendsAutoSplit.sol,
    _plan). Deliberately NOT in production code and NOT imported from
    split_math — it exists only so the divergence below stays pinned.
    """
    amounts = [(total_base_units * bps) // 10_000 for bps in shares_bps[:-1]]
    amounts.append(total_base_units - sum(amounts))
    return amounts


def test_split_math_diverges_from_autosplit_remainder_rule():
    """On a dust case the two rules MUST disagree — that is the pin."""
    backend = compute_split_amounts(101, [3333, 3333, 3334])
    autosplit = contract_convention_remainder_to_last(101, [3333, 3333, 3334])

    assert backend == [35, 33, 33]     # remainder 2 → index 0
    assert autosplit == [33, 33, 35]   # remainder 2 → last leg
    assert backend != autosplit, (
        "compute_split_amounts (SplitRouter rule: remainder → first/primary) "
        "now matches RSendsAutoSplit's rule (remainder → last). These are "
        "deliberately different: unifying them breaks either the indexer's "
        "settlement validation or AutoSplit's exact-zero merchant balance. "
        "See the split_math docstring before touching either side."
    )


def test_autosplit_convention_conserves_total():
    """The contract convention sums to exactly the input amount — always."""
    cases = [
        (101, [3333, 3333, 3334]),
        (101, [5000, 5000]),
        (7, [5000, 5000]),
        (999_999_999_999, [1, 1, 9998]),
        (12345678901234567890, [123, 4567, 5310]),
    ]
    for total, bps in cases:
        amounts = contract_convention_remainder_to_last(total, bps)
        assert sum(amounts) == total, (total, bps)
