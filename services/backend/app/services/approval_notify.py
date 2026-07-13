"""Telegram notification for a merchant entering the approval queue.

Fires when the company profile is SUBMITTED (the full profile is what the
operator needs to decide). Strictly a CONVENIENCE: the admin approval page
lists pending orgs from the DB, so a lost message never strands a merchant —
this function must NEVER raise into the submit path.

Transport is the existing generic sender
(notification_service.send_telegram_alert — rate-limited raw Bot API POST);
chat id: TELEGRAM_APPROVALS_CHAT_ID, falling back to TELEGRAM_CHAT_ID. With
neither token nor chat configured the send is skipped (one startup WARNING
comes from config.py) and signup/KYB proceed normally.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.notification_service import send_telegram_alert

logger = logging.getLogger(__name__)

_SEND_TIMEOUT = 8.0  # never let a slow Telegram stall the KYB submit


def _esc(value) -> str:
    """Minimal HTML escaping for parse_mode=HTML message bodies."""
    return (
        str(value if value is not None else "—")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_pending_message(org, profile) -> str:
    settings = get_settings()
    approvals_url = f"{settings.app_url}/admin/approvals"
    served = ", ".join(profile.countries_served or []) if profile else "—"
    lines = [
        "🆕 <b>Merchant pending approval</b>",
        f"Org: {_esc(org.name)} ({_esc(org.slug)})",
        f"Legal name: {_esc(profile.legal_name if profile else None)}",
        f"Country: {_esc(profile.country if profile else None)}",
        f"Registration #: {_esc(profile.registration_number if profile else None)}",
        f"Tax/VAT: {_esc(profile.tax_or_vat_number if profile else None)}",
        f"Category: {_esc(profile.business_category if profile else None)}",
        f"Expected volume: {_esc(profile.expected_monthly_volume if profile else None)}",
        f"Stablecoin: {_esc(profile.primary_stablecoin if profile else None)}",
        f"Countries served: {_esc(served)}",
        f"Website: {_esc(profile.website if profile else None)}",
        f"PEP: {_esc(profile.has_pep if profile else None)}",
        "",
        f"Review: {approvals_url}",
    ]
    return "\n".join(lines)


async def notify_merchant_pending(org, profile) -> None:
    """Send the approval-queue message. Logs and swallows every failure."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.info("approval_notify_skipped: TELEGRAM_BOT_TOKEN not configured")
        return
    chat_id = (
        getattr(settings, "telegram_approvals_chat_id", "")
        or settings.telegram_chat_id
    )
    if not chat_id:
        logger.info("approval_notify_skipped: no approvals chat id configured")
        return
    try:
        await asyncio.wait_for(
            send_telegram_alert(build_pending_message(org, profile), chat_id=chat_id),
            timeout=_SEND_TIMEOUT,
        )
    except Exception:
        # ERROR with a distinct code; the merchant is safely in the DB queue.
        logger.exception(
            "approval_notify_failed", extra={"org_id": str(org.id)}
        )
