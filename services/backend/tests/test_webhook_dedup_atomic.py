"""
RPagos Backend — Test: atomic per-TX webhook dedup (M6).

`claim_tx_processed` replaces the non-atomic is_tx_processed()+mark_tx_processed()
pair. A single Redis SETNX makes exactly ONE concurrent delivery of a given
tx_hash win the claim; the rest skip. Fail-closed when Redis is down.

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_webhook_dedup_atomic.py -v
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.idempotency_service import claim_tx_processed


class _FakeRedis:
    """Minimal Redis honoring SET ... NX semantics."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, val, nx=False, ex=None):
        if nx and key in self.store:
            return None  # key already exists ⇒ SETNX fails
        self.store[key] = val
        return True


@pytest.mark.asyncio
async def test_claim_is_single_winner():
    fake = _FakeRedis()
    with patch("app.services.cache_service.get_redis", AsyncMock(return_value=fake)):
        first = await claim_tx_processed("0xTX")
        dup = await claim_tx_processed("0xTX")       # same tx ⇒ duplicate
        other = await claim_tx_processed("0xOTHER")  # different tx ⇒ new
    assert first == (True, "new")
    assert dup == (False, "duplicate")
    assert other == (True, "new")


@pytest.mark.asyncio
async def test_concurrent_claims_one_winner():
    """Two concurrent claims of the same tx ⇒ exactly one (True, 'new')."""
    fake = _FakeRedis()
    with patch("app.services.cache_service.get_redis", AsyncMock(return_value=fake)):
        results = await asyncio.gather(
            claim_tx_processed("0xRACE"),
            claim_tx_processed("0xRACE"),
        )
    winners = [r for r in results if r[0] is True]
    losers = [r for r in results if r[0] is False]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0] == (False, "duplicate")


@pytest.mark.asyncio
async def test_claim_fails_closed_on_redis_down():
    with patch("app.services.cache_service.get_redis", AsyncMock(return_value=None)):
        result = await claim_tx_processed("0xTX")
    assert result == (False, "redis_unavailable")
