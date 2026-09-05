"""The three-way RPC outcome, and the one backend error worth naming.

`tests/test_preflight.py` proves the keeper does the right thing GIVEN a
`PreviewReverted` or an `RpcUnavailable`. This file proves the real chain client
produces the right one — which is where the distinction is actually made, and
where collapsing it would be invisible until a live outage looked like a skip.
"""

import httpx
import pytest
from web3.exceptions import ContractLogicError

from keeper.backend_client import BackendClient, BackendUnavailable
from keeper.chain import Chain, PermanentRpcError, _classify
from keeper.models import Wallet
from keeper.preflight import PreviewReverted, RpcUnavailable

WALLET = Wallet(
    id="sw-1",
    org_id="org-1",
    chain="base_sepolia",
    chain_id=84532,
    address="0x" + "a" * 40,
    token_symbol="USDC",
    token_address="0x" + "d" * 40,
    token_decimals=6,
    auto_split="0x" + "5" * 40,
)


# ═══════════════════════════════════════════════════════════════
#  Transient vs permanent
# ═══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "message",
    [
        "Monthly capacity limit exceeded",
        "exceeded its compute units per second capacity",
        "daily request count exceeded",
        "rate limit exceeded",
        "429 Too Many Requests",
        "request is being throttled",
        "block range extends beyond current head block",
    ],
)
def test_quota_and_throttle_wordings_are_transient(message):
    """These all contain "exceed" or look like a bad request, and every one of
    them is an availability fault that the SAME call survives on retry. The
    2026-08-22 incident was exactly this misclassification: a quota 429 treated
    as permanent, so the breaker never opened and nothing alerted while a dead
    provider kept being asked for days."""
    assert isinstance(_classify(Exception(message)), RpcUnavailable)


@pytest.mark.parametrize(
    "message", ["invalid params: bad address", "the method eth_foo does not exist"]
)
def test_malformed_requests_are_permanent(message):
    """Retrying changes nothing — the request itself is wrong."""
    assert isinstance(_classify(Exception(message)), PermanentRpcError)


def test_an_unknown_fault_is_treated_as_transient():
    """The safe default. A transient misread costs one tick of latency; a
    permanent misread stops a merchant's distributions until someone notices."""
    assert isinstance(_classify(Exception("connection reset by peer")), RpcUnavailable)


# ═══════════════════════════════════════════════════════════════
#  A revert is an answer, not a fault
# ═══════════════════════════════════════════════════════════════


class _Call:
    def __init__(self, raises):
        self._raises = raises

    def call(self, block_identifier=None):
        raise self._raises


class _Functions:
    def __init__(self, raises):
        self._raises = raises

    def previewSplit(self, *_args):
        return _Call(self._raises)


class _Contract:
    def __init__(self, raises):
        self.functions = _Functions(raises)


class _Eth:
    def __init__(self, raises):
        self._raises = raises

    def contract(self, address=None, abi=None):
        return _Contract(self._raises)


class _W3:
    def __init__(self, raises):
        self.eth = _Eth(raises)


def test_a_contract_revert_becomes_PreviewReverted_not_RpcUnavailable():
    """The whole reason the keeper needs a three-way outcome. If this collapsed
    into RpcUnavailable, "this merchant has no policy" and "the node is down"
    would produce the same log line forever."""
    chain = Chain(_W3(ContractLogicError("execution reverted: NoPolicy()")))

    with pytest.raises(PreviewReverted):
        chain.preview_split(WALLET)


def test_a_transport_fault_during_preview_is_not_a_revert():
    chain = Chain(_W3(TimeoutError("read timed out")))

    with pytest.raises(RpcUnavailable):
        chain.preview_split(WALLET)


# ═══════════════════════════════════════════════════════════════
#  The backend client
# ═══════════════════════════════════════════════════════════════


def _client_with(handler):
    client = BackendClient("https://backend.example", "s" * 48)
    transport = httpx.MockTransport(handler)
    real_get = httpx.get

    def _get(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.get(url, **kwargs)

    return client, _get, real_get


def test_a_403_says_the_secret_drifted(monkeypatch):
    """A silent 403 makes the keeper do nothing, which looks exactly like every
    wallet being idle. Name the actual cause."""

    def handler(request):
        return httpx.Response(403, json={"detail": "forbidden"})

    client, fake_get, _ = _client_with(handler)
    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(BackendUnavailable) as exc:
        client.fetch_wallets("test")

    assert "INTERNAL_PROXY_SECRET" in str(exc.value)


def test_the_secret_is_sent_and_the_payload_is_parsed(monkeypatch):
    seen = {}

    def handler(request):
        seen["secret"] = request.headers.get("X-RSend-Internal-Secret")
        seen["environment"] = request.url.params.get("environment")
        return httpx.Response(
            200,
            json={
                "wallets": [
                    {
                        "id": "sw-1",
                        "org_id": "org-1",
                        "chain": "base_sepolia",
                        "chain_id": 84532,
                        "address": "0x" + "a" * 40,
                        "token_symbol": "USDC",
                        "token_address": "0x" + "d" * 40,
                        "token_decimals": 6,
                        "auto_split": "0x" + "5" * 40,
                    }
                ]
            },
        )

    client, fake_get, _ = _client_with(handler)
    monkeypatch.setattr(httpx, "get", fake_get)

    wallets = client.fetch_wallets("test")

    assert seen["secret"] == "s" * 48
    assert seen["environment"] == "test"
    assert [w.id for w in wallets] == ["sw-1"]
    assert wallets[0].chain_id == 84532


def test_an_unreachable_backend_raises_rather_than_returning_an_empty_list(monkeypatch):
    """An empty list and a failed fetch must not be the same value. Empty means
    "no wallets are registered"; failed means "we do not know", and the loop
    must not treat the second as the first."""

    def handler(request):
        raise httpx.ConnectError("connection refused")

    client, fake_get, _ = _client_with(handler)
    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(BackendUnavailable):
        client.fetch_wallets("test")
