"""The keeper loop.

Fetch the work list, process each wallet, sleep, repeat. Two properties the loop
itself is responsible for:

  • One bad wallet must not stop the others. `process_wallet` already converts
    every per-wallet exception into an Outcome, and the loop keeps going.
  • A failure to fetch the work list means NO ticks this round — never a stale
    list. Acting on a cached wallet the merchant has since paused is precisely
    what the pause switch exists to prevent.

Redis is required, not optional: without it there is no lock, and a keeper that
sends without a lock is the one failure mode that costs real money. So a Redis
outage skips the round entirely rather than degrading to "send anyway".
"""

import logging
import signal
import sys
import time
from collections import Counter

import redis as redis_lib
from web3 import Web3

from keeper.backend_client import BackendClient, BackendUnavailable
from keeper.chain import Chain
from keeper.config import ConfigError, KeeperConfig
from keeper.executor import Executor
from keeper.state import KeeperState
from keeper.tick import process_wallet

log = logging.getLogger("keeper")

_running = True


def _stop(signum, _frame):
    global _running
    log.info("keeper: received signal %s — finishing this round and exiting", signum)
    _running = False


def run_round(*, client, state, chains, executors, environment) -> Counter:
    wallets = client.fetch_wallets(environment)
    counts: Counter = Counter()

    for wallet in wallets:
        chain = chains.get(wallet.chain_id)
        executor = executors.get(wallet.chain_id)
        if chain is None or executor is None:
            # Configured chains are an operator decision; a wallet on a chain we
            # have no RPC for is not an error, but it must not be silent either.
            log.warning(
                "keeper: no RPC configured for chain_id=%s — skipping wallet %s",
                wallet.chain_id,
                wallet.id,
            )
            counts["unconfigured_chain"] += 1
            continue

        outcome = process_wallet(
            wallet, chain=chain, executor=executor, state=state
        )
        counts[outcome.kind] += 1

    return counts


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        config = KeeperConfig.from_env()
    except ConfigError as exc:
        log.critical("keeper: refusing to start — %s", exc)
        return 1

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    redis_client = redis_lib.Redis.from_url(config.redis_url, decode_responses=True)
    state = KeeperState(
        redis_client, max_consecutive_failures=config.max_consecutive_failures
    )
    client = BackendClient(config.backend_url, config.internal_secret)

    chains, executors = {}, {}
    for chain_id, url in config.rpc_urls.items():
        w3 = Web3(Web3.HTTPProvider(url))
        chains[chain_id] = Chain(w3)
        executors[chain_id] = Executor(
            w3, config.private_key, receipt_timeout=config.receipt_timeout
        )

    # The address, never the key — the one thing about this account worth
    # logging, and the operator needs it to fund the thing.
    any_executor = next(iter(executors.values()))
    log.info(
        "keeper: started environment=%s chains=%s gas_account=%s",
        config.environment,
        sorted(chains),
        any_executor.address,
    )

    while _running:
        started = time.monotonic()
        try:
            counts = run_round(
                client=client,
                state=state,
                chains=chains,
                executors=executors,
                environment=config.environment,
            )
            log.info("keeper: round complete %s", dict(counts))
        except BackendUnavailable as exc:
            # No list ⇒ no ticks. Loud, because the keeper doing nothing looks
            # exactly like every wallet being idle.
            log.error("keeper: could not fetch the work list — %s", exc)
        except redis_lib.RedisError as exc:
            log.error("keeper: Redis unavailable — skipping round entirely: %s", exc)
        except Exception:  # noqa: BLE001 — the loop outlives any one round
            log.exception("keeper: unexpected error in round")

        elapsed = time.monotonic() - started
        remaining = config.tick_seconds - elapsed
        while remaining > 0 and _running:
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

    log.info("keeper: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
