"""Topic-hash resolution must be correct AND fail-loud.

The getLogs topic filter IS the indexer's detection scope: a wrong topic0
means zero payments detected. Two invariants pinned here:

1. The module constants equal the keccak of the exact on-chain event
   signatures — pinned as literals so a signature edit that forgets the
   contract (or vice versa) fails a test instead of silently filtering
   nothing. Every other test builds fake logs FROM the module constant and
   compares against the same constant, so only this file catches a wrong
   value.

2. A keccak/import failure at topic resolution must RAISE (boot fails with
   the real cause), never degrade to a sentinel: eth-utils is a hard pinned
   dependency, and a placeholder topic in the filter would stall the watcher
   against a live chain while the process reports itself running.
"""

import pytest

import app.services.payment_indexer as idx

# keccak256 of the exact event signatures in RSendsRouter / RSendsSplitRouter.
# Recompute with: python -c "from eth_utils import keccak; print('0x'+keccak(text=SIG).hex())"
PAYMENT_MADE_TOPIC0 = (
    "0xab7ccb7fe7da5e22a3f0005fe67aa4652cd87b623e108b54088210d0deb04947"
)
SPLIT_PAYMENT_MADE_TOPIC0 = (
    "0x451afa2957064e8a00f536645647373c30cba4fc74e00cdfecc599d0fe30fd60"
)


def test_payment_made_topic_pinned():
    assert idx._payment_made_topic() == PAYMENT_MADE_TOPIC0
    assert idx.PAYMENT_MADE_TOPIC == PAYMENT_MADE_TOPIC0


def test_split_payment_made_topic_pinned():
    assert idx._split_payment_made_topic() == SPLIT_PAYMENT_MADE_TOPIC0
    assert idx.SPLIT_PAYMENT_MADE_TOPIC == SPLIT_PAYMENT_MADE_TOPIC0


def test_topic_resolution_failure_raises(monkeypatch):
    """A broken keccak must raise, never return a placeholder topic."""
    import eth_utils

    def _boom(*args, **kwargs):
        raise RuntimeError("keccak unavailable")

    monkeypatch.setattr(eth_utils, "keccak", _boom)
    with pytest.raises(Exception) as exc_info:
        idx._payment_made_topic()
    assert "keccak unavailable" in str(exc_info.value)
    with pytest.raises(Exception) as exc_info:
        idx._split_payment_made_topic()
    assert "keccak unavailable" in str(exc_info.value)


def test_no_sentinel_topic_in_module():
    """No code path may hand a placeholder topic to a getLogs filter."""
    import inspect

    source = inspect.getsource(idx)
    assert "UNRESOLVED_RECOMPUTE" not in source
