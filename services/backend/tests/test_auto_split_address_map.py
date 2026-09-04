"""AUTO_SPLIT_ADDRESSES_JSON — the operator env flip, and every way it stays shut.

`auto_split_address_for` was built as a deliberate seam returning None for every
chain (`source_wallet_service.py`, "THE SEAM"), so the whole source-wallet
surface 422s `AUTO_SPLIT_UNAVAILABLE` until an operator wires the address map.
This module wires it, following the `SPLIT_ROUTER_ADDRESSES_JSON` three-layer
pattern — raw settings field -> parsed property -> resolver — and pins that
opening ONE chain does not open any other.

Fail-closed matrix. Every one of these must resolve to None, never to a guessed
default:

  - env var unset                    (the shipping state; deploying late is safe)
  - malformed JSON                   (+ a WARNING naming the var, never silence)
  - valid JSON, not an object        (+ the same WARNING)
  - a chain the name table has never heard of
  - a chain in the map but ABSENT from the token registry — the case the
    split-router body alone gets WRONG: CHAIN_IDS is wider than TOKEN_REGISTRY
    (`chain_id_for("arbitrum")` is 42161 while `chain_is_supported("arbitrum")`
    is False), so a bare chain-id lookup would hand back an address for a chain
    with no settlement path at all
  - a watch_only chain, EVEN WITH an entry in the map — AutoSplit is an EVM
    contract; TRON's addresses are base58check and it was never deployed there
  - an address that is ALSO in a router map — the indexer builds its log filters
    from those chain sets, so it would fetch every SplitExecuted and then drop
    it with a WARNING per execution. The contract deploy script says "NEVER add
    this address to RSENDS_ROUTER_*_ADDRESSES_JSON"; this is that sentence made
    enforceable instead of hoped for.

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
MALFORMED = '{"84532": "0xdeadbeef"'          # unterminated object
NOT_AN_OBJECT = '["84532"]'                   # valid JSON, wrong shape

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
    s = Settings(auto_split_addresses_json='{"84532": "' + AUTOSPLIT + '"}')

    with caplog.at_level(logging.WARNING, logger="app.config"):
        parsed = s.auto_split_addresses

    assert parsed == {"84532": AUTOSPLIT}
    assert caplog.records == []


# ═══════════════════════════════════════════════════════════════
#  Layer 3 — the resolver opens exactly one chain
# ═══════════════════════════════════════════════════════════════

def test_base_sepolia_resolves_when_configured(auto_split_json):
    """The whole point of the branch: the deployed chain answers with the
    configured address, and answers with THAT address, not a default."""
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("base_sepolia") == AUTOSPLIT


def test_int_keyed_map_also_resolves(monkeypatch):
    """`.get(str(cid)) or .get(cid)` parity with the three router resolvers.

    JSON object keys are always strings, so this shape can only arrive from a
    stubbed Settings — which is exactly how several suites drive these maps
    (`test_router_v2.py`, `test_router_config_fail_closed.py`). Pinning it keeps
    the resolver body honest to the pattern it claims to follow.
    """
    import app.services.source_wallet_service as svc

    stub = SimpleNamespace(
        auto_split_addresses={84532: AUTOSPLIT},
        rsends_router_addresses={},
        rsends_router_v2_addresses={},
        split_router_addresses={},
    )
    monkeypatch.setattr(svc, "get_settings", lambda: stub)

    assert auto_split_address_for("base_sepolia") == AUTOSPLIT


def test_unset_env_var_resolves_to_none(auto_split_json):
    """The shipping state. Deploying the contract and not recording the address
    keeps the feature off rather than guessing where it lives."""
    auto_split_json("")

    assert auto_split_address_for("base_sepolia") is None


@pytest.mark.parametrize("bad", [MALFORMED, NOT_AN_OBJECT], ids=["unparseable", "wrong-shape"])
def test_malformed_map_resolves_to_none(auto_split_json, bad):
    auto_split_json(bad)

    assert auto_split_address_for("base_sepolia") is None


def test_unknown_chain_resolves_to_none(auto_split_json):
    """A populated map does not make an invented chain resolvable."""
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("dogechain") is None


def test_configured_chain_absent_from_token_registry_resolves_to_none(auto_split_json):
    """The case a bare chain-id lookup gets wrong.

    `arbitrum` HAS a chain id (42161) but is NOT in the token registry, so the
    system has no settlement path for it at all. Copying the split-router body
    verbatim would return the address here; the registry gate is what stops it.
    """
    assert chain_id_for("arbitrum") == 42161      # reachable by id …
    assert chain_is_supported("arbitrum") is False  # … but unsupported

    auto_split_json('{"42161": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("arbitrum") is None


# ═══════════════════════════════════════════════════════════════
#  Watch-only chains: refused on their own grounds, not by accident
# ═══════════════════════════════════════════════════════════════

def test_tron_is_watch_only_and_has_no_evm_chain_id():
    """The premise of the guard below, stated rather than assumed.

    Today tron is unreachable through the map because it has no EVM chain id at
    all (deliberately — `test_tron_watchonly_intent.py`, "no fake integer").
    That is a REACHABILITY accident, not a policy, which is why the next test
    exists.
    """
    assert chain_is_supported("tron") is True
    assert is_watch_only_chain("tron") is True
    assert chain_id_for("tron") is None


def test_watch_only_chain_refused_even_when_present_in_the_map(auto_split_json, monkeypatch):
    """Give TRON a chain id and put that id in the map — it STILL resolves None.

    AutoSplit is an EVM contract and TRON settles watch_only with base58check
    addresses; that is a property of the chain, not of the operator's env. This
    pins the refusal to `is_watch_only_chain`, so it survives anyone giving TRON
    a chain id later (TRON checkout work is landing on main).
    """
    import app.services.source_wallet_service as svc

    monkeypatch.setattr(svc, "chain_id_for", lambda chain: 728126428)
    auto_split_json('{"728126428": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("tron") is None
    # Control: the same map, the same patched id table, on an EVM chain — the
    # refusal above is TRON's watch_only status and nothing else.
    assert auto_split_address_for("base_sepolia") == AUTOSPLIT


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
    outright and say why — the misconfiguration is silent otherwise."""
    monkeypatch.setattr(
        get_settings(), router_field, '{"84532": "' + AUTOSPLIT + '"}'
    )
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    with caplog.at_level(logging.ERROR, logger="app.services.source_wallet_service"):
        assert auto_split_address_for("base_sepolia") is None

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
    auto_split_json('{"84532": "' + lower + '"}')

    assert auto_split_address_for("base_sepolia") is None


def test_collision_on_a_different_chain_also_refused(auto_split_json, monkeypatch):
    """The constraint is flat: not in ANY router map, on any chain. An address
    the indexer watches on base is not made safe by being registered for
    base_sepolia."""
    monkeypatch.setattr(
        get_settings(), "rsends_router_addresses_json", '{"8453": "' + AUTOSPLIT + '"}'
    )
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("base_sepolia") is None


def test_distinct_address_alongside_router_maps_still_resolves(auto_split_json):
    """The control for the three above: with the conftest router map live and an
    AutoSplit address that is genuinely its own, resolution succeeds. The
    refusals are the collision guard's, not a blanket 'any router map present'.
    """
    assert AUTOSPLIT.lower() != CONFTEST_ROUTER_84532.lower()
    auto_split_json('{"84532": "' + AUTOSPLIT + '"}')

    assert auto_split_address_for("base_sepolia") == AUTOSPLIT
