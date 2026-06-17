"""
RSends Backend — Structured JSON Logging Configuration.

Formato JSON strutturato con python-json-logger.
Ogni log include: timestamp, level, message, request_id, module, extra fields.

Livelli:
  DEBUG    → solo in dev
  INFO     → operazioni normali
  WARNING  → degradation (es. Redis down, fallback permissivo)
  ERROR    → errori recuperabili
  CRITICAL → errori che richiedono intervento immediato
"""

import logging
import sys

from pythonjsonlogger import json as jsonlogger

from app.middleware.request_context import get_request_id
from app.middleware.correlation import get_correlation_id


class RequestContextFilter(logging.Filter):
    """Aggiunge request_id e correlation_id a ogni log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        req_id = get_request_id()
        record.request_id = str(req_id) if req_id else None  # type: ignore[attr-defined]
        record.correlation_id = get_correlation_id() or None  # type: ignore[attr-defined]
        return True


def setup_logging(*, debug: bool = False) -> None:
    """Configura il logging strutturato JSON per tutta l'applicazione.

    Args:
        debug: Se True, livello DEBUG; altrimenti INFO.
    """
    level = logging.DEBUG if debug else logging.INFO

    # Formatter JSON strutturato (con correlation_id)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s %(correlation_id)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "module",
        },
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Handler stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(RequestContextFilter())

    # Configura il root logger
    root = logging.getLogger()
    root.setLevel(level)
    # Rimuovi handler esistenti per evitare duplicati
    root.handlers.clear()
    root.addHandler(handler)

    # Abbassa il livello dei logger rumorosi
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if debug else logging.WARNING
    )
    logging.getLogger("alembic").setLevel(logging.INFO)
