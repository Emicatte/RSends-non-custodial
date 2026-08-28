"""F3 — a malformed router map must not be silence.

`_parse_json_map` swallows every parse error into `{}`:

    except (ValueError, TypeError):
        return {}

For the three router maps that means a typo'd `RSENDS_ROUTER_ADDRESSES_JSON`
disables the indexer with no log line at all — payments stop being detected and
nothing says why. `RPC_PROVIDERS_JSON` already gets this right (it warns on
malformed input, `config.py:204-247`); the router maps get the same treatment,
plus one step further:

  - malformed, any posture      → WARNING from the parser (parity with
                                  RPC_PROVIDERS_JSON);
  - malformed, PROD posture     → startup ERROR in `validate_settings`. "Present
                                  but unparseable" is a typo in the one env var
                                  the money path depends on, not a deployment
                                  choice;
  - empty, prod                 → WARNING, unchanged (a chain-less deployment is
                                  a legitimate state and already says so).

Run:
  cd services/backend
  DATABASE_URL="sqlite+aiosqlite://" pytest tests/test_router_config_fail_closed.py -v
"""

import logging
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import Settings, StartupValidationError, validate_settings

ROUTER_MAP = '{"84532": "0x' + "a" * 40 + '"}'
MALFORMED = '{"84532": "0xdeadbeef"'          # unterminated object
NOT_AN_OBJECT = '["84532"]'                   # valid JSON, wrong shape

ROUTER_JSON_FIELDS = [
    "rsends_router_addresses_json",
    "rsends_router_v2_addresses_json",
    "split_router_addresses_json",
]
ROUTER_MAP_PROPERTIES = {
    "rsends_router_addresses_json": "rsends_router_addresses",
    "rsends_router_v2_addresses_json": "rsends_router_v2_addresses",
    "split_router_addresses_json": "split_router_addresses",
}


# ═══════════════════════════════════════════════════════════════
#  The parser warns instead of swallowing
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("json_field", ROUTER_JSON_FIELDS)
@pytest.mark.parametrize("bad", [MALFORMED, NOT_AN_OBJECT], ids=["unparseable", "wrong-shape"])
def test_malformed_router_map_warns(caplog, json_field, bad):
    s = Settings(**{json_field: bad})
    prop = ROUTER_MAP_PROPERTIES[json_field]

    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert getattr(s, prop) == {}

    assert any(
        json_field.upper().replace("_JSON", "_JSON") in r.message.upper()
        or prop.upper() in r.message.upper()
        for r in caplog.records
    ), [r.message for r in caplog.records]


@pytest.mark.parametrize("json_field", ROUTER_JSON_FIELDS)
def test_empty_router_map_does_not_warn(caplog, json_field):
    """Unset is the normal dev/test state — it must stay quiet at the parser."""
    s = Settings(**{json_field: ""})

    with caplog.at_level(logging.WARNING, logger="app.config"):
        assert getattr(s, ROUTER_MAP_PROPERTIES[json_field]) == {}

    assert caplog.records == []


@pytest.mark.parametrize("json_field", ROUTER_JSON_FIELDS)
def test_wellformed_router_map_parses_and_is_quiet(caplog, json_field):
    s = Settings(**{json_field: ROUTER_MAP})

    with caplog.at_level(logging.WARNING, logger="app.config"):
        parsed = getattr(s, ROUTER_MAP_PROPERTIES[json_field])

    assert parsed == {"84532": "0x" + "a" * 40}
    assert caplog.records == []


# ═══════════════════════════════════════════════════════════════
#  Prod posture: present-but-unparseable is a startup ERROR
# ═══════════════════════════════════════════════════════════════

def _prod_settings(**over):
    """A fully-valid production Settings stand-in; override one field to break it.

    Mirrors tests/test_config_hardening.py::_prod_settings, plus the raw `_json`
    strings — `validate_settings` cannot tell "empty" from "unparseable" without
    them, because both parse to `{}`.
    """
    base = dict(
        debug=False,
        alchemy_api_key="alch-key",
        hmac_secret="x" * 32,
        admin_api_token="y" * 32,
        database_url="postgresql+asyncpg://u:p@db.internal/rpagos",
        telegram_bot_token="tg",
        redis_url="rediss://redis.internal:6379/0",
        celery_broker_url="rediss://redis.internal:6379/1",
        auth_jwt_secret="a" * 64,
        email_dev_mode=False,
        app_url="https://app.rsends.io",
        wallet_auth_allow_legacy=False,
        rsends_router_addresses={"8453": "0xRouter"},
        rsends_router_v2_addresses={},
        split_router_addresses={},
        # Per-chain RPC provider coverage: 8453 is served by alchemy_api_key
        # above, so no extra provider is needed for the baseline to validate.
        rpc_extra_providers={},
        rsends_router_addresses_json=ROUTER_MAP,
        rsends_router_v2_addresses_json="",
        split_router_addresses_json="",
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("json_field", ROUTER_JSON_FIELDS)
@pytest.mark.parametrize("bad", [MALFORMED, NOT_AN_OBJECT], ids=["unparseable", "wrong-shape"])
def test_malformed_router_map_blocks_startup_in_prod(json_field, bad):
    """Present but unparseable → the map the money path reads is `{}` and the
    operator does not know it. Refuse to boot."""
    s = _prod_settings(**{
        json_field: bad,
        ROUTER_MAP_PROPERTIES[json_field]: {},
    })
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with pytest.raises(StartupValidationError):
            validate_settings(s)


def test_empty_router_map_stays_a_warning_in_prod(caplog):
    """Unchanged behaviour: a deployment with no routers configured yet boots
    and says so. Only *malformed* is promoted to an error."""
    s = _prod_settings(
        rsends_router_addresses={},
        rsends_router_addresses_json="",
    )
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            validate_settings(s)   # must NOT raise

    assert any("RSENDS_ROUTER_ADDRESSES_JSON" in r.message for r in caplog.records)


def test_malformed_router_map_does_not_block_startup_outside_prod():
    """Dev keeps booting on a broken env var — the parser WARNING is the signal
    there. The hard stop is a production posture rule."""
    s = _prod_settings(
        debug=True,
        rsends_router_addresses={},
        rsends_router_addresses_json=MALFORMED,
    )
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        validate_settings(s)   # must NOT raise


def test_valid_prod_router_config_still_passes():
    s = _prod_settings()
    with patch.dict(os.environ, {"ENVIRONMENT": ""}, clear=False):
        validate_settings(s)
