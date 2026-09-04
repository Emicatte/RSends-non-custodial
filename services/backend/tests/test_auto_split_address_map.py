"""AUTO_SPLIT_ADDRESSES_JSON — the operator env flip, and every way it stays shut.

`auto_split_address_for` was built as a deliberate seam returning None for every
chain (`source_wallet_service.py`, "THE SEAM"), so the whole source-wallet
surface 422s `AUTO_SPLIT_UNAVAILABLE` until an operator wires the address map.
This module wires it, following the `SPLIT_ROUTER_ADDRESSES_JSON` three-layer
pattern — raw settings field -> parsed property -> resolver — and pins that
opening ONE chain does not open any other.

KEYED BY CHAIN NAME, not by EVM chain id, and that is the one place this map
deliberately diverges from the three router maps it otherwise copies. AutoSplit
runs on TRON as well as Base, and TRON has no EVM chain id to key by — nor may
it be given a synthetic one, because `728126428` in an EVM chain table starts a
PaymentWatcher against a non-EVM node and SystemExits the boot
(`test_tron_poller.py:790`). The name is the registry's own vocabulary:
`token_registry.json` already keys `tron` and `tron_nile` that way.

THE MAP IS THE GATE. Being `settlement: watch_only` does NOT make a chain
ineligible — that field describes settlement routing for the payment path, not
whether a merchant may point a keeper at their own wallet. So `tron` and
`tron_nile` resolve exactly like `base` and `base_sepolia` when configured, and
refuse exactly like them when absent.

Fail-closed matrix. Every one of these must resolve to None, never to a guessed
default:

  - env var unset                    (the shipping state; deploying late is safe)
  - malformed JSON                   (+ a WARNING naming the var, never silence)
  - valid JSON, not an object        (+ the same WARNING)
  - a chain the registry has never heard of
  - a chain in the map but ABSENT from the token registry (`arbitrum` — it has a
    chain id but no settlement path at all)
  - a chain keyed by its NUMERIC id rather than its name — the map moved
    vocabulary, and a stale chain-id key must fail closed rather than resolve
  - an address that is ALSO in a router map — the indexer builds its log filters
    from those chain sets, so it would fetch every SplitExecuted and then drop
    it with a WARNING per execution. The contract deploy script says "NEVER add
    this address to RSENDS_ROUTER_*_ADDRESSES_JSON"; this is that sentence made
    enforceable instead of hoped for.

EVERY NEGATIVE HAS A POSITIVE CONTROL IN THE SAME ENVIRONMENT. Without one, a
key-vocabulary change makes the whole file resolve to None for every reason at
once, and each `is None` assertion keeps passing while proving nothing — which
would silently gut the collision guards, the tests that protect the indexer.

Two idioms, both borrowed rather than invented:
  - parser tests construct `Settings(auto_split_addresses_json=...)` directly
    (test_router_config_fail_closed.py) — no env, no cache;
  - resolver tests patch the raw string on the cached settings instance
    (test_intent_split_gate.py::split_enabled). `get_settings()` is @lru_cache'd
    but the parsed map is a @property that re-parses per access, so patching the
    string is enough and NO test clears the cache.

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_auto_split_address_map.py -v
"""

import logging
from types import SimpleNamespace

import pytest

from app.config import Settings, get_settings
from app.services.router_registry import (
    chain_id_for,
    chain_is_supported,
    is_watch_only_chain,
)
from app.services.source_wallet_service import auto_split_address_for

# Letter-bearing on purpose: an all-digit address makes every case-folding
# assertion below vacuously true (`"0x333…".upper() == "0x333…".lower()`), so a
# case-SENSITIVE collision compare would slip through the pin unnoticed.
AUTOSPLIT = "0xAaBbCcDdEeFf00112233445566778899aAbBcCdD"
# A TRON AutoSplit deploy is a base58check address, not an 0x one — the map
# carries whatever the chain's address family is, and never parses it.
AUTOSPLIT_TRON = "TUxpshC4JxPWPP7pFmpF84Co87nguRMudb"
MALFORMED = '{"base_sepolia": "0xdeadbeef"'    # unterminated object
NOT_AN_OBJECT = '["base_sepolia"]'             # valid JSON, wrong shape

