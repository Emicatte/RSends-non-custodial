"""
RPagos Backend Core — Servizio di verifica HMAC.

Verifica la x_signature inviata dal frontend usando HMAC-SHA256.

Firma: HMAC_SHA256(secret, "fiscal_ref|tx_hash|gross_amount|currency|timestamp")

Sicurezza:
  - Verifica HMAC-SHA256 rigorosa + anti-replay (5 min) in TUTTI gli ambienti
  - Usa hmac.compare_digest per prevenire timing attacks
  - In DEBUG=true: logga warning extra per diagnostica, ma NON bypassa la verifica
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone, timedelta

from app.config import get_settings

logger = logging.getLogger(__name__)

# Anti-replay: rifiuta richieste con timestamp più vecchio di 5 minuti
REPLAY_WINDOW_SECONDS = 300


def compute_signature(
    fiscal_ref: str,
    tx_hash: str,
    amount: str,
    currency: str,
    timestamp: str,
) -> str:
    """
    Calcola la firma HMAC-SHA256 attesa.

    Il messaggio da firmare segue lo stesso ordine del frontend:
    fiscal_ref|tx_hash|gross_amount|currency|timestamp
    """
    settings = get_settings()
    message = f"{fiscal_ref}|{tx_hash}|{amount}|{currency}|{timestamp}"
    signature = hmac.new(
        settings.hmac_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signature


def _check_timestamp_freshness(timestamp: str) -> bool:
    """Verifica che il timestamp non sia più vecchio di REPLAY_WINDOW_SECONDS.

    Returns:
        True se il timestamp è entro la finestra, False se è troppo vecchio.
    """
    try:
        # Prova ISO format (con o senza timezone)
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        logger.warning("Anti-replay: invalid timestamp format: %s", timestamp)
        return False

    now = datetime.now(timezone.utc)
    age = abs((now - ts).total_seconds())

    if age > REPLAY_WINDOW_SECONDS:
        logger.warning(
            "Anti-replay: timestamp too old (age=%.0fs, max=%ds): %s",
            age, REPLAY_WINDOW_SECONDS, timestamp,
        )
        return False

    return True


def verify_signature(
    x_signature: str,
    fiscal_ref: str,
    tx_hash: str,
    amount: str,
    currency: str,
    timestamp: str,
) -> bool:
    """
    Verifica che x_signature corrisponda al payload.

    - Usa hmac.compare_digest per prevenire timing attacks.
    - Anti-replay: rifiuta timestamp più vecchi di 5 minuti.
    - In DEBUG=true: logga warning extra ma verifica comunque.
    """
    settings = get_settings()

    if x_signature == "PENDING_HMAC_SHA256":
        logger.warning(
            "HMAC verification REJECTED: received placeholder 'PENDING_HMAC_SHA256'. "
            "The frontend must compute a real HMAC-SHA256 signature."
        )
        return False

    # Anti-replay: verifica che il timestamp sia entro la finestra
    if not _check_timestamp_freshness(timestamp):
        return False

    expected = compute_signature(fiscal_ref, tx_hash, amount, currency, timestamp)
    valid = hmac.compare_digest(x_signature, expected)

    if not valid and settings.debug:
        logger.warning(
            "HMAC mismatch (DEBUG mode). fiscal_ref=%s, tx_hash=%s",
            fiscal_ref, tx_hash[:16] + "..." if len(tx_hash) > 16 else tx_hash,
        )

    return valid
