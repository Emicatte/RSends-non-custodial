"""
RPagos Backend — Price API Routes.

Endpoint:
  GET /api/v1/prices              → Tutti i prezzi cached (EUR + USD)
  GET /api/v1/prices/{coingecko_id} → Prezzo singolo token
"""

from fastapi import APIRouter

from app.services.price_service import get_all_cached_prices, get_price

price_router = APIRouter(prefix="/api/v1", tags=["prices"])


@price_router.get("/prices")
async def get_prices():
    """Ritorna tutti i prezzi correnti in EUR e USD."""
    eur = await get_all_cached_prices("eur")
    usd = await get_all_cached_prices("usd")
    return {"eur": eur, "usd": usd, "cached": True}


@price_router.get("/prices/{coingecko_id}")
async def get_single_price(coingecko_id: str):
    """Ritorna prezzo di un singolo token in EUR e USD."""
    eur = await get_price(coingecko_id, "eur")
    usd = await get_price(coingecko_id, "usd")
    if eur is None and usd is None:
        return {"id": coingecko_id, "eur": None, "usd": None, "cached": False}
    return {"id": coingecko_id, "eur": eur, "usd": usd}