EVM_CHAIN = "base_sepolia"
TRON_TESTNET = "tron_nile"
TRON_MAINNET = "tron"

# The conftest suite fixture routes 84532 and 8453 to these; a collision with
# either is the misconfiguration this module refuses.
CONFTEST_ROUTER_84532 = "0x1111111111111111111111111111111111111111"


@pytest.fixture
def auto_split_json(monkeypatch):
    """Set AUTO_SPLIT_ADDRESSES_JSON as the operator would, on the live settings.

    Patches the RAW string, not the parsed map: the property re-parses on every
    access, so this exercises the real parse path rather than smuggling a dict
    past it.
    """

    def _set(raw: str):
        monkeypatch.setattr(get_settings(), "auto_split_addresses_json", raw)

    return _set


def _one(chain: str, address: str = AUTOSPLIT) -> str:
    """A one-entry map, keyed by chain NAME."""
    return '{"' + chain + '": "' + address + '"}'


# ═══════════════════════════════════════════════════════════════
#  Layer 2 — the parser, parity with the three router maps
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [MALFORMED, NOT_AN_OBJECT], ids=["unparseable", "wrong-shape"])
def test_malformed_map_warns_and_is_empty(caplog, bad):
    """Present but unparseable must never be silence — a typo'd var would
    otherwise disable the whole feature with no log line naming the cause."""
    s = Settings(auto_split_addresses_json=bad)

    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert s.auto_split_addresses == {}

    assert any(
        "AUTO_SPLIT_ADDRESSES_JSON" in r.message.upper() for r in caplog.records
    ), [r.message for r in caplog.records]


def test_empty_map_does_not_warn(caplog):
    """Unset is the normal dev/test state — it must stay quiet at the parser."""
    s = Settings(auto_split_addresses_json="")

    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert s.auto_split_addresses == {}

    assert caplog.records == []


def test_wellformed_map_parses_and_is_quiet(caplog):
    s = Settings(auto_split_addresses_json=_one(EVM_CHAIN))

    with caplog.at_level(logging.WARNING, logger="app.config"):
        parsed = s.auto_split_addresses

    assert parsed == {EVM_CHAIN: AUTOSPLIT}
    assert caplog.records == []


def test_the_parser_does_not_touch_a_base58_address(caplog):
    """A TRON entry survives the parse byte-identical.

    `_parse_json_map` is deliberately format-agnostic — no checksum, no
    lowercasing, not even a 0x check — which is what lets one map carry both
    address families. Pinned because a "helpful" `.lower()` added there would
    destroy a T-address rather than merely change it.
    """
    s = Settings(auto_split_addresses_json=_one(TRON_TESTNET, AUTOSPLIT_TRON))

    with caplog.at_level(logging.WARNING, logger="app.config"):
        parsed = s.auto_split_addresses

    assert parsed == {TRON_TESTNET: AUTOSPLIT_TRON}
    assert parsed[TRON_TESTNET] != AUTOSPLIT_TRON.lower()
    assert caplog.records == []


# ═══════════════════════════════════════════════════════════════
#  Layer 3 — the resolver opens exactly the chains named
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "chain,address",
    [
        (EVM_CHAIN, AUTOSPLIT),
        (TRON_TESTNET, AUTOSPLIT_TRON),
        (TRON_MAINNET, AUTOSPLIT_TRON),
    ],
    ids=["base_sepolia", "tron_nile", "tron"],
)
def test_a_configured_chain_resolves_by_name(auto_split_json, chain, address):
    """The whole point of the branch: a chain named in the map answers with the
    configured address, and with THAT address, not a default.

    All three chains are here because Auto Split is not EVM-only. TRON's two
    networks are eligible exactly as Base's are; which of them is live is the
    operator's env, not a property the code decides.
    """
    auto_split_json(_one(chain, address))

    assert auto_split_address_for(chain) == address


