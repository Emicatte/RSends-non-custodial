"""Keeper configuration — environment only, fail-closed.

Deliberately NOT `app.config`. Importing it would pull the backend's production
guards into a service that has no Postgres, no JWT and no email: the keeper
would refuse to boot for missing things it does not use, and its deploy would be
coupled to the backend's.

Every required value raises at startup if absent. A keeper that boots with half
its configuration is a keeper that either does nothing quietly or signs with the
wrong key.
"""

import json
import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Startup configuration is missing or unusable."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"required environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class KeeperConfig:
    backend_url: str
    internal_secret: str
    environment: str
    rpc_urls: dict
    private_key: str
    redis_url: str
    tick_seconds: int
    max_consecutive_failures: int
    receipt_timeout: int

    @classmethod
    def from_env(cls) -> "KeeperConfig":
        environment = os.environ.get("KEEPER_ENVIRONMENT", "test").strip()
        if environment not in ("test", "live"):
            raise ConfigError(
                f"KEEPER_ENVIRONMENT must be 'test' or 'live', got {environment!r}"
            )

        raw_rpc = _require("KEEPER_RPC_URLS_JSON")
        try:
            parsed = json.loads(raw_rpc)
            rpc_urls = {int(k): str(v) for k, v in parsed.items()}
        except (ValueError, TypeError, AttributeError) as exc:
            raise ConfigError(
                "KEEPER_RPC_URLS_JSON must be a JSON object mapping chain id to "
                f'URL, e.g. {{"84532": "https://..."}} — {exc}'
            ) from exc
        if not rpc_urls:
            raise ConfigError("KEEPER_RPC_URLS_JSON is empty — no chain is reachable")

        return cls(
            backend_url=_require("KEEPER_BACKEND_URL"),
            # The same value as the backend's INTERNAL_PROXY_SECRET. Named
            # identically on purpose: a drift between the two is a silent 403,
            # and a differently-named variable makes that harder to spot.
            internal_secret=_require("INTERNAL_PROXY_SECRET"),
            environment=environment,
            rpc_urls=rpc_urls,
            # The gas key. Never logged, never echoed, and deliberately NOT part
            # of the shared Render env group — this service is the only thing in
            # the system that should be able to read it.
            private_key=_require("KEEPER_PRIVATE_KEY"),
            redis_url=_require("KEEPER_REDIS_URL"),
            tick_seconds=int(os.environ.get("KEEPER_TICK_SECONDS", "60")),
            max_consecutive_failures=int(
                os.environ.get("KEEPER_MAX_CONSECUTIVE_FAILURES", "5")
            ),
            receipt_timeout=int(os.environ.get("KEEPER_RECEIPT_TIMEOUT", "180")),
        )
