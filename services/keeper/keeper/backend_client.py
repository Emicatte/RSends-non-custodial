"""Fetch the work list from the backend's internal endpoint.

The keeper holds no database credentials, so this is the only way it learns
which wallets exist. The endpoint is exempt from API-KEY auth and gated by
`require_internal_secret` on its router; this secret is the only thing in front
of a deliberately cross-tenant read, so it is sent on every request and never
logged.

The response is trusted as data, not as instruction: every address is used only
as a call target the preflight then re-derives its decision from on chain.
"""

import logging

import httpx

from keeper.models import Wallet

log = logging.getLogger(__name__)

INTERNAL_SECRET_HEADER = "X-RSend-Internal-Secret"


class BackendUnavailable(Exception):
    """The work list could not be fetched. No list means no ticks — never a
    stale one: acting on a wallet the backend may since have paused is exactly
    what the pause switch exists to prevent."""


class BackendClient:
    def __init__(self, base_url: str, secret: str, *, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._secret = secret
        self._timeout = timeout

    def fetch_wallets(self, environment: str) -> list:
        url = f"{self._base_url}/api/internal/keeper/source-wallets"
        try:
            response = httpx.get(
                url,
                params={"environment": environment},
                headers={INTERNAL_SECRET_HEADER: self._secret},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            # 403 here means the secret drifted between the two services. Say so
            # explicitly: the symptom is otherwise "the keeper does nothing",
            # which looks identical to "no wallets are registered".
            if exc.response.status_code == 403:
                raise BackendUnavailable(
                    "backend rejected the internal secret (403) — "
                    "INTERNAL_PROXY_SECRET does not match between the keeper and "
                    "the backend"
                ) from exc
            raise BackendUnavailable(
                f"backend returned HTTP {exc.response.status_code}"
            ) from exc
        except Exception as exc:
            raise BackendUnavailable(str(exc)) from exc

        return [Wallet(**item) for item in payload.get("wallets", [])]
