"""One tick over one wallet: the lock, the send, the confirm, the back-off.

Run against a REAL Redis. The lock's entire purpose is to be atomic across
processes, and an in-memory dict driven from one thread proves branching, not
atomicity — `test_webhook_dedup_atomic.py` in the backend suite is honest about
that limitation in its own docstring. Every key here is uuid-suffixed so no case
can observe another's state.
"""

import os
import threading
import uuid

import pytest
import redis as redis_lib

from keeper.models import Wallet
from keeper.preflight import SKIP_ZERO_AMOUNT, Policy
from keeper.state import KeeperState
from keeper.tick import OUTCOME_BACKED_OFF, OUTCOME_EXECUTED, OUTCOME_FAILED, \
    OUTCOME_LOCKED_OUT, OUTCOME_SKIPPED, process_wallet

REDIS_URL = os.environ.get("KEEPER_TEST_REDIS_URL", "redis://localhost:6379/0")

WALLET_ADDR = "0x" + "a" * 40
REC_A = "0x" + "b" * 40
REC_B = "0x" + "c" * 40
POLICY = Policy(recipients=(REC_A, REC_B), bps=(5000, 5000), min_amount=0)


@pytest.fixture
def wallet():
    """A distinct id per test ⇒ distinct Redis keys ⇒ no cross-test leakage."""
    return Wallet(
        id=f"sw-{uuid.uuid4()}",
        org_id="org-1",
        chain="base_sepolia",
        chain_id=84532,
        address=WALLET_ADDR,
        token_symbol="USDC",
        token_address="0x" + "d" * 40,
        token_decimals=6,
        auto_split="0x" + "5" * 40,
    )


@pytest.fixture
def state():
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except Exception:  # pragma: no cover
        pytest.skip("Redis is not reachable — the lock cannot be tested honestly")
    return KeeperState(client, max_consecutive_failures=5)


class Receipt:
    def __init__(self, block_number=1234, status=1):
        self.blockNumber = block_number
        self.status = status


