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
