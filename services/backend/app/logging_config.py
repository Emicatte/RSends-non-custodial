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

Posture (H6, `is_prod_posture`): in produzione il root resta a INFO e i logger
di terze parti rumorosi (httpx, httpcore, sqlalchemy.engine) sono forzati a
WARNING — i loro WARNING/ERROR continuano a passare (le diagnosi degli ultimi
incidenti Redis dipendevano esattamente da quelli). Dev/test invariati.

Redazione segreti — indipendente dal livello, perché la chiave Alchemy
trapelava a INFO nella riga request-URL di httpx: `SecretRedactionFilter`
(sull'handler root) maschera messaggio post-interpolazione, %-args, valori
stringa negli extra; `RedactingJsonFormatter` maschera i traceback formattati
(pythonjsonlogger consulta exc_info PRIMA di exc_text, quindi il solo filtro
non basterebbe; exc_info resta intatto sul record per il grouping di Sentry).

Uvicorn tiene i propri logger (`uvicorn`/`uvicorn.access`) con handler dedicati
e `propagate=False` per l'intera vita del processo: senza intervento i loro
record — in particolare i traceback di `uvicorn.error`, il vettore più ricco di
segreti — bypasserebbero il filtro. `setup_logging` li ri-instrada sul root
(svuota gli handler + `propagate=True`) in ENTRAMBE le posture, così la
redazione è universale e i log uvicorn diventano JSON come il resto.

Limiti accettati (fuori scope, documentati):
  - solo i record emessi PRIMA che il lifespan chiami setup_logging (le prime
    righe di avvio di uvicorn) restano non redatti;
  - i worker Celery non chiamano setup_logging;
  - Sentry vede msg/extra già redatti (il filtro riscrive il record condiviso:
    scelta a favore della sicurezza — il segreto non arriva a Sentry — al costo
    del raggruppamento per template dei log parametrici); l'oggetto exc_info
    resta grezzo sul record (scrubbing lato Sentry fuori scope).
"""

import logging
import re
import sys

from pythonjsonlogger import json as jsonlogger
from pythonjsonlogger.core import RESERVED_ATTRS

from app.middleware.request_context import get_request_id
from app.middleware.correlation import get_correlation_id

_MASK = "[REDACTED]"

# API key nel path URL — forma RPC Alchemy (https://<net>.alchemy.com/v2/<key>).
_ALCHEMY_URL_KEY = re.compile(
    r"(https?://[A-Za-z0-9.\-]*\.alchemy\.com/v2/)[^\s\"'/?#]+"
)
# Difesa in profondità: qualunque /v2/<segmento token-like ≥ 20 char> in URL
# (non tocca segmenti umani corti tipo /v2/invoices).
_GENERIC_V2_KEY = re.compile(
    r"(https?://[^\s\"']*/v2/)[A-Za-z0-9_\-]{20,}(?![A-Za-z0-9_\-])"
)
# Connection string con credenziali (redis://, rediss://, postgresql://,
# postgresql+asyncpg://, amqp://, …): maschera SOLO la password, conserva
# schema+utente+host così il log resta utile.
_URL_CREDENTIALS = re.compile(
    r"\b([a-z][a-z0-9+.\-]*://[^/\s:@\"']*):([^@/\s\"']+)@", re.IGNORECASE
)
# Token del bot Telegram nel PATH dell'URL (https://api.telegram.org/bot
# <id>:<token>/metodo — notification_service/alert_service): host-anchored e
# con la forma <digits>:<token> obbligatoria, così /botinfo o /bottega/…
# restano intatti. Il suffisso (/sendMessage) resta visibile come contesto.
_TELEGRAM_BOT_URL = re.compile(
    r"(https?://api\.telegram\.org/bot)\d+:[A-Za-z0-9_\-]+"
)
# Bearer token (header Authorization, JWT inclusi).
_BEARER = re.compile(r"\b([Bb]earer\s+)[A-Za-z0-9\-._~+/]+=*")
# Chiavi API del repo (merchant rsend_*, utente rsusr_*) — oltre il minimo
# richiesto, ma economico: il prefisso resta visibile, il segreto no. Copre
# ENTRAMBI gli ambienti per entrambi i namespace (il regex non deve mai essere
# più stretto dello spazio delle chiavi).
_RSEND_KEY = re.compile(
    r"\b(rsend_(?:test|live)_|rsusr_(?:test|live)_)[A-Za-z0-9_\-]+"
)

# Marcatori a substring: se nessuno è presente, nessuna delle 6 regex può
# matchare, quindi si salta l'intera scansione (fast-path, output invariato).
# "://" copre le connection string e TUTTI i pattern URL (Alchemy, /v2/…,
# Telegram bot).
_MARKERS = ("://", "earer", "rsend_", "rsusr_")


def redact_secrets(text: str) -> str:
    """Maschera i segreti in una stringa di log conservando il contesto
    (host, schema, prefissi) che rende il log ancora leggibile."""
    if not any(m in text for m in _MARKERS):
        return text
    text = _ALCHEMY_URL_KEY.sub(r"\1" + _MASK, text)
    text = _GENERIC_V2_KEY.sub(r"\1" + _MASK, text)
    text = _TELEGRAM_BOT_URL.sub(r"\1" + _MASK, text)
    text = _URL_CREDENTIALS.sub(r"\1:" + _MASK + "@", text)
    text = _BEARER.sub(r"\1" + _MASK, text)
    text = _RSEND_KEY.sub(r"\1" + _MASK, text)
    return text


class RequestContextFilter(logging.Filter):
    """Aggiunge request_id e correlation_id a ogni log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        req_id = get_request_id()
        record.request_id = str(req_id) if req_id else None  # type: ignore[attr-defined]
        record.correlation_id = get_correlation_id() or None  # type: ignore[attr-defined]
        return True


# Attributi standard del LogRecord (lista di pythonjsonlogger) da NON toccare
# quando si redigono gli extra; taskName è l'aggiunta di Python 3.12.
_SKIP_ATTRS = frozenset(RESERVED_ATTRS) | {"taskName"}


class SecretRedactionFilter(logging.Filter):
    """Maschera i segreti in ogni record emesso: messaggio (interpolato coi
    %-args), valori stringa negli extra, exc_text pre-formattato. Applicato
    sull'handler root, quindi copre anche i logger di terze parti."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Logging must NEVER raise into the caller. In a handler *filter* an
        # exception is not contained by Handler.handleError (which only guards
        # emit), so it would propagate out of the logger.xxx() call site → 500.
        # record.getMessage() raises on malformed %-args, so guard each step.
        try:
            if isinstance(record.msg, dict):
                # pythonjsonlogger supporta msg dict (merge nei campi JSON).
                record.msg = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.msg.items()
                }
            else:
                record.msg = redact_secrets(record.getMessage())
                record.args = None
        except Exception:
            # Fail safe: redact the raw template (no interpolation happened)
            # and drop args so the formatter's getMessage() can't re-raise.
            try:
                if isinstance(record.msg, str):
                    record.msg = redact_secrets(record.msg)
            except Exception:
                pass
            record.args = None
        try:
            for key, val in list(record.__dict__.items()):
                if key not in _SKIP_ATTRS and isinstance(val, str):
                    record.__dict__[key] = redact_secrets(val)
        except Exception:
            pass
        try:
            if isinstance(record.exc_text, str) and record.exc_text:
                record.exc_text = redact_secrets(record.exc_text)
        except Exception:
            pass
        return True


class RedactingJsonFormatter(jsonlogger.JsonFormatter):
    """Redazione a livello formatter per traceback/stack: exc_info resta
    intatto sul record (Sentry lo usa), ma il testo formattato è mascherato."""

    def formatException(self, exc_info) -> str:
        return redact_secrets(super().formatException(exc_info))

    def formatStack(self, stack_info) -> str:
        return redact_secrets(super().formatStack(stack_info))


def setup_logging(*, debug: bool = False, prod_posture: bool = False) -> None:
    """Configura il logging strutturato JSON per tutta l'applicazione.

    Args:
        debug: Se True, livello DEBUG; altrimenti INFO.
        prod_posture: `is_prod_posture(settings)` — in produzione forza i
            logger rumorosi (httpx, httpcore, sqlalchemy.engine) a WARNING.
            Nota: prod posture ⟹ debug=False in ogni config avviabile
            (validate_dev_flags rifiuta DEBUG=true + ENVIRONMENT=prod*).
    """
    level = logging.DEBUG if debug else logging.INFO

    # Formatter JSON strutturato (con correlation_id) + redazione traceback
    formatter = RedactingJsonFormatter(
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
    # Redazione segreti su OGNI record, in OGNI posture — indipendente dal
    # livello (la chiave Alchemy trapelava a INFO).
    handler.addFilter(SecretRedactionFilter())

    # Configura il root logger
    root = logging.getLogger()
    root.setLevel(level)
    # Rimuovi handler esistenti per evitare duplicati
    root.handlers.clear()
    root.addHandler(handler)

    # Ri-instrada i logger di uvicorn sul root handler. La config di default di
    # uvicorn dà a 'uvicorn'/'uvicorn.access' handler dedicati NON-propaganti,
    # quindi i loro record — inclusi i traceback di uvicorn.error, il vettore
    # più ricco di segreti — bypasserebbero il filtro di redazione e il
    # formatter JSON per tutta la vita del processo. Svuotare i loro handler e
    # riattivare la propagazione li fa confluire sul root (redatti + JSON).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # Abbassa il livello dei logger rumorosi
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("alembic").setLevel(logging.INFO)
    if prod_posture:
        # Produzione: terze parti rumorose a WARNING (impostare il parent
        # "httpcore" copre anche httpcore.http11/.connection per ereditarietà);
        # i logger applicativi restano a INFO.
        for name in ("httpx", "httpcore", "sqlalchemy.engine"):
            logging.getLogger(name).setLevel(logging.WARNING)
    else:
        # Dev/test: comportamento invariato (httpx/httpcore non forzati).
        logging.getLogger("sqlalchemy.engine").setLevel(
            logging.INFO if debug else logging.WARNING
        )
