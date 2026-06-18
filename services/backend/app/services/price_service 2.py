"""
RSend Price Service — Prezzi real-time da CoinGecko con cache Redis.

CoinGecko free tier: 10-30 call/min.
Strategia: batch fetch ogni 60s di tutti i token, cache in Redis.
Fallback: in-memory cache se Redis è down.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

from app.services.cache_service import get_redis
from app.tokens.registry import get_all_coingecko_ids

logger = logging.getLogger("price_service")

COINGECKO_API = "https://api.coingecko.com/api/v3"
CACHE_PREFIX = "price:"
CACHE_TTL = 120           # 2 minuti — conservative per free tier
FETCH_INTERVAL = 60       # fetch ogni 60 secondi
REQUEST_TIMEOUT = 10      # timeout per singola richiesta CoinGecko

# ── In-memory fallback se Redis è down ─────────────────────────
_memory_cache: dict[str, dict[str, float]] = {}
_last_fetch: float = 0


async def fetch_all_prices(vs_currencies: str = "eur,usd") -> dict[str, dict[str, float]]:
    """
    Fetch prezzi di tutti i token dal CoinGecko in una singola call.

    Ritorna: {"ethereum": {"eur": 1785.51, "usd": 2057.18}, ...}
    """
    global _memory_cache, _last_fetch

    ids = get_all_coingecko_ids()
    if not ids:
        logger.warning("No coingecko IDs configured — skipping price fetch")
        return _memory_cache

    ids_str = ",".join(ids)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{COINGECKO_API}/simple/price",
                params={"ids": ids_str, "vs_currencies": vs_currencies},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data: dict[str, dict[str, float]] = resp.json()

        # Salva in Redis (per-token keys)
        try:
            r = await get_redis()
            if r:
                pipe = r.pipeline()
                for coin_id, prices in data.items():
                    pipe.set(
                        f"{CACHE_PREFIX}{coin_id}",
                        json.dumps(prices),
                        ex=CACHE_TTL,
                    )
                await pipe.execute()
        except Exception as redis_err:
            logger.debug("Redis cache write failed: %s", redis_err)

        # Salva in memory fallback
        _memory_cache = data
        _last_fetch = time.time()

        logger.debug("Prices updated: %d coins", len(data))
        return data

    except Exception as e:
        logger.warning("CoinGecko fetch failed: %s — using cache", e)
        return _memory_cache


async def get_price(coingecko_id: str, currency: str = "eur") -> Optional[float]:
    """
    Get prezzo di un singolo token.
    Prova: Redis cache → memory cache → fetch fresh.
    """
    # 1. Redis cache
    try:
        r = await get_redis()
        if r:
            cached = await r.get(f"{CACHE_PREFIX}{coingecko_id}")
            if cached:
                data = json.loads(cached)
                price = data.get(currency)
                if price is not None:
                    return float(price)
    except Exception:
        pass

    # 2. Memory cache
    if coingecko_id in _memory_cache:
        price = _memory_cache[coingecko_id].get(currency)
        if price is not None:
            return float(price)

    # 3. Fetch fresh (solo se cache è vuota o stale > 5 min)
    if time.time() - _last_fetch > 300:
        prices = await fetch_all_prices()
        if coingecko_id in prices:
            price = prices[coingecko_id].get(currency)
            if price is not None:
                return float(price)

    return None


async def get_eur_value(coingecko_id: str, amount: float) -> Optional[float]:
    """Calcola il controvalore EUR di un importo."""
    price = await get_price(coingecko_id, "eur")
    if price is None:
        return None
    return round(amount * price, 2)


async def get_usd_value(coingecko_id: str, amount: float) -> Optional[float]:
    """Calcola il controvalore USD di un importo."""
    price = await get_price(coingecko_id, "usd")
    if price is None:
        return None
    return round(amount * price, 2)


async def get_all_cached_prices(currency: str = "eur") -> dict[str, float]:
    """Ritorna tutti i prezzi cached. Per il frontend."""
    result: dict[str, float] = {}

    for coin_id in get_all_coingecko_ids():
        price: Optional[float] = None

        # Redis first
        try:
            r = await get_redis()
            if r:
                cached = await r.get(f"{CACHE_PREFIX}{coin_id}")
                if cached:
                    data = json.loads(cached)
                    price = data.get(currency)
        except Exception:
            pass

        # Memory fallback
        if price is None and coin_id in _memory_cache:
            price = _memory_cache[coin_id].get(currency)

        if price is not None:
            result[coin_id] = float(price)

    return result


# ── Background refresh loop ────────────────────────────────────

async def price_refresh_loop() -> None:
    """Background loop che refresha i prezzi ogni FETCH_INTERVAL secondi."""
    logger.info("Price refresh loop started (interval=%ds)", FETCH_INTERVAL)
    while True:
        try:
            await fetch_all_prices()
        except Exception as e:
            logger.error("Price refresh failed: %s", e)
        await asyncio.sleep(FETCH_INTERVAL)
