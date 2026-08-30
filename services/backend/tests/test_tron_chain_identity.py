"""TRON chain identity — PROVEN from the genesis block, not declared.

Nothing calls `assert_tron_chain_identity` yet; the watch-only poller will. The
guard exists first, and with teeth, because the failure it prevents is silent:
a TRON node URL carries no proof of which network it serves, and every
downstream key — the poller cursor, the test/live stamp, the address a payer is
told to send TRX/USDT to — is derived from the assumption that it is mainnet.

Contract pinned here:

  - `assert_tron_chain_identity(node_url, network)` POSTs `{"num": 0}` to
    `{node_url}/wallet/getblockbynum` ONCE and compares the returned `blockID`
    with the genesis constant registered under `network`.
  - It RAISES. It does not return a bool. `isTronFeeRouterAvailable()` returned
    `True` for the literal string `'T_INDIRIZZO_DAL_DEPLOY'`; a guard whose
    result can be ignored will be ignored.
  - It reads the node URL AND the network from its ARGUMENTS and reads no
    configuration: no env var, and above all no matching on the host string.
    The deleted `useTronWallet.ts` decided mainnet-vs-testnet by matching the
    URL host — that is the anti-pattern this replaces. Two networks make the
    distinction load-bearing rather than theoretical: the caller must SAY which
    network it expects, and neither network accepts the other's genesis.
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
    TRON_NILE_GENESIS_BLOCK_ID,
    TronChainIdentityError,
    assert_tron_chain_identity,
)

NODE = "https://api.trongrid.io"

# Byte-identical restatements of the constants, independent of the module, so a
# silent edit to a source constant fails here rather than in production.
EXPECTED_GENESIS = (
    "00000000000000001ebf88508a03865c71d452e25f4d51194196a1d22b6653dc"
)
EXPECTED_NILE_GENESIS = (
    "0000000000000000d698d4192c56cb6be724a558448e2684802de4d6cd8690dc"
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


def test_the_pinned_nile_constant_is_byte_identical_to_the_verified_genesis():
    """Verified 2026-08-29 against nile.trongrid.io. ONE source, unlike mainnet's
    three — acceptable on a testnet precisely because a wrong constant makes the
    poller refuse to start rather than index the wrong chain."""
    assert TRON_NILE_GENESIS_BLOCK_ID == EXPECTED_NILE_GENESIS
    assert tci.TRON_GENESIS_BLOCK_IDS["nile"] == EXPECTED_NILE_GENESIS


def test_the_last_four_bytes_of_the_nile_genesis_are_niles_chain_id():
    """3448148188 derives from this hash — the same cross-check as mainnet's,
    and the number the Nile cursor row and settlement rows are keyed on."""
    assert int(TRON_NILE_GENESIS_BLOCK_ID[-8:], 16) == 3448148188


def test_the_two_networks_are_distinct_entries():
    """Not a refactor of one constant into a parameterised one: two networks,
    two independently verified hashes, two chain ids."""
    assert set(tci.TRON_GENESIS_BLOCK_IDS) == {"mainnet", "nile"}
    assert TRON_MAINNET_GENESIS_BLOCK_ID != TRON_NILE_GENESIS_BLOCK_ID


def test_shasta_is_still_deliberately_absent():
    """An unverified genesis is worse than an absent one: it would make the
    guard pass for the wrong reason. Shasta gets an entry when someone verifies
    it, not before."""
    assert "shasta" not in tci.TRON_GENESIS_BLOCK_IDS


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

    await assert_tron_chain_identity(NODE, "mainnet")  # must NOT raise

    assert posts == [(f"{NODE}/wallet/getblockbynum", {"num": 0})]


@pytest.mark.asyncio
async def test_the_nile_genesis_block_proves_nile(monkeypatch):
    posts = _stub_transport(monkeypatch, _ok(EXPECTED_NILE_GENESIS))

    await assert_tron_chain_identity(NODE, "nile")  # must NOT raise

    assert posts == [(f"{NODE}/wallet/getblockbynum", {"num": 0})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network,other_genesis",
    [("mainnet", EXPECTED_NILE_GENESIS), ("nile", EXPECTED_GENESIS)],
)
async def test_neither_network_accepts_the_others_genesis(
    monkeypatch, network, other_genesis
):
    """THE test for a second network. Both answers are real, well formed and
    height zero — the only thing separating them is which network the caller
    said it expected. A node pointed at the wrong one is refused in BOTH
    directions: a Nile node silently accepted as mainnet would record testnet
    play money as live payments, and a mainnet node accepted as Nile would key
    real transfers to the testnet cursor."""
    _stub_transport(monkeypatch, _ok(other_genesis))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, network)


@pytest.mark.asyncio
async def test_an_unregistered_network_is_fatal_not_a_key_error(monkeypatch):
    """A typo'd network name must fail the way every other unproven chain
    fails, through the one exception callers already handle. A KeyError would
    escape `except TronChainIdentityError` at the boot site and surface as an
    unhandled crash instead of the deliberate SystemExit."""
    _stub_transport(monkeypatch, _ok(EXPECTED_GENESIS))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "shasta")


@pytest.mark.asyncio
async def test_a_different_chains_genesis_is_fatal(monkeypatch):
    """Well formed, height zero, and neither of the two registered networks."""
    other = "0" * 16 + "dead" + "0" * 44
    assert len(other) == 64 and other not in (EXPECTED_GENESIS, EXPECTED_NILE_GENESIS)
    _stub_transport(monkeypatch, _ok(other))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


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
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_block_id_that_is_not_32_bytes_of_hex_is_fatal(monkeypatch):
    for bad in ("0" * 63, "0" * 65, "0" * 16 + "z" * 48, "", 12345, None):
        _stub_transport(monkeypatch, _ok(bad))
        with pytest.raises(TronChainIdentityError):
            await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_missing_block_id_key_is_fatal(monkeypatch):
    """TronGrid answers an unknown request with a 200 and no blockID."""
    _stub_transport(monkeypatch, _Resp({"Error": "class java.lang.NullPointer"}))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_non_object_body_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, _Resp(["not", "an", "object"]))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_malformed_json_is_fatal(monkeypatch):
    _stub_transport(
        monkeypatch,
        _Resp(json_exc=json.JSONDecodeError("Expecting value", "<html>502</html>", 0)),
    )

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_non_200_response_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, _Resp({"blockID": EXPECTED_GENESIS}, status_code=429))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_transport_error_is_fatal(monkeypatch):
    """Deliberately the OPPOSITE of `check_webhook_egress`, where an
    unreachable host is safe because it cannot reach anything internal. Here an
    unreachable node proves nothing, and an unproven chain is not a safe one."""
    _stub_transport(monkeypatch, httpx.ConnectError("nodename nor servname provided"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_a_timeout_is_fatal(monkeypatch):
    _stub_transport(monkeypatch, httpx.ReadTimeout("timed out"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


@pytest.mark.asyncio
async def test_failure_is_a_single_attempt_not_a_retry_loop(monkeypatch):
    """A guard that retries until success is a guard that hangs a boot."""
    posts = _stub_transport(monkeypatch, httpx.ConnectError("refused"))

    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")

    assert len(posts) == 1, posts


@pytest.mark.asyncio
async def test_it_raises_rather_than_returning_a_falsy_value(monkeypatch):
    """The `isTronFeeRouterAvailable()` failure mode: a bool result invites a
    caller to ignore it. On success the function returns None, so there is
    nothing to test truthiness against."""
    _stub_transport(monkeypatch, _ok(EXPECTED_GENESIS))
    assert await assert_tron_chain_identity(NODE, "mainnet") is None

    _stub_transport(monkeypatch, _ok("0" * 64))
    with pytest.raises(TronChainIdentityError):
        await assert_tron_chain_identity(NODE, "mainnet")


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

    # Signature: the node URL, the network to prove, and a transport timeout.
    # Nothing else, and no boolean whose default could turn the guard off.
    # `network` carries NO default: a caller that does not say which network it
    # expects gets a TypeError, never a silent mainnet assumption.
    params = inspect.signature(assert_tron_chain_identity).parameters
    assert list(params) == ["node_url", "network", "timeout"], list(params)
    assert params["network"].default is inspect.Parameter.empty
    for p in params.values():
        assert not isinstance(p.default, bool), f"{p.name} is a boolean switch"

    # The guard reads no configuration at all — not settings, not the env, and
    # it does not infer the network from the URL it was handed.
    src = inspect.getsource(assert_tron_chain_identity)
    for forbidden in ("get_settings", "os.environ", "getenv", "settings."):
        assert forbidden not in src, f"the guard reads configuration: {forbidden!r}"

    # No host-string matching — the `useTronWallet.ts` anti-pattern. Note this
    # forbids naming the networks AT ALL inside the guard, docstring included:
    # the network arrives as an argument and is looked up in the registry, so
    # there is nothing for the function body to know about Nile or Shasta.
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
