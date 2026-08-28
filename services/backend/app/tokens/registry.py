"""
RSend Token Registry — display-side token metadata.

Questo file serve le superfici di VISUALIZZAZIONE (le KPI di /app e la card
"Volume trend"): decimali per normalizzare gli importi in base units, simbolo
per etichettarli, e il peg USD per valorizzarli. NON è il registro del money
path — quello è `app/token_registry.json`, letto da `app/services/router_registry.py`,
ed è l'unico che decide cosa si può addebitare.

Il peg ha sostituito il price feed CoinGecko (`price_service.py`, rimosso): RSends
incassa stablecoin, e per una stablecoin il valore in dollari è esatto per
costruzione — 1 USDC È un dollaro di USDC. Nessuna chiamata di rete per scoprirlo.

REGOLA: `peg_usd is None` significa ESCLUDERE, mai contare zero. Un token che
contribuisce 0.0 a un aggregato fa leggere "$0.00" a un merchant che è stato
pagato davvero, indistinguibile dal non aver incassato nulla. `None` è l'unica
rappresentazione di "non so valorizzarlo"; 0 è un valore.

Chains supportate:
  8453   — Base Mainnet
  84532  — Base Sepolia (testnet)
  1      — Ethereum Mainnet
  42161  — Arbitrum One
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

# Peg esatto delle stablecoin a 1 unità della loro valuta di riferimento.
# Decimal, non float: sommare mille settlement non deve accumulare drift.
_PEG_ONE = Decimal("1")


@dataclass(frozen=True)
class TokenInfo:
    symbol: str
    name: str
    decimals: int
    address: Optional[str]   # None = native (ETH)
    chain_id: int
    is_native: bool
    min_amount: float
    # Valore USD esatto di UNA unità del token, o None se non esiste un peg.
    # None ⇒ escluso dagli aggregati, mai sommato come zero.
    peg_usd: Optional[Decimal] = None


# Registry: (chain_id, address_lowercase) → TokenInfo
# Per native token: (chain_id, "native") → TokenInfo
TOKEN_REGISTRY: dict[tuple[int, str], TokenInfo] = {}


def _register(t: TokenInfo) -> None:
    key = (t.chain_id, (t.address or "native").lower())
    TOKEN_REGISTRY[key] = t


# ═══ BASE MAINNET (8453) ═══
_register(TokenInfo("ETH",   "Ether",          18, None,                                               8453, True,  0.0001))
_register(TokenInfo("USDC",  "USD Coin",         6, "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",      8453, False, 0.01,    _PEG_ONE))
_register(TokenInfo("USDT",  "Tether USD",       6, "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",      8453, False, 0.01,    _PEG_ONE))
_register(TokenInfo("DAI",   "Dai Stablecoin",  18, "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",      8453, False, 0.01,    _PEG_ONE))
_register(TokenInfo("WETH",  "Wrapped Ether",   18, "0x4200000000000000000000000000000000000006",       8453, False, 0.0001))
_register(TokenInfo("cbBTC", "Coinbase BTC",      8, "0xcbB7C0000AB88B473b1f5aFd9ef808440eed33Bf",      8453, False, 0.00001))

# ═══ BASE SEPOLIA (84532) ═══
_register(TokenInfo("ETH",  "Ether (Sepolia)",  18, None,                                               84532, True,  0.0001))
_register(TokenInfo("USDC", "USDC (Sepolia)",     6, "0x036CbD53842c5426634e7929541eC2318f3dCF7e",      84532, False, 0.01,    _PEG_ONE))

# ═══ ETHEREUM MAINNET (1) ═══
_register(TokenInfo("ETH",  "Ether",            18, None,                                                   1, True,  0.001))
_register(TokenInfo("USDC", "USD Coin",           6, "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",          1, False, 0.01,    _PEG_ONE))
_register(TokenInfo("USDT", "Tether USD",         6, "0xdAC17F958D2ee523a2206206994597C13D831ec7",          1, False, 0.01,    _PEG_ONE))
# Addebitabile ed `enabled: true` in token_registry.json, ma per molto tempo
# assente da qui: i suoi settlement finivano esclusi pur avendo un peg esatto.
_register(TokenInfo("DAI",  "Dai Stablecoin",    18, "0x6B175474E89094C44Da98b954EedeAC495271d0F",          1, False, 0.01,    _PEG_ONE))

# ═══ ARBITRUM ONE (42161) ═══
_register(TokenInfo("ETH",  "Ether",            18, None,                                               42161, True,  0.0001))
_register(TokenInfo("USDC", "USD Coin",           6, "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",      42161, False, 0.01,    _PEG_ONE))
_register(TokenInfo("USDT", "Tether USD",         6, "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",      42161, False, 0.01,    _PEG_ONE))
_register(TokenInfo("ARB",  "Arbitrum",          18, "0x912CE59144191C1204E64559FE8253a0e49E6548",      42161, False, 0.1))


# ═══ LOOKUP HELPERS ═══

def get_token(chain_id: int, address: Optional[str] = None) -> Optional[TokenInfo]:
    """Get token info by chain and address. address=None for native."""
    key = (chain_id, (address or "native").lower())
    return TOKEN_REGISTRY.get(key)


def get_native(chain_id: int) -> Optional[TokenInfo]:
    """Get native token for a chain."""
    return get_token(chain_id, None)


def get_tokens_for_chain(chain_id: int) -> list[TokenInfo]:
    """Get all tokens for a chain."""
    return [t for (cid, _), t in TOKEN_REGISTRY.items() if cid == chain_id]


def get_decimals(chain_id: int, address: Optional[str]) -> int:
    """Get decimals, default 18 if unknown."""
    t = get_token(chain_id, address)
    return t.decimals if t else 18


def get_usd_peg(chain_id: int, address: Optional[str]) -> Optional[Decimal]:
    """Peg USD esatto di una unità del token, o None se non ne ha uno.

    None è il caso di gran lunga più comune (ETH, e qualsiasi token che il
    registry non conosce) e significa **ESCLUDI dall'aggregato**: il chiamante
    deve contarlo a parte e dirlo, mai sommarlo come zero.
    """
    t = get_token(chain_id, address)
    return t.peg_usd if t else None
