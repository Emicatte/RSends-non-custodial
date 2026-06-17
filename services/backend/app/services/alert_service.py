"""
RSend Alert Service — Immediate notifications for critical events.

Channels (in order of priority):
  1. Telegram bot (push notifications — primary)
  2. Generic webhook (Slack, PagerDuty, Discord, etc.)
  3. Critical log (always, as guaranteed fallback)

Alert types:
  SIGNING_DOWN      — circuit breaker opened on signing path
  SIGNING_SPIKE     — >5 signing errors in 1 minute
  KMS_RATE_LIMIT    — local KMS rate limit reached
  RPC_DOWN          — chain RPC unreachable
  REDIS_DOWN        — Redis unreachable
  AML_BLOCK         — transaction blocked by AML screening
  SWEEP_FAILED      — sweep execution failed
  BALANCE_LOW       — master wallet balance below threshold
  CB_RECOVERY       — circuit breaker recovered (OPEN -> CLOSED)

Cooldown per severity prevents notification spam.

Backward-compatible: critical_alert() keeps same signature for
existing callers in circuit_breaker.py and reconciliation_job.py.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("rsend.alerts")


# ═══════════════════════════════════════════════════════════════
#  Enums
# ═══════════════════════════════════════════════════════════════

class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    SIGNING_DOWN = "signing_down"
    SIGNING_SPIKE = "signing_spike"
    KMS_RATE_LIMIT = "kms_rate_limit"
    RPC_DOWN = "rpc_down"
    REDIS_DOWN = "redis_down"
    AML_BLOCK = "aml_block"
    SWEEP_FAILED = "sweep_failed"
    BALANCE_LOW = "balance_low"
    CB_RECOVERY = "cb_recovery"
    # Reconciliation job alerts
    SYSTEM_IMBALANCE = "system_imbalance"
    LEDGER_DISCREPANCY = "ledger_discrepancy"
    LEDGER_DISCREPANCY_CRITICAL = "ledger_discrepancy_critical"
    ONCHAIN_DISCREPANCY = "onchain_discrepancy"
    ONCHAIN_DISCREPANCY_CRITICAL = "onchain_discrepancy_critical"
    STALE_TRANSACTIONS = "stale_transactions"
    TREASURY_MISMATCH = "treasury_mismatch"
    TREASURY_MISMATCH_CRITICAL = "treasury_mismatch_critical"


SEVERITY_MAP: dict[AlertType, AlertSeverity] = {
    AlertType.SIGNING_DOWN: AlertSeverity.EMERGENCY,
    AlertType.SIGNING_SPIKE: AlertSeverity.CRITICAL,
    AlertType.KMS_RATE_LIMIT: AlertSeverity.CRITICAL,
    AlertType.RPC_DOWN: AlertSeverity.WARNING,
    AlertType.REDIS_DOWN: AlertSeverity.EMERGENCY,
    AlertType.AML_BLOCK: AlertSeverity.INFO,
    AlertType.SWEEP_FAILED: AlertSeverity.CRITICAL,
    AlertType.BALANCE_LOW: AlertSeverity.WARNING,
    AlertType.CB_RECOVERY: AlertSeverity.INFO,
    AlertType.SYSTEM_IMBALANCE: AlertSeverity.EMERGENCY,
    AlertType.LEDGER_DISCREPANCY: AlertSeverity.WARNING,
    AlertType.LEDGER_DISCREPANCY_CRITICAL: AlertSeverity.EMERGENCY,
    AlertType.ONCHAIN_DISCREPANCY: AlertSeverity.WARNING,
    AlertType.ONCHAIN_DISCREPANCY_CRITICAL: AlertSeverity.EMERGENCY,
    AlertType.STALE_TRANSACTIONS: AlertSeverity.WARNING,
    AlertType.TREASURY_MISMATCH: AlertSeverity.WARNING,
    AlertType.TREASURY_MISMATCH_CRITICAL: AlertSeverity.EMERGENCY,
}


# ═══════════════════════════════════════════════════════════════
#  Alert dataclass
# ═══════════════════════════════════════════════════════════════

@dataclass
class Alert:
    type: AlertType
    severity: AlertSeverity
    message: str
    context: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
#  AlertService
# ═══════════════════════════════════════════════════════════════

class AlertService:
    """Multi-channel alert dispatcher with per-severity cooldown."""

    _COOLDOWN_MINUTES: dict[AlertSeverity, int] = {
        AlertSeverity.EMERGENCY: 1,     # max 1 alert/minute
        AlertSeverity.CRITICAL: 5,      # max 1 every 5 min
        AlertSeverity.WARNING: 15,      # max 1 every 15 min
        AlertSeverity.INFO: 60,         # max 1/hour
    }

    def __init__(
        self,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ):
        self._telegram_token = telegram_token
        self._telegram_chat_id = telegram_chat_id
        self._webhook_url = webhook_url
        self._cooldowns: dict[str, datetime] = {}

    # ── Public API ────────────────────────────────────────

    async def fire(
        self,
        alert_type: AlertType,
        message: str,
        context: Optional[dict] = None,
    ) -> None:
        """Send an alert if not in cooldown.

        Always logs. Telegram and webhook are best-effort.
        """
        severity = SEVERITY_MAP.get(alert_type, AlertSeverity.WARNING)

        # Cooldown check
        cooldown_key = alert_type.value
        now = datetime.now(timezone.utc)
        if cooldown_key in self._cooldowns:
            cooldown_min = self._COOLDOWN_MINUTES.get(severity, 5)
            if now - self._cooldowns[cooldown_key] < timedelta(minutes=cooldown_min):
                return
        self._cooldowns[cooldown_key] = now

        alert = Alert(
            type=alert_type,
            severity=severity,
            message=message,
            context=context or {},
            timestamp=now,
        )

        # Log (guaranteed fallback)
        log_fn = (
            logger.critical
            if severity in (AlertSeverity.EMERGENCY, AlertSeverity.CRITICAL)
            else logger.warning
        )
        log_fn(
            "ALERT [%s] %s: %s | ctx=%s",
            severity.value, alert_type.value, message, context,
        )

        # Dispatch to external channels in parallel
        tasks: list = []
        if self._telegram_token and self._telegram_chat_id:
            tasks.append(self._send_telegram(alert))
        if self._webhook_url:
            tasks.append(self._send_webhook(alert))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning("Alert channel %d failed: %s", i, result)

    # ── Telegram ──────────────────────────────────────────

    async def _send_telegram(self, alert: Alert) -> None:
        import httpx

        emoji = {
            AlertSeverity.EMERGENCY: "\U0001f534\U0001f534\U0001f534",
            AlertSeverity.CRITICAL: "\U0001f534",
            AlertSeverity.WARNING: "\U0001f7e1",
            AlertSeverity.INFO: "\u2139\ufe0f",
        }.get(alert.severity, "\u26aa")

        lines = [
            f"{emoji} *RSend Alert*",
            f"*Type:* `{alert.type.value}`",
            f"*Severity:* {alert.severity.value.upper()}",
            f"*Message:* {alert.message}",
            f"*Time:* {alert.timestamp.strftime('%H:%M:%S UTC')}",
        ]

        if alert.context:
            ctx_lines = [f"  {k}: `{v}`" for k, v in alert.context.items()]
            lines.append("*Context:*")
            lines.extend(ctx_lines)

        text = "\n".join(lines)
        url = f"https://api.telegram.org/bot{self._telegram_token}/sendMessage"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": self._telegram_chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Telegram alert failed: %d %s",
                    resp.status_code, resp.text[:200],
                )

    # ── Generic webhook (Discord/Slack/PagerDuty) ─────────

    async def _send_webhook(self, alert: Alert) -> None:
        import httpx

        is_discord = "discord.com" in self._webhook_url or "discordapp.com" in self._webhook_url

        if is_discord:
            payload = {
                "content": (
                    f"**[{alert.severity.value.upper()}] {alert.type.value}**\n"
                    f"{alert.message}\n"
                    f"Context: {alert.context}\n"
                    f"{alert.timestamp.strftime('%H:%M:%S UTC')}"
                ),
            }
        else:
            # Slack / generic format
            payload = {
                "type": alert.type.value,
                "severity": alert.severity.value,
                "message": alert.message,
                "context": alert.context,
                "timestamp": alert.timestamp.isoformat(),
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._webhook_url, json=payload, timeout=5,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Webhook alert failed: %d %s",
                    resp.status_code, resp.text[:200],
                )


# ═══════════════════════════════════════════════════════════════
#  Singleton + convenience functions
# ═══════════════════════════════════════════════════════════════

_alert_service: Optional[AlertService] = None


def init_alert_service(
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    webhook_url: Optional[str] = None,
) -> AlertService:
    """Create and register the global AlertService singleton."""
    global _alert_service
    _alert_service = AlertService(
        telegram_token=telegram_token,
        telegram_chat_id=telegram_chat_id,
        webhook_url=webhook_url,
    )
    logger.info(
        "AlertService initialised: telegram=%s webhook=%s",
        bool(telegram_token and telegram_chat_id),
        bool(webhook_url),
    )
    return _alert_service


def get_alert_service() -> Optional[AlertService]:
    """Get the global AlertService (may be None before init)."""
    return _alert_service


async def fire_alert(
    alert_type: AlertType,
    message: str,
    context: Optional[dict] = None,
) -> None:
    """Fire an alert via the global service. No-op if not initialised."""
    svc = _alert_service
    if svc is not None:
        await svc.fire(alert_type, message, context)


# ═══════════════════════════════════════════════════════════════
#  Backward-compatible API
#  (used by circuit_breaker.py, reconciliation_job.py)
# ═══════════════════════════════════════════════════════════════

async def critical_alert(message: str, context: Optional[dict] = None) -> bool:
    """Send a critical alert. Backward-compatible with old callers.

    If AlertService is initialised, routes through it (with cooldown).
    Otherwise, falls back to legacy webhook/Telegram path.
    Returns True if sent successfully.
    """
    svc = _alert_service
    if svc is not None:
        await svc.fire(AlertType.SIGNING_DOWN, message, context)
        return True

    # Legacy fallback (before AlertService is initialised)
    from app.config import get_settings
    settings = get_settings()
    webhook_url = settings.alert_webhook_url

    timestamp = datetime.now(timezone.utc).isoformat()
    full_message = f"**RSend CRITICAL**\n{message}\n{timestamp}"

    if webhook_url:
        return await _send_legacy_webhook(webhook_url, full_message)

    # Fallback to Telegram
    try:
        from app.services.notification_service import send_telegram_alert
        html_message = f"<b>[CRITICAL]</b>\n{message}\n<i>{timestamp}</i>"
        return await send_telegram_alert(html_message)
    except Exception as exc:
        logger.error("Critical alert failed (no webhook, Telegram error): %s", exc)
        return False


async def _send_legacy_webhook(url: str, message: str) -> bool:
    """Legacy webhook dispatch (kept for backward compat)."""
    import httpx

    is_discord = "discord.com" in url or "discordapp.com" in url
    payload = {"content": message} if is_discord else {"text": message}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            logger.info("Critical alert sent via webhook: %s", message[:80])
            return True
    except Exception as exc:
        logger.error("Webhook alert failed: %s", exc)
        try:
            from app.services.notification_service import send_telegram_alert
            return await send_telegram_alert(f"<b>[CRITICAL]</b>\n{message}")
        except Exception:
            return False
