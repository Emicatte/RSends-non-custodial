"""TRON chain identity — PROVEN from the genesis block, not declared.

Nothing calls `assert_tron_chain_identity` yet; the watch-only poller will. The
guard exists first, and with teeth, because the failure it prevents is silent:
a TRON node URL carries no proof of which network it serves, and every
downstream key — the poller cursor, the test/live stamp, the address a payer is
told to send TRX/USDT to — is derived from the assumption that it is mainnet.

Contract pinned here:

  - `assert_tron_chain_identity(node_url)` POSTs `{"num": 0}` to
    `{node_url}/wallet/getblockbynum` ONCE and compares the returned `blockID`
    with the pinned mainnet genesis constant.
  - It RAISES. It does not return a bool. `isTronFeeRouterAvailable()` returned
    `True` for the literal string `'T_INDIRIZZO_DAL_DEPLOY'`; a guard whose
    result can be ignored will be ignored.
  - It reads the node URL from its ARGUMENT and reads no configuration: no
    network flag, no env var, no matching on the host string. The deleted
    `useTronWallet.ts` decided mainnet-vs-testnet by matching the URL host —
    that is the anti-pattern this replaces.
  - Every failure mode is the SAME failure: unreachable, timeout, non-200,
    malformed JSON, missing `blockID`, a `blockID` that is not 32 bytes of hex,
    a `blockID` whose first 16 hex chars are not zero (height 0 is structural —
    the first 8 bytes of a TRON blockID are the block number, big-endian), and
    a well-formed `blockID` that is simply a different chain's. An unproven
    chain is not a safe chain.
  - No configuration surface can disable it — same shape as
    `test_chain_identity_guard.py::test_no_configuration_surface_can_disable_chain_identity`.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_tron_chain_identity.py -v
"""

import inspect
import json

import httpx
import pytest

from app.services import tron_chain_identity as tci
from app.services.tron_chain_identity import (
    TRON_MAINNET_GENESIS_BLOCK_ID,
    TronChainIdentityError,
    assert_tron_chain_identity,
)

NODE = "https://api.trongrid.io"

# Byte-identical restatement of the constant, independent of the module, so a
# silent edit to the source constant fails here rather than in production.
EXPECTED_GENESIS = (
    "00000000000000001ebf88508a03865c71d452e25f4d51194196a1d22b6653dc"
)


# ═══════════════════════════════════════════════════════════════
#  HTTP boundary doubles — the suite never touches the network
# ═══════════════════════════════════════════════════════════════

class _Resp:
    """Minimal stand-in for `httpx.Response`."""

    def __init__(self, payload=None, *, status_code=200, json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _stub_transport(monkeypatch, outcome):
    """Replace `httpx.AsyncClient` for the duration of one test.

    `outcome` is either a `_Resp` to return or an exception to raise from
    `.post()`. Returns the list of `(url, json_body)` posts, so a test can
    assert the endpoint, the payload, and that exactly ONE attempt was made.
    """
    posts: list[tuple[str, object]] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kwargs):
            posts.append((url, json))
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(tci.httpx, "AsyncClient", _Client)
    return posts


def _ok(block_id: str) -> _Resp:
    """A getblockbynum(0) response shaped like TronGrid's."""
    return _Resp(
        {
            "blockID": block_id,
            "block_header": {"raw_data": {"number": 0, "timestamp": 0}},
        }
    )


# ═══════════════════════════════════════════════════════════════
#  The constant
# ═══════════════════════════════════════════════════════════════

def test_the_pinned_constant_is_byte_identical_to_the_verified_genesis():
    """Verified 2026-08-28 against TronGrid, TronStack and tronscan.org."""
    assert TRON_MAINNET_GENESIS_BLOCK_ID == EXPECTED_GENESIS
    assert tci.TRON_GENESIS_BLOCK_IDS["mainnet"] == EXPECTED_GENESIS


def test_the_last_four_bytes_of_the_genesis_are_trons_chain_id():
    """728126428 derives from this hash — a cheap cross-check of the constant."""
    assert int(TRON_MAINNET_GENESIS_BLOCK_ID[-8:], 16) == 728126428


def test_every_registered_network_genesis_is_a_height_zero_block_id():
    """A second network is a new entry, not a refactor — and must be as well
    formed as this one. No entry may be invented without being verified: a
    wrong testnet genesis is worse than an absent one."""
    for network, block_id in tci.TRON_GENESIS_BLOCK_IDS.items():
        assert len(block_id) == 64, network
        int(block_id, 16)  # hex or ValueError
        assert block_id[:16] == "0" * 16, network


# ═══════════════════════════════════════════════════════════════
#  The proof
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_genesis_block_proves_the_chain(monkeypatch):
    posts = _stub_transport(monkeypatch, _ok(EXPECTED_GENESIS))

    await assert_tron_chain_identity(NODE)  # must NOT raise

    assert posts == [(f"{NODE}/wallet/getblockbynum", {"num": 0})]


