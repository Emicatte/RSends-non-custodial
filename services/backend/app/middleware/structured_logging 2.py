"""
RSends Backend — Structured Logging Formatter.

Logger strutturato JSON che include automaticamente:
  - correlation_id  (traccia l'operazione attraverso tutti i servizi)
  - service         (nome del componente: "api", "celery", "sweep", "execution")
  - timestamp ISO
  - level
  - event           (cosa sta succedendo)
  - duration_ms     (per operazioni misurabili)
  - chain_id, tx_hash, wallet quando rilevanti

Uso:
  logger.info("Sweep executed", extra={
      "service": "sweep",
      "chain_id": 8453,
      "tx_hash": "0xabc...",
      "duration_ms": 120,
  })
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.middleware.correlation import get_correlation_id
from app.middleware.request_context import get_request_id


# ── Extra fields propagated automatically ────────────────────
_EXTRA_KEYS = (
    "service",
    "chain_id",
    "tx_hash",
    "wallet",
    "duration_ms",
    "error",
    "sweep_id",
    "rule_id",
    "batch_id",
)


class StructuredFormatter(logging.Formatter):
    """JSON formatter that auto-injects correlation_id and context fields."""

    def format(self, record: logging.LogRecord) -> str:
        log: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "correlation_id": get_correlation_id() or None,
            "request_id": str(rid) if (rid := get_request_id()) else None,
            "service": getattr(record, "service", "api"),
            "module": record.name,
            "event": record.getMessage(),
        }

        # Append extra fields when present on the record
        for key in _EXTRA_KEYS:
            val = getattr(record, key, None)
            if val is not None:
                log[key] = val

        # Include exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            log["error"] = self.formatException(record.exc_info)

        return json.dumps(log, default=str)


class TimedOperation:
    """Context manager that logs duration_ms for a block of code.

    Usage:
        with TimedOperation(logger, "RPC eth_blockNumber", service="sweep", chain_id=8453):
            block = await rpc.eth_blockNumber()
    """

    def __init__(
        self,
        logger_: logging.Logger,
        event: str,
        level: int = logging.INFO,
        **extra: Any,
    ):
        self._logger = logger_
        self._event = event
        self._level = level
        self._extra = extra
        self._start: float = 0

    def __enter__(self) -> "TimedOperation":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed_ms = round((time.monotonic() - self._start) * 1000, 1)
        extra = {**self._extra, "duration_ms": elapsed_ms}
        if exc_val is not None:
            extra["error"] = str(exc_val)
            self._logger.log(
                logging.ERROR, "%s FAILED (%.1fms)", self._event, elapsed_ms, extra=extra
            )
        else:
            self._logger.log(
                self._level, "%s (%.1fms)", self._event, elapsed_ms, extra=extra
            )
