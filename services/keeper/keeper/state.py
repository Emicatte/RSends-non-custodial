"""The keeper's only mutable state, all of it in Redis.

Four keys per wallet, colon-namespaced in the repo's convention:

    keeper:lock:{chain}:{wallet_id}       tick lock, token-valued
    keeper:lastblock:{chain}:{wallet_id}  last receipt block we observed
    keeper:fails:{chain}:{wallet_id}      consecutive failures
    keeper:backoff:{chain}:{wallet_id}    set once the counter trips

None of this is in the database, and that is the design rather than a
convenience. The obvious place to record "stop trying this wallet" is
`source_wallets.disabled_at` — and it is the wrong place, because that column is
the MERCHANT's pause switch, surfaced in their dashboard. An operational
back-off written there would be indistinguishable from a user action, in both
directions.

Accepted trade-off: Redis loss forgets the back-off, so a broken wallet is
retried once after recovery. That is bounded (gas only), and Redis loss already
means no lock, which already means no tick runs at all.

The lock releases with a COMPARE-AND-DELETE. The one acquire/release lock in the
backend (`app/middleware/idempotency.py`) releases with a bare `DELETE` and no
ownership token, so a holder that overran its TTL deletes its successor's lock.
That is a real bug to not inherit, and the fix needs the delete and the
comparison to be one operation — hence the Lua script, the first in this repo.
"""

import logging
import secrets
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

#: Comfortably longer than a tick's worst case (preflight + send + receipt
#: wait), so the lock never expires under a keeper that is still working. It is
#: a crash-recovery bound, not a timeout.
LOCK_TTL_SECONDS = 600

#: Long enough that a wallet failing once an hour still accumulates, short
#: enough that a fixed problem forgets itself.
FAILURE_TTL_SECONDS = 86_400
BACKOFF_TTL_SECONDS = 86_400
LAST_BLOCK_TTL_SECONDS = 86_400

#: Delete the key only if it still holds OUR token. KEYS[1] = key,
#: ARGV[1] = token. Returns 1 if we released our own lock, 0 if someone else's
#: lock was there (ours had already expired).
_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


@dataclass(frozen=True)
class LockHandle:
    key: str
    token: str


class KeeperState:
    def __init__(self, client, *, max_consecutive_failures: int = 5):
        self._client = client
        self._max_failures = max_consecutive_failures
        self._release_script = client.register_script(_RELEASE_IF_OWNER)

    # ── Keys ──────────────────────────────────────────────────

    def lock_key(self, wallet) -> str:
        return f"keeper:lock:{wallet.chain}:{wallet.id}"

    def _fails_key(self, wallet) -> str:
        return f"keeper:fails:{wallet.chain}:{wallet.id}"

    def _backoff_key(self, wallet) -> str:
        return f"keeper:backoff:{wallet.chain}:{wallet.id}"

    def _last_block_key(self, wallet) -> str:
        return f"keeper:lastblock:{wallet.chain}:{wallet.id}"

    # ── The lock ──────────────────────────────────────────────

    def acquire(self, wallet) -> Optional[LockHandle]:
        """Claim this wallet for this tick, or return None if someone else has.

        The boolean return of SET NX is the claim — the repo's idiom
        (`idempotency_service.claim_tx_processed`). The value is a random token
        so `release` can prove ownership.
        """
        key = self.lock_key(wallet)
        token = secrets.token_hex(16)
        if self._client.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
            return LockHandle(key=key, token=token)
        return None

    def release(self, handle: LockHandle) -> None:
        try:
            self._release_script(keys=[handle.key], args=[handle.token])
        except Exception as exc:  # pragma: no cover — Redis died mid-tick
            # Not fatal: the TTL will clear it. Losing the release costs one
            # wallet one tick of latency; raising here would lose the outcome.
            log.warning("keeper: lock release failed for %s: %s", handle.key, exc)

    # ── Failure accounting ────────────────────────────────────

    def consecutive_failures(self, wallet) -> int:
        raw = self._client.get(self._fails_key(wallet))
        return int(raw) if raw else 0

    def is_backed_off(self, wallet) -> bool:
        return bool(self._client.exists(self._backoff_key(wallet)))

    def record_failure(self, wallet, reason: str) -> int:
        """Count the failure and, at the threshold, stop attempting this wallet.

        The CRITICAL fires exactly ONCE, at `== max`, not `>=` — the shape of
        `payment_indexer._note_failure`. A stuck wallet that screams every tick
        trains everyone to ignore it.
        """
        key = self._fails_key(wallet)
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, FAILURE_TTL_SECONDS)
        count = int(pipe.execute()[0])

        if count == self._max_failures:
            self._client.set(
                self._backoff_key(wallet), reason[:200], ex=BACKOFF_TTL_SECONDS
            )
            log.critical(
                "KEEPER_WALLET_BACKED_OFF wallet=%s org=%s chain=%s token=%s after "
                "%d consecutive failures — no further executeSplit will be attempted "
                "for it until this clears; other wallets are unaffected. Last error: %s",
                wallet.id,
                wallet.org_id,
                wallet.chain,
                wallet.token_symbol,
                count,
                reason,
            )
        else:
            log.error(
                "keeper: executeSplit failed for wallet=%s (consecutive=%d): %s",
                wallet.id,
                count,
                reason,
            )
        return count

    def record_success(self, wallet, block_number: int) -> None:
        pipe = self._client.pipeline()
        pipe.delete(self._fails_key(wallet))
        pipe.delete(self._backoff_key(wallet))
        pipe.set(
            self._last_block_key(wallet), int(block_number), ex=LAST_BLOCK_TTL_SECONDS
        )
        pipe.execute()

    # ── Replica-lag floor ─────────────────────────────────────

    def last_block(self, wallet) -> Optional[int]:
        """The block of the last receipt WE saw for this wallet.

        Guards the opposite replica hazard from the post-send read: at the start
        of a later tick a node that is BEHIND still shows the pre-split balance,
        and the keeper would re-execute a split that already happened. Reading no
        older than this block makes that impossible.
        """
        raw = self._client.get(self._last_block_key(wallet))
        return int(raw) if raw else None
