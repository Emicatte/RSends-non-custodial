"""
RPagos Backend — Test: NonceManager (Redis-backed Atomic Nonce Management)

Tests:
  1. test_initialize_empty_redis       — uses chain value when Redis is empty
  2. test_initialize_redis_ahead       — keeps Redis value when Redis > chain
  3. test_initialize_chain_ahead       — uses chain value when chain > Redis
  4. test_get_next_sequential          — 10 calls, all different, sequential
  5. test_get_next_concurrent          — 10 calls via asyncio.gather, all different
  6. test_reserve_range                — correct range, no overlap with get_next
  7. test_crash_recovery               — simulates crash, verifies nonce is safe

Run:
  cd rpagos-backend
  pytest tests/test_nonce_manager.py -v
"""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.nonce_manager import NonceManager, NonceError


# ═══════════════════════════════════════════════════════════════
#  Fake Redis — in-memory dict with INCR/INCRBY/SET/GET/EXISTS
# ═══════════════════════════════════════════════════════════════

class FakeRedisLock:
    """Fake async context-manager lock that always succeeds."""

    def __init__(self, *args, **kwargs):
        pass

    async def acquire(self):
        return True

    async def release(self):
        pass

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        await self.release()


class FakeRedis:
    """Minimal fake Redis with atomic INCR/INCRBY for testing."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value):
        self._store[key] = str(value)

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    async def incrby(self, key: str, amount: int) -> int:
        val = int(self._store.get(key, "0")) + amount
        self._store[key] = str(val)
        return val

    def lock(self, name, timeout=None, blocking_timeout=None):
        return FakeRedisLock()


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

SIGNER_ADDRESS = "0x50b593f57A3FE580096216A1cf8ba3aB070f4b85"
CHAIN_ID = 84532


def _make_chain_nonce_mock(nonce_value: int):
    """Return an AsyncMock for _get_chain_nonce that returns nonce_value."""
    mock = AsyncMock(return_value=nonce_value)
    return mock


@pytest_asyncio.fixture
async def fake_redis():
    return FakeRedis()


@pytest_asyncio.fixture
async def nm(fake_redis):
    """NonceManager with mocked Redis and signer."""
    manager = NonceManager(chain_id=CHAIN_ID)
    manager._address = SIGNER_ADDRESS.lower()

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        yield manager


# ═══════════════════════════════════════════════════════════════
#  Tests
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_initialize_empty_redis(nm, fake_redis):
    """When Redis is empty, initialize() should use the chain nonce value."""
    chain_nonce = 42

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(chain_nonce)):
        result = await nm.initialize()

    assert result == chain_nonce
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    assert int(await fake_redis.get(key)) == chain_nonce


@pytest.mark.asyncio
async def test_initialize_redis_ahead(nm, fake_redis):
    """When Redis nonce > chain nonce, keep the Redis value (pending TXes in mempool)."""
    chain_nonce = 42
    redis_nonce = 50  # 8 TXes pending in mempool

    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, redis_nonce)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(chain_nonce)):
        result = await nm.initialize()

    assert result == redis_nonce
    assert int(await fake_redis.get(key)) == redis_nonce


@pytest.mark.asyncio
async def test_initialize_chain_ahead(nm, fake_redis):
    """When chain nonce > Redis nonce, update Redis (TXes confirmed externally)."""
    chain_nonce = 60
    redis_nonce = 50  # chain moved ahead (e.g. manual TX from wallet)

    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, redis_nonce)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(chain_nonce)):
        result = await nm.initialize()

    assert result == chain_nonce
    assert int(await fake_redis.get(key)) == chain_nonce


@pytest.mark.asyncio
async def test_get_next_sequential(nm, fake_redis):
    """10 sequential get_next() calls must return 10 different sequential nonces."""
    start_nonce = 100
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, start_nonce)

    nonces = []
    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        for _ in range(10):
            n = await nm.get_next()
            nonces.append(n)

    # All different
    assert len(set(nonces)) == 10
    # Sequential starting from start_nonce
    assert nonces == list(range(start_nonce, start_nonce + 10))


@pytest.mark.asyncio
async def test_get_next_concurrent(nm, fake_redis):
    """10 concurrent get_next() calls via asyncio.gather must all return different nonces."""
    start_nonce = 200
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, start_nonce)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        nonces = await asyncio.gather(*[nm.get_next() for _ in range(10)])

    # All different
    assert len(set(nonces)) == 10
    # All in expected range
    assert set(nonces) == set(range(start_nonce, start_nonce + 10))


@pytest.mark.asyncio
async def test_reserve_range(nm, fake_redis):
    """reserve_range returns correct range, and subsequent get_next doesn't overlap."""
    start_nonce = 300
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, start_nonce)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        # Reserve 5 nonces
        range_start, range_end = await nm.reserve_range(5)

        assert range_start == 300
        assert range_end == 304

        # Next get_next must be AFTER the reserved range
        next_nonce = await nm.get_next()
        assert next_nonce == 305

        # Reserve another batch
        r2_start, r2_end = await nm.reserve_range(3)
        assert r2_start == 306
        assert r2_end == 308

    # No overlap between any allocated nonces
    all_nonces = list(range(range_start, range_end + 1)) + [next_nonce] + list(range(r2_start, r2_end + 1))
    assert len(set(all_nonces)) == len(all_nonces)