class FakeChain:
    def __init__(self, *, balance=1_000_000, allowance=1_000_000, policy=POLICY):
        self._balance = balance
        self._allowance = allowance
        self._policy = policy
        self.confirm_blocks = []

    def get_policy(self, wallet, block_identifier=None):
        return self._policy

    def balance_of(self, wallet, block_identifier=None):
        self.confirm_blocks.append(block_identifier)
        return self._balance

    def allowance(self, wallet, block_identifier=None):
        return self._allowance

    def preview_split(self, wallet):
        total = min(self._balance, self._allowance)
        return (total, [total // 2, total - total // 2])


class FakeExecutor:
    def __init__(self, *, raises=None, receipt=None):
        self._raises = raises
        self._receipt = receipt or Receipt()
        self.calls = 0

    def execute_split(self, wallet):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._receipt


# ═══════════════════════════════════════════════════════════════
#  Nothing to do ⇒ nothing sent
# ═══════════════════════════════════════════════════════════════


def test_a_skip_never_touches_the_signer(wallet, state):
    """The strongest available statement that no gas was spent and the key was
    never used: the executor was not called at all."""
    executor = FakeExecutor()

    outcome = process_wallet(
        wallet, chain=FakeChain(balance=0), executor=executor, state=state
    )

    assert outcome.kind == OUTCOME_SKIPPED
    assert outcome.reason == SKIP_ZERO_AMOUNT
    assert executor.calls == 0


# ═══════════════════════════════════════════════════════════════
#  Two ticks, one winner
# ═══════════════════════════════════════════════════════════════


def test_two_overlapping_ticks_execute_once(wallet, state):
    """Real threads, real Redis, one lock. The second tick must not merely
    produce the same result — it must not SEND."""
    executor = FakeExecutor()
    outcomes = []
    append_lock = threading.Lock()

    # Deliberately NOT a Barrier. A barrier is cyclic, so the winner can clear
    # it, finish its whole tick and RELEASE the lock before the second thread
    # even attempts to acquire — at which point the second acquire succeeds and
    # the test proves nothing. Gate on both ACQUIRE ATTEMPTS having happened
    # instead: that is the moment the two ticks provably overlap.
    attempted = threading.Semaphore(0)
    release_winner = threading.Event()

    real_acquire = state.acquire

    def counting_acquire(w):
        handle = real_acquire(w)
        attempted.release()
        return handle

    state.acquire = counting_acquire

    class BlockingChain(FakeChain):
        def preview_split(self, w):
            release_winner.wait(timeout=5)
            return super().preview_split(w)

    def run():
        o = process_wallet(
            wallet, chain=BlockingChain(), executor=executor, state=state
        )
        with append_lock:
            outcomes.append(o)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    assert attempted.acquire(timeout=5), "first tick never tried to acquire"
    assert attempted.acquire(timeout=5), "second tick never tried to acquire"
    release_winner.set()
    for t in threads:
        t.join(timeout=10)

    kinds = sorted(o.kind for o in outcomes)
    assert kinds == [OUTCOME_EXECUTED, OUTCOME_LOCKED_OUT]
    assert executor.calls == 1, "the lock did not prevent a second send"


def test_the_lock_is_released_so_the_next_tick_can_run(wallet, state):
    executor = FakeExecutor()

    first = process_wallet(wallet, chain=FakeChain(), executor=executor, state=state)
    second = process_wallet(wallet, chain=FakeChain(), executor=executor, state=state)

    assert first.kind == OUTCOME_EXECUTED
    assert second.kind == OUTCOME_EXECUTED
    assert executor.calls == 2


def test_the_lock_is_released_even_when_the_send_fails(wallet, state):
    """A claim taken before the send must not outlive its failure — the exact
    trap webhook_service.py:1353 records having removed."""
    failing = FakeExecutor(raises=RuntimeError("reverted"))

    process_wallet(wallet, chain=FakeChain(), executor=failing, state=state)
    ok = FakeExecutor()
    outcome = process_wallet(wallet, chain=FakeChain(), executor=ok, state=state)

    assert outcome.kind == OUTCOME_EXECUTED


def test_release_only_deletes_our_own_lock(wallet, state):
    """Compare-and-delete. The one acquire/release lock in the backend releases
    with a bare DELETE and no ownership token, so a holder that overran its TTL
    deletes its successor's lock. Do not inherit that."""
    mine = state.acquire(wallet)
    assert mine is not None

    state._client.set(state.lock_key(wallet), "somebody-elses-token")
    state.release(mine)

    assert state._client.get(state.lock_key(wallet)) == "somebody-elses-token"


# ═══════════════════════════════════════════════════════════════
#  Failure ⇒ back off, on separate state
# ═══════════════════════════════════════════════════════════════


def test_a_failed_execute_backs_off_after_n_and_never_writes_disabled_at(wallet, state):
    """`disabled_at` is the MERCHANT's pause switch, surfaced in their
    dashboard. An operational back-off must stay distinguishable from a user
    action, so it lives in Redis under its own key. The keeper has no database
    connection at all — see test_no_database_authority.py — so this is
    structural, and the behavioural half is that the counter trips at N."""
    failing = FakeExecutor(raises=RuntimeError("execution reverted"))

    for i in range(5):
        outcome = process_wallet(
            wallet, chain=FakeChain(), executor=failing, state=state
        )
        assert outcome.kind == OUTCOME_FAILED, f"attempt {i}"

    assert state.is_backed_off(wallet) is True

    # Backed off ⇒ not attempted again, so no further gas is burned.
    after = process_wallet(wallet, chain=FakeChain(), executor=failing, state=state)
    assert after.kind == OUTCOME_BACKED_OFF
    assert failing.calls == 5


def test_success_resets_the_failure_counter(wallet, state):
    failing = FakeExecutor(raises=RuntimeError("boom"))
    for _ in range(4):
        process_wallet(wallet, chain=FakeChain(), executor=failing, state=state)
    assert state.is_backed_off(wallet) is False

    process_wallet(wallet, chain=FakeChain(), executor=FakeExecutor(), state=state)

    assert state.consecutive_failures(wallet) == 0


def test_a_skip_is_not_a_failure(wallet, state):
    """A wallet with nothing to distribute is the normal case, not a fault. If
    skips counted, every idle wallet would back itself off in five ticks."""
    for _ in range(6):
        process_wallet(
            wallet, chain=FakeChain(balance=0), executor=FakeExecutor(), state=state
        )

    assert state.is_backed_off(wallet) is False


# ═══════════════════════════════════════════════════════════════
#  Reading after a write
# ═══════════════════════════════════════════════════════════════


def test_the_confirming_read_is_anchored_to_the_receipt_block(wallet, state):
    """Reading at "latest" after a send can land on a replica behind the block
    that included the transaction — observed three times in manual testing. A
    node that has the receipt has the block, so anchoring to receipt.blockNumber
    is consistent by construction rather than a mitigation."""
    chain = FakeChain()
    executor = FakeExecutor(receipt=Receipt(block_number=987_654))

    process_wallet(wallet, chain=chain, executor=executor, state=state)

    assert 987_654 in chain.confirm_blocks, (
        f"confirming read was not anchored to the receipt block: {chain.confirm_blocks}"
    )
    assert "latest" not in chain.confirm_blocks


def test_the_receipt_block_is_remembered_for_the_next_tick(wallet, state):
    """The opposite replica hazard: a BEHIND node at the start of the next tick
    shows the pre-split balance, and the keeper re-executes a split that already
    happened. The lock cannot help — it was released."""
    process_wallet(
        wallet,
        chain=FakeChain(),
        executor=FakeExecutor(receipt=Receipt(block_number=555)),
        state=state,
    )

    assert state.last_block(wallet) == 555


def test_a_reverted_receipt_is_a_failure_not_a_success(wallet, state):
    """status == 0 means the transaction mined and reverted. A returned tx hash
    is not success."""
    executor = FakeExecutor(receipt=Receipt(status=0))

    outcome = process_wallet(
        wallet, chain=FakeChain(), executor=executor, state=state
    )

    assert outcome.kind == OUTCOME_FAILED
    assert state.consecutive_failures(wallet) == 1
