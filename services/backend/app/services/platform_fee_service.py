"""
RSends Platform Fee Calculator.

Calculates the platform fee deducted from merchant payments at sweep time.
All amounts are in raw token units (wei for ETH, smallest unit for ERC-20).
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

TOKEN_DECIMALS = {"ETH": 18, "USDC": 6, "USDT": 6, "DAI": 18}


def token_decimals(currency: str) -> int:
    return TOKEN_DECIMALS.get(currency.upper(), 18)


@dataclass
class FeeResult:
    enabled: bool
    fee_bps: int
    gross_amount: int
    fee_amount: int
    merchant_amount: int


def calculate_fee(gross_raw: int, fee_bps: Optional[int] = None) -> FeeResult:
    """
    Calculate platform fee from gross amount in raw token units.

    Args:
        gross_raw: Gross payment amount in raw units (e.g. 100_000_000 for 100 USDC)
        fee_bps: Override fee in basis points (default: from config)

    Returns:
        FeeResult with enabled flag, amounts, and BPS rate.
    """
    settings = get_settings()

    if not settings.platform_fee_enabled or not settings.platform_treasury_address:
        return FeeResult(
            enabled=False,
            fee_bps=0,
            gross_amount=gross_raw,
            fee_amount=0,
            merchant_amount=gross_raw,
        )

    bps = fee_bps if fee_bps is not None else settings.platform_fee_bps
    fee = gross_raw * bps // 10000
    merchant = gross_raw - fee

    logger.info(
        "Platform fee: gross=%d, fee_bps=%d, fee=%d, merchant=%d",
        gross_raw, bps, fee, merchant,
    )

    return FeeResult(
        enabled=True,
        fee_bps=bps,
        gross_amount=gross_raw,
        fee_amount=fee,
        merchant_amount=merchant,
    )