@pytest.mark.parametrize(
    "chain", [EVM_CHAIN, TRON_TESTNET, TRON_MAINNET],
    ids=["base_sepolia", "tron_nile", "tron"],
)
def test_a_chain_absent_from_the_map_resolves_to_none(auto_split_json, chain):
    """…and the same three chains refuse when the operator has not named them.

    The control is what makes this non-vacuous: a DIFFERENT chain is configured
    in the same environment, so `None` here means "not in the map" rather than
    "the map is broken" or "nothing resolves any more".
    """
    other = "base" if chain != "base" else EVM_CHAIN
    auto_split_json(_one(other))

    assert auto_split_address_for(other) == AUTOSPLIT   # control: the map works
    assert auto_split_address_for(chain) is None


def test_a_chain_id_key_does_not_resolve(auto_split_json):
    """The vocabulary moved, and a stale numeric key must fail CLOSED.

    This replaces the old `test_int_keyed_map_also_resolves`, which pinned
    `.get(str(cid)) or .get(cid)` parity with the three router resolvers. That
    parity is gone on purpose: this map keys by name because TRON has no chain
    id, so resolving `84532` as well would mean two vocabularies for one map and
    an operator could not tell which one the code actually reads.
    """
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for(EVM_CHAIN) is None
    # Control: the same address under the NAME key does resolve, so the refusal
    # above is the key vocabulary and not a broken map.
    auto_split_json(_one(EVM_CHAIN))
    assert auto_split_address_for(EVM_CHAIN) == AUTOSPLIT


def test_int_keyed_map_from_a_stubbed_settings_does_not_resolve(monkeypatch):
    """Same rule one layer down, where several suites drive these maps from a
    SimpleNamespace rather than a JSON string (`test_router_v2.py`,
    `test_router_config_fail_closed.py`). JSON keys are always strings, so an
    int key can only arrive this way — and it must not be honoured here either.
    """
    import app.services.source_wallet_service as svc

    stub = SimpleNamespace(
        auto_split_addresses={84532: AUTOSPLIT},
        rsends_router_addresses={},
        rsends_router_v2_addresses={},
        split_router_addresses={},
    )
    monkeypatch.setattr(svc, "get_settings", lambda: stub)

    assert auto_split_address_for(EVM_CHAIN) is None
    # Control: the name key resolves through the identical stub.
    stub.auto_split_addresses = {EVM_CHAIN: AUTOSPLIT}
    assert auto_split_address_for(EVM_CHAIN) == AUTOSPLIT


def test_unset_env_var_resolves_to_none(auto_split_json):
    """The shipping state. Deploying the contract and not recording the address
    keeps the feature off rather than guessing where it lives."""
    auto_split_json("")

    assert auto_split_address_for(EVM_CHAIN) is None


@pytest.mark.parametrize("bad", [MALFORMED, NOT_AN_OBJECT], ids=["unparseable", "wrong-shape"])
def test_malformed_map_resolves_to_none(auto_split_json, bad):
    auto_split_json(bad)

    assert auto_split_address_for(EVM_CHAIN) is None
    # Control: well-formed input in the same environment does resolve.
    auto_split_json(_one(EVM_CHAIN))
    assert auto_split_address_for(EVM_CHAIN) == AUTOSPLIT


def test_unknown_chain_resolves_to_none(auto_split_json):
    """A populated map does not make an invented chain resolvable."""
    auto_split_json(_one(EVM_CHAIN))

    assert auto_split_address_for(EVM_CHAIN) == AUTOSPLIT   # control
    assert auto_split_address_for("dogechain") is None


def test_configured_chain_absent_from_token_registry_resolves_to_none(auto_split_json):
    """`chain_is_supported` is the guard, and it still bites under name keys.

    `arbitrum` HAS a chain id (42161) but is NOT in the token registry, so the
    system has no settlement path for it at all. The map is operator-supplied
    text, so without this guard an `"arbitrum"` entry would hand back an address
    for a chain nothing else in the system can serve.
    """
    assert chain_id_for("arbitrum") == 42161        # known to the id table …
    assert chain_is_supported("arbitrum") is False  # … but unsupported

    auto_split_json('{"arbitrum": "' + AUTOSPLIT + '", "' + EVM_CHAIN + '": "'
                    + CONFTEST_ROUTER_84532.replace("1", "7") + '"}')

    assert auto_split_address_for("arbitrum") is None
    # Control: the OTHER entry in the very same map resolves.
    assert auto_split_address_for(EVM_CHAIN) is not None


