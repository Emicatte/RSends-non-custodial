"""The static USD peg that replaced the CoinGecko price feed.

`app/tokens/registry.py` is a DISPLAY registry — it feeds the /app KPI tiles and
the volume-trend card, nothing on the money path (that is
`app/token_registry.json` via `router_registry.py`). Its one job is to answer
"what is this token worth in USD", and for the tokens RSends actually charges
that answer is exact by construction: a stablecoin is one unit of its peg.

The rule these tests exist to hold: **absent peg means EXCLUDE, never zero.**
A token that contributes 0.0 to a volume aggregate makes a merchant with real
settled payments read "$0.00" — indistinguishable from having received nothing.
`None` is the only representation of "cannot value this"; 0 is a value.
"""

from decimal import Decimal

import pytest

from app.tokens.registry import TOKEN_REGISTRY, TokenInfo, get_token, get_usd_peg

# Symbols with an exact, definitional USD peg. Not a price — 1 USDC IS one
# dollar of USDC. Nothing here needs a network call to stay true.
PEGGED = {"USDC", "USDT", "DAI"}

# Chargeable today = the Pydantic currency set ∩ token_registry.json `enabled`.
# (chain_id, symbol) pairs, kept explicit so a registry edit that drops one of
# them fails here rather than silently excluding a merchant's payments.
CHARGEABLE = [
    (1, "ETH"), (1, "USDC"), (1, "USDT"), (1, "DAI"),
    (8453, "ETH"), (8453, "USDC"),
    (84532, "ETH"), (84532, "USDC"),
]


def _by_symbol(chain_id: int, symbol: str) -> TokenInfo:
    for (cid, _addr), t in TOKEN_REGISTRY.items():
        if cid == chain_id and t.symbol == symbol:
            return t
    raise AssertionError(f"{symbol} is not registered on chain {chain_id}")


@pytest.mark.parametrize("chain_id,symbol", CHARGEABLE)
def test_every_chargeable_token_is_registered(chain_id, symbol):
    """A chargeable token missing from this registry is silently unvaluable —
    the failure mode is a merchant's volume reading low with no explanation."""
    assert _by_symbol(chain_id, symbol) is not None


@pytest.mark.parametrize("chain_id,symbol", [c for c in CHARGEABLE if c[1] in PEGGED])
def test_chargeable_stablecoins_peg_at_exactly_one(chain_id, symbol):
    t = _by_symbol(chain_id, symbol)
    assert t.peg_usd == Decimal("1")


@pytest.mark.parametrize("chain_id,symbol", [c for c in CHARGEABLE if c[1] not in PEGGED])
def test_chargeable_non_stablecoins_have_no_peg(chain_id, symbol):
    """ETH has no exact USD value. Absent, not zero, not a guess."""
    assert _by_symbol(chain_id, symbol).peg_usd is None


def test_mainnet_dai_is_registered_and_pegged():
    """Ethereum DAI is chargeable and `enabled: true` in token_registry.json but
    had no row here — its settlements were excluded despite being exactly
    pegged. Pinned so it cannot silently go missing again."""
    dai = get_token(1, "0x6B175474E89094C44Da98b954EedeAC495271d0F")
    assert dai is not None
    assert dai.symbol == "DAI"
    assert dai.decimals == 18
    assert dai.peg_usd == Decimal("1")


def test_no_token_is_pegged_to_zero():
    """The defect this whole branch removes: a 0 peg is indistinguishable from
    a payment that never happened. If a token cannot be valued, say None."""
    for t in TOKEN_REGISTRY.values():
        assert t.peg_usd is None or t.peg_usd > 0


def test_peg_is_exact_decimal_not_float():
    """Decimal, so summing a thousand stablecoin settlements does not drift."""
    for t in TOKEN_REGISTRY.values():
        assert t.peg_usd is None or isinstance(t.peg_usd, Decimal)


def test_get_usd_peg_resolves_native_by_none_address():
    assert get_usd_peg(84532, None) is None  # native ETH — registered, unpegged


def test_get_usd_peg_is_case_insensitive():
    lower = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
    checksummed = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    assert get_usd_peg(84532, lower) == get_usd_peg(84532, checksummed) == Decimal("1")


def test_unknown_token_has_no_peg():
    """Unknown must behave exactly like unpegged — excluded, never zeroed."""
    assert get_usd_peg(84532, "0x" + "9" * 40) is None
    assert get_usd_peg(999999, "0x" + "9" * 40) is None


def test_registry_carries_no_coingecko_ids():
    """The price feed is gone; a leftover `coingecko_id` is an invitation to
    wire another fetcher to it."""
    assert not hasattr(TokenInfo("X", "X", 18, None, 1, True, 0.0), "coingecko_id")
