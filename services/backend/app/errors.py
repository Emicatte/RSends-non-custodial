"""
RSend Structured Error Codes

Ogni errore ha:
- code: stringa unica (es. "TX_DUPLICATE")
- http_status: codice HTTP
- message: descrizione human-readable
- detail: contesto aggiuntivo (opzionale)

Mai restituire errori generici tipo "Internal Server Error".
Mai esporre stack trace o dettagli interni in produzione.
"""
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request
import logging

logger = logging.getLogger("errors")

# Error catalog
ERRORS = {
    # Input validation
    "INVALID_ADDRESS": (400, "Invalid Ethereum address format or checksum"),
    "INVALID_AMOUNT": (400, "Amount must be positive and within valid range"),
    "INVALID_CHAIN_ID": (400, "Unsupported chain ID"),
    "MISSING_REQUIRED_FIELD": (400, "Required field is missing"),

    # Idempotency
    "DUPLICATE_TRANSACTION": (409, "Transaction already processed"),
    "DUPLICATE_WEBHOOK": (200, "Webhook already processed"),

    # Auth
    "INVALID_SIGNATURE": (401, "HMAC signature verification failed"),
    "INVALID_API_KEY": (401, "Invalid or missing API key"),
    "RATE_LIMITED": (429, "Too many requests — retry after cooldown"),

    # Business logic
    "INSUFFICIENT_BALANCE": (402, "Insufficient balance for this operation"),
    "GAS_TOO_HIGH": (503, "Gas price exceeds configured limit — retry later"),
    "DAILY_LIMIT_EXCEEDED": (403, "Daily volume limit exceeded"),
    "RULE_NOT_FOUND": (404, "Forwarding rule not found"),
    "RULE_PAUSED": (403, "Forwarding rule is paused"),
    "COOLDOWN_ACTIVE": (429, "Cooldown period active — retry later"),

    # Infrastructure
    "SERVICE_UNAVAILABLE": (503, "Service temporarily unavailable"),
    "REDIS_UNAVAILABLE": (503, "Cache service unavailable — retry later"),
    "RPC_ERROR": (502, "Blockchain RPC error"),
    "DB_ERROR": (500, "Database error"),

    # Security
    "BLACKLISTED_WALLET": (403, "Wallet address is blacklisted"),
    "SUSPICIOUS_ACTIVITY": (403, "Transaction flagged for suspicious activity"),
}


class RSendError(HTTPException):
    """Structured error with code."""
    def __init__(self, code: str, detail: str = None):
        status, message = ERRORS.get(code, (500, "Unknown error"))
        super().__init__(
            status_code=status,
            detail={
                "error": code,
                "message": message,
                "detail": detail,
            }
        )
        # Log non-4xx errors
        if status >= 500:
            logger.error("RSendError %s: %s (%s)", code, message, detail)
        elif status >= 400:
            logger.warning("RSendError %s: %s (%s)", code, message, detail)


def raise_if_invalid_address(address: str, field_name: str = "address") -> str:
    """Validate and checksum an Ethereum address. Raises RSendError if invalid."""
    import re
    if not address or not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        raise RSendError("INVALID_ADDRESS", f"{field_name}: {address}")

    # EIP-55 checksum validation
    try:
        from eth_utils import to_checksum_address, is_checksum_address
        checksummed = to_checksum_address(address)
        return checksummed
    except ImportError:
        # eth_utils non installato: accetta lowercase
        return address.lower()
    except ValueError:
        raise RSendError("INVALID_ADDRESS", f"{field_name} failed checksum: {address}")


def raise_if_invalid_amount(amount_wei: str, field_name: str = "amount") -> str:
    """Validate amount in Wei. Must be positive, no overflow."""
    try:
        val = int(amount_wei)
    except (ValueError, TypeError):
        raise RSendError("INVALID_AMOUNT", f"{field_name} is not a valid integer: {amount_wei}")

    if val <= 0:
        raise RSendError("INVALID_AMOUNT", f"{field_name} must be positive: {amount_wei}")

    if val > 10 ** 30:  # ~1 trillion ETH — impossibile, probabile overflow
        raise RSendError("INVALID_AMOUNT", f"{field_name} exceeds maximum: {amount_wei}")

    return amount_wei