# ═══════════════════════════════════════════════════════════════
#  Watch-only is about settlement routing, not Auto Split eligibility
# ═══════════════════════════════════════════════════════════════

def test_tron_is_watch_only_and_has_no_evm_chain_id():
    """The premise the NAME key exists to satisfy, stated rather than assumed.

    Both TRON networks are `settlement: watch_only` and neither has an EVM chain
    id — deliberately (`test_tron_watchonly_intent.py`, "no fake integer"). That
    is precisely why this map cannot key by id, and it is NOT a reason to refuse
    the chain: see the test below.
    """
    for chain in (TRON_MAINNET, TRON_TESTNET):
        assert chain_is_supported(chain) is True
        assert is_watch_only_chain(chain) is True
        assert chain_id_for(chain) is None


def test_a_watch_only_chain_resolves_when_the_operator_names_it(auto_split_json):
    """The inversion, and the reason this branch exists.

    This test used to assert the opposite — that TRON was refused even with an
    entry in the map — on the reasoning that "AutoSplit is an EVM contract …
    never deployed there". That is no longer true: it compiles under the
    tronprotocol solc fork and executes on Nile against real USDT. `watch_only`
    describes how a PAYMENT settles (payer → merchant, no router), which says
    nothing about whether a keeper may empty a wallet the merchant owns.

    So the refusal is not the chain's class, it is the operator's env — and the
    control below is a watch-only chain the operator did NOT name.
    """
    auto_split_json(_one(TRON_TESTNET, AUTOSPLIT_TRON))

    assert auto_split_address_for(TRON_TESTNET) == AUTOSPLIT_TRON
    assert auto_split_address_for(TRON_MAINNET) is None      # same class, not named
    assert auto_split_address_for(EVM_CHAIN) is None         # not named either


def test_configuring_tron_puts_no_tron_identifier_in_a_router_map(auto_split_json):
    """The `test_tron_poller.py:790` invariant, restated for the new vocabulary.

    That pin asserts TRON's chain IDs appear in no EVM chain table and in none
    of the three router maps, because a TRON id reaching one starts a
    PaymentWatcher against a non-EVM node and SystemExits the boot. Name-keying
    introduces a SECOND TRON identifier — the chain name — so this checks the
    same property for it, and checks that configuring TRON for Auto Split does
    not leak either identifier sideways.

    It cannot, structurally: AUTO_SPLIT_ADDRESSES_JSON is its own env var with
    exactly one consumer (`auto_split_address_for`), and the indexer builds its
    watcher set from the router maps alone. This pins that, so a future change
    that starts merging the maps fails here rather than at boot.
    """
    auto_split_json(_one(TRON_TESTNET, AUTOSPLIT_TRON))
    assert auto_split_address_for(TRON_TESTNET) == AUTOSPLIT_TRON  # really configured

    settings = get_settings()
    forbidden = {TRON_MAINNET, TRON_TESTNET, "728126428", "3448148188"}
    for attr in (
        "rsends_router_addresses",
        "rsends_router_v2_addresses",
        "split_router_addresses",
    ):
        keys = {str(k).lower() for k in (getattr(settings, attr, {}) or {})}
        assert not (keys & forbidden), (
            f"{attr} carries a TRON identifier {keys & forbidden} — the indexer "
            f"builds PaymentWatchers from this map and would point one at a "
            f"non-EVM node (see test_tron_poller.py:790)"
        )