@pytest.mark.asyncio
async def test_a_different_chains_genesis_is_fatal(monkeypatch):
    """Well formed, height zero, and simply not TRON mainnet."""
    other = "0" * 16 + "dead" + "0" * 44
    assert len(other) == 64 and other != EXPECTED_GENESIS
    _stub_transport(monkeypatch, _ok(other))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_block_id_that_is_not_height_zero_is_fatal(monkeypatch):
    """The first 8 bytes are the block number, big-endian. A node that answers
    getblockbynum(0) with a non-zero height is not answering our question,
    even when the remaining 24 bytes match the pinned hash.

    The message is asserted because the equality check would reject this value
    anyway: without it, this test would pass with the structural check deleted,
    and the height rule would be pinned by nothing. Only the attribution tells
    the two branches apart."""
    not_genesis = "000000000000000f" + EXPECTED_GENESIS[16:]
    assert not_genesis[16:] == EXPECTED_GENESIS[16:]
    _stub_transport(monkeypatch, _ok(not_genesis))

    with pytest.raises(TronChainIdentityError, match="block height 0"):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_block_id_that_is_not_32_bytes_of_hex_is_fatal(monkeypatch):
    for bad in ("0" * 63, "0" * 65, "0" * 16 + "z" * 48, "", 12345, None):
        _stub_transport(monkeypatch, _ok(bad))
        with pytest.raises(TronChainIdentityError):
            await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_missing_block_id_key_is_fatal(monkeypatch):
    """TronGrid answers an unknown request with a 200 and no blockID."""
    _stub_transport(monkeypatch, _Resp({"Error": "class java.lang.NullPointer"}))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_non_object_body_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, _Resp(["not", "an", "object"]))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_malformed_json_is_fatal(monkeypatch):
    _stub_transport(
        monkeypatch,
        _Resp(json_exc=json.JSONDecodeError("Expecting value", "<html>502</html>", 0)),
    )

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_non_200_response_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, _Resp({"blockID": EXPECTED_GENESIS}, status_code=429))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_transport_error_is_fatal(monkeypatch):
    """Deliberately the OPPOSITE of `check_webhook_egress`, where an
    unreachable host is safe because it cannot reach anything internal. Here an
    unreachable node proves nothing, and an unproven chain is not a safe one."""
    _stub_transport(monkeypatch, httpx.ConnectError("nodename nor servname provided"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_a_timeout_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, httpx.ReadTimeout("timed out"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


@pytest.mark.asyncio
async def test_failure_is_a_single_attempt_not_a_retry_loop(monkeypatch):
    """A guard that retries until success is a guard that hangs a boot."""
    posts = _stub_transport(monkeypatch, httpx.ConnectError("refused"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)

    assert len(posts) == 1, posts


@pytest.mark.asyncio
async def test_it_raises_rather_than_returning_a_falsy_value(monkeypatch):
    """The `isTronFeeRouterAvailable()` failure mode: a bool result invites a
    caller to ignore it. On success the function returns None, so there is
    nothing to test truthiness against."""
    _stub_transport(monkeypatch, _ok(EXPECTED_GENESIS))
    assert await assert_tron_chain_identity(NODE) is None

    _stub_transport(monkeypatch, _ok("0" * 64))
    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE)


# ═══════════════════════════════════════════════════════════════
#  No off switch
# ═══════════════════════════════════════════════════════════════

def test_no_configuration_surface_can_disable_tron_chain_identity():
    """Same discipline as the EVM guard: there must be no way to turn this off.

    Precedent: `security/auth.py` returns a checksummed address and RETURNS
    before ever reaching its regex gate, because someone wanted a debug bypass.
    A guard with an off switch is a guard that will be off.
    """
    from app import config as config_mod

    # Signature: the node URL and a transport timeout. Nothing else, and no
    # boolean whose default could turn the guard off.
    params = inspect.signature(assert_tron_chain_identity).parameters
    assert list(params) == ["node_url", "timeout"], list(params)
    for p in params.values():
        assert not isinstance(p.default, bool), f"{p.name} is a boolean switch"

    # The guard reads no configuration at all — not settings, not the env, and
    # it does not infer the network from the URL it was handed.
    src = inspect.getsource(assert_tron_chain_identity)
    for forbidden in ("get_settings", "os.environ", "getenv", "settings."):
        assert forbidden not in src, f"the guard reads configuration: {forbidden!r}"

    # No host-string matching — the `useTronWallet.ts` anti-pattern.
    for forbidden in ("trongrid", "nile", "shasta", "hostname", "urlparse"):
        assert forbidden not in src.lower(), f"the guard matches on the URL: {forbidden!r}"

    # The module itself imports no configuration.
    module_src = inspect.getsource(tci)
    assert "app.config" not in module_src
    assert "from app import config" not in module_src

    # And config.py has not grown a knob for it.
    config_src = inspect.getsource(config_mod).lower()
    for token in ("tron_chain", "tron_genesis", "skip_tron", "verify_tron"):
        assert token not in config_src, f"config.py grew a {token!r} surface"
