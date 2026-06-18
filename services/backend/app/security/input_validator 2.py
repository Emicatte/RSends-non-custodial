"""
RSends Backend — Input Validation Service.

Pure validation functions for all user-facing inputs.

Functions:
  validate_eth_address()     — checksum, non-zero
  validate_amount_wei()      — numeric string, positive, max 78 digits
  validate_percent_bps()     — integer 1-10000
  validate_distribution_list() — addresses + bps, no dupes, sum=10000, max 500
  sanitize_label()           — strip HTML, trim, max 100 chars
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

ZERO_ADDRESS = "0x" + "0" * 40
MAX_WEI_DIGITS = 78          # uint256 max is 78 digits
MAX_RECIPIENTS = 500
BPS_DENOM = 10_000            # 10000 bps = 100%
MAX_LABEL_LEN = 100

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# ═══════════════════════════════════════════════════════════════
#  Exception
# ═══════════════════════════════════════════════════════════════

class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


# ═══════════════════════════════════════════════════════════════
#  Address Validation
# ═══════════════════════════════════════════════════════════════

def validate_eth_address(address: str, field: str = "address") -> str:
    """Validate and return checksummed Ethereum address.

    Checks:
      - Correct format (0x + 40 hex chars)
      - Not zero address
      - Valid EIP-55 checksum (if mixed case)

    Args:
        address: Raw address string.
        field: Field name for error messages.

    Returns:
        Checksummed address string.

    Raises:
        ValidationError: If address is invalid.
    """
    if not isinstance(address, str):
        raise ValidationError(field, "must be a string")

    address = address.strip()

    if not _ETH_ADDR_RE.match(address):
        raise ValidationError(field, "invalid Ethereum address format")

    if address == ZERO_ADDRESS:
        raise ValidationError(field, "zero address not allowed")

    # EIP-55 checksum verification
    from eth_utils import to_checksum_address, is_checksum_address

    # Mixed case = claims to be checksummed — verify
    if address != address.lower() and address != address.upper():
        if not is_checksum_address(address):
            raise ValidationError(field, "invalid EIP-55 checksum")

    return to_checksum_address(address)


# ═══════════════════════════════════════════════════════════════
#  Amount Validation
# ═══════════════════════════════════════════════════════════════

def validate_amount_wei(amount: str, field: str = "amount") -> str:
    """Validate a Wei amount string.

    Checks:
      - Numeric string (no decimals, no negatives)
      - Positive (> 0)
      - Max 78 digits (uint256 range)

    Args:
        amount: Wei amount as string.
        field: Field name for error messages.

    Returns:
        Validated amount string.

    Raises:
        ValidationError: If amount is invalid.
    """
    if not isinstance(amount, str):
        raise ValidationError(field, "must be a string")

    amount = amount.strip()

    if not amount.isdigit():
        raise ValidationError(
            field, "must be a numeric string (no decimals, no negatives)"
        )

    if len(amount) > MAX_WEI_DIGITS:
        raise ValidationError(field, f"exceeds maximum {MAX_WEI_DIGITS} digits")

    if int(amount) <= 0:
        raise ValidationError(field, "must be positive")

    return amount


# ═══════════════════════════════════════════════════════════════
#  BPS Validation
# ═══════════════════════════════════════════════════════════════

def validate_percent_bps(bps: int, field: str = "bps") -> int:
    """Validate basis points (1-10000).

    1 bps = 0.01%, 10000 bps = 100%.

    Raises:
        ValidationError: If bps is out of range.
    """
    if not isinstance(bps, int):
        raise ValidationError(field, "must be an integer")

    if bps < 1 or bps > BPS_DENOM:
        raise ValidationError(field, f"must be between 1 and {BPS_DENOM}")

    return bps


# ═══════════════════════════════════════════════════════════════
#  Distribution List Validation
# ═══════════════════════════════════════════════════════════════

def validate_distribution_list(
    recipients: list[dict],
    sender: Optional[str] = None,
    field: str = "distribution",
) -> list[dict]:
    """Validate a distribution list.

    Each entry: {"address": "0x...", "bps": 500}

    Checks:
      - Valid Ethereum addresses, no duplicates
      - BPS per entry in 1-10000
      - Total BPS sum == 10000
      - No self-send (if sender provided)
      - Max 500 recipients

    Args:
        recipients: List of {address, bps} dicts.
        sender: Optional sender address to block self-sends.
        field: Field name for error messages.

    Returns:
        Validated list with checksummed addresses.

    Raises:
        ValidationError: On any check failure.
    """
    if not isinstance(recipients, list):
        raise ValidationError(field, "must be a list")

    if len(recipients) == 0:
        raise ValidationError(field, "cannot be empty")

    if len(recipients) > MAX_RECIPIENTS:
        raise ValidationError(field, f"max {MAX_RECIPIENTS} recipients")

    seen: set[str] = set()
    total_bps = 0
    validated: list[dict] = []

    for i, entry in enumerate(recipients):
        if not isinstance(entry, dict):
            raise ValidationError(f"{field}[{i}]", "must be an object")

        addr = entry.get("address")
        bps = entry.get("bps")

        if addr is None:
            raise ValidationError(f"{field}[{i}].address", "required")
        if bps is None:
            raise ValidationError(f"{field}[{i}].bps", "required")

        checksummed = validate_eth_address(addr, f"{field}[{i}].address")
        validate_percent_bps(bps, f"{field}[{i}].bps")

        addr_lower = checksummed.lower()

        if addr_lower in seen:
            raise ValidationError(f"{field}[{i}].address", "duplicate address")
        seen.add(addr_lower)

        if sender and addr_lower == sender.lower():
            raise ValidationError(f"{field}[{i}].address", "self-send not allowed")

        total_bps += bps
        validated.append({"address": checksummed, "bps": bps})

    if total_bps != BPS_DENOM:
        raise ValidationError(
            field, f"bps must sum to {BPS_DENOM}, got {total_bps}"
        )

    return validated


# ═══════════════════════════════════════════════════════════════
#  Label Sanitization
# ═══════════════════════════════════════════════════════════════

def sanitize_label(label: str, field: str = "label") -> str:
    """Sanitize a user-provided label.

    - Strips all HTML tags
    - Trims leading/trailing whitespace
    - Truncates to 100 characters

    Args:
        label: Raw label string.
        field: Field name for error messages.

    Returns:
        Sanitized label.

    Raises:
        ValidationError: If label is not a string.
    """
    if not isinstance(label, str):
        raise ValidationError(field, "must be a string")

    cleaned = _HTML_TAG_RE.sub("", label)
    cleaned = cleaned.strip()

    if len(cleaned) > MAX_LABEL_LEN:
        cleaned = cleaned[:MAX_LABEL_LEN]

    return cleaned