# ═══════════════════════════════════════════════════════════════
#  The address must never live in a router map
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "router_field",
    [
        "rsends_router_addresses_json",
        "rsends_router_v2_addresses_json",
        "split_router_addresses_json",
    ],
)
def test_address_also_in_a_router_map_is_refused(auto_split_json, monkeypatch, caplog, router_field):
    """The indexer builds its log filters from the router chain sets, so an
    AutoSplit address parked in one of them would have every SplitExecuted
    fetched and then dropped with a WARNING per execution. Refuse the address
    outright and say why — the misconfiguration is silent otherwise.

    Note the router maps stay CHAIN-ID keyed; only the AutoSplit map moved to
    names. The guard compares values, so the two vocabularies never meet.
    """
    monkeypatch.setattr(
        get_settings(), router_field, '{"84532": "' + AUTOSPLIT + '"}'
    )
    auto_split_json(_one(EVM_CHAIN))

    with caplog.at_level(logging.ERROR, logger="app.services.source_wallet_service"):
        assert auto_split_address_for(EVM_CHAIN) is None

    assert any(
        "AUTO_SPLIT_ADDRESSES_JSON" in r.message.upper() for r in caplog.records
    ), [r.message for r in caplog.records]


def test_collision_is_case_insensitive(auto_split_json, monkeypatch):
    """Checksummed in one map, lowercase in the other, is the SAME address —
    a case-sensitive compare would wave the collision straight through.

    `_parse_json_map` does no normalization of any kind (no checksum, no
    lowercasing, not even a 0x check), so the two maps really can disagree on
    case and the resolver is the only place the equality can be decided.
    """
    upper = AUTOSPLIT.upper().replace("0X", "0x")
    lower = AUTOSPLIT.lower()
    # Guard against this pin going vacuous: an all-digit address would make the
    # two spellings identical and a case-sensitive compare would still pass.
    assert upper != lower
    assert upper.lower() == lower

    monkeypatch.setattr(
        get_settings(), "rsends_router_addresses_json", '{"84532": "' + upper + '"}'
    )
    auto_split_json(_one(EVM_CHAIN, lower))

    assert auto_split_address_for(EVM_CHAIN) is None


def test_collision_on_a_different_chain_also_refused(auto_split_json, monkeypatch):
    """The constraint is flat: not in ANY router map, on any chain. An address
    the indexer watches on base is not made safe by being registered for
    base_sepolia."""
    monkeypatch.setattr(
        get_settings(), "rsends_router_addresses_json", '{"8453": "' + AUTOSPLIT + '"}'
    )
    auto_split_json(_one(EVM_CHAIN))

    assert auto_split_address_for(EVM_CHAIN) is None


def test_a_tron_autosplit_address_is_collision_checked_too(auto_split_json, monkeypatch):
    """The guard folds case for comparison, which is safe for base58 only
    because nothing is stored or decoded — it is a string equality and both
    sides are folded identically.

    Worth pinning: `.lower()` on a T-address is destructive everywhere else in
    this codebase, so a reader meeting it here needs to see that the result is
    used for one comparison and then discarded.
    """
    monkeypatch.setattr(
        get_settings(),
        "rsends_router_addresses_json",
        '{"84532": "' + AUTOSPLIT_TRON + '"}',
    )
    auto_split_json(_one(TRON_TESTNET, AUTOSPLIT_TRON))

    assert auto_split_address_for(TRON_TESTNET) is None
    # Control: a DIFFERENT TRON address in the same environment resolves, so the
    # refusal is the collision and not "TRON never resolves".
    auto_split_json(_one(TRON_TESTNET, "TNHUQgX2C1bSxdfuKZM855FY6QfPWLJiEa"))
    assert auto_split_address_for(TRON_TESTNET) == "TNHUQgX2C1bSxdfuKZM855FY6QfPWLJiEa"


def test_distinct_address_alongside_router_maps_still_resolves(auto_split_json):
    """The control for the four above: with the conftest router map live and an
    AutoSplit address that is genuinely its own, resolution succeeds. The
    refusals are the collision guard's, not a blanket 'any router map present'.
    """
    assert AUTOSPLIT.lower() != CONFTEST_ROUTER_84532.lower()
    auto_split_json(_one(EVM_CHAIN))

    assert auto_split_address_for(EVM_CHAIN) == AUTOSPLIT