@pytest.mark.asyncio
async def test_crash_recovery(nm, fake_redis):
    """Simulate crash: Redis has nonce=110, chain says 96. After recovery,
    nonce must be >= 110 (not 96) to avoid mempool collisions."""
    redis_nonce_before_crash = 110
    chain_nonce_after_restart = 96  # chain only sees confirmed TXes

    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, redis_nonce_before_crash)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(chain_nonce_after_restart)):

        # Simulate restart: initialize reads both sources
        result = await nm.initialize()

        # MUST keep Redis value (110) not chain value (96)
        assert result == redis_nonce_before_crash
        assert result > chain_nonce_after_restart

        # Next nonce must continue from 110, not drop to 96
        next_nonce = await nm.get_next()
        assert next_nonce == redis_nonce_before_crash  # 110
        assert next_nonce > chain_nonce_after_restart


@pytest.mark.asyncio
async def test_get_next_not_initialized(nm, fake_redis):
    """get_next() on uninitialized manager raises NonceError."""
    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        with pytest.raises(NonceError, match="not initialized"):
            await nm.get_next()


@pytest.mark.asyncio
async def test_reserve_range_invalid_count(nm, fake_redis):
    """reserve_range(0) or reserve_range(-1) raises NonceError."""
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, 100)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis):
        with pytest.raises(NonceError, match="must be >= 1"):
            await nm.reserve_range(0)
        with pytest.raises(NonceError, match="must be >= 1"):
            await nm.reserve_range(-1)


@pytest.mark.asyncio
async def test_sync_from_chain_chain_ahead(nm, fake_redis):
    """sync_from_chain updates Redis when chain is ahead."""
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, 50)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(75)):
        result = await nm.sync_from_chain()

    assert result == 75
    assert int(await fake_redis.get(key)) == 75


@pytest.mark.asyncio
async def test_sync_from_chain_redis_ahead(nm, fake_redis):
    """sync_from_chain keeps Redis value when Redis > chain (pending TXes)."""
    key = nm._nonce_key(SIGNER_ADDRESS.lower())
    await fake_redis.set(key, 120)

    with patch.object(NonceManager, "_get_redis", return_value=fake_redis), \
         patch.object(nm, "_get_chain_nonce", _make_chain_nonce_mock(96)):
        result = await nm.sync_from_chain()

    assert result == 120
    assert int(await fake_redis.get(key)) == 120
