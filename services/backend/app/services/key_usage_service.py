"""Track API key usage — intents created, volume, monthly limits."""
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key_models import ApiKey

logger = logging.getLogger(__name__)


async def increment_intent_count(db: AsyncSession, key_id: int) -> None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key:
        key.total_intents_created = (key.total_intents_created or 0) + 1


async def add_volume(db: AsyncSession, key_id: int, amount_usd: Decimal) -> None:
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if key:
        current = Decimal(key.total_volume_usd or "0")
        key.total_volume_usd = str(current + amount_usd)


async def check_monthly_limits(db: AsyncSession, key_id: int) -> dict:
    """Returns {"allowed": True/False, "reason": "..."}"""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        return {"allowed": False, "reason": "Key not found"}

    if key.monthly_intent_limit and key.monthly_intent_limit > 0:
        if (key.total_intents_created or 0) >= key.monthly_intent_limit:
            return {
                "allowed": False,
                "reason": f"Monthly intent limit reached ({key.monthly_intent_limit})",
            }

    vol_limit = Decimal(key.monthly_volume_limit_usd or "0")
    if vol_limit > 0:
        current_vol = Decimal(key.total_volume_usd or "0")
        if current_vol >= vol_limit:
            return {
                "allowed": False,
                "reason": f"Monthly volume limit reached (${vol_limit})",
            }

    return {"allowed": True, "reason": ""}
