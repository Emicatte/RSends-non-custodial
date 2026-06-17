"""
RSends Backend — Fan-Out Distribution Engine.

Pure-math distribution calculator and transaction builder.
ALL amounts are Python int (Wei). NEVER float.

Classes:
  DistributionService — stateless calculator + TX builder

Methods:
  calculate_distribution()      — split incoming amount across recipients
  prepare_batch_calldata()      — encode RSendsBatchDistributor.distributeETH()
  prepare_sequential_txs()      — build N individual TX dicts
  validate_post_execution()     — verify on-chain events match expected amounts
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from eth_abi import encode

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

# ERC-20 transfer(address,uint256) selector
ERC20_TRANSFER_SELECTOR = bytes.fromhex("a9059cbb")

# RSendsBatchDistributor.distributeETH(address[],uint256[]) selector
# keccak256("distributeETH(address[],uint256[])") → first 4 bytes
DISTRIBUTE_ETH_SELECTOR = bytes.fromhex("27945eff")

# SingleTransfer(address indexed recipient, uint256 amount) event topic
# keccak256("SingleTransfer(address,uint256)")
SINGLE_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)

# Gas constants
GAS_PER_ETH_TRANSFER = 21_000
GAS_PER_BATCH_BASE = 30_000
GAS_PER_BATCH_RECIPIENT = 9_500
BATCH_GAS_BUFFER_BPS = 2000  # 20% buffer as bps

# Address validation
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ═══════════════════════════════════════════════════════════════
#  Data Classes
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DistributionItem:
    """Single recipient allocation — all Wei ints."""
    recipient: str
    amount_wei: int
    percent_bps: int


@dataclass(frozen=True)
class DistributionResult:
    """Output of calculate_distribution()."""
    items: tuple[DistributionItem, ...]
    fee_wei: int
    distributable_wei: int
    incoming_wei: int
    fee_bps: int
    fee_handling: str


@dataclass(frozen=True)
class ValidationResult:
    """Output of validate_post_execution()."""
    valid: bool
    matched: int
    mismatched: int
    missing: int
    details: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
#  Errors
# ═══════════════════════════════════════════════════════════════

class DistributionError(Exception):
    """Base distribution error."""


class InvalidRecipientsError(DistributionError):
    """Recipients list is invalid."""


class InvalidAmountError(DistributionError):
    """Incoming amount is invalid."""


class BpsError(DistributionError):
    """Basis points don't sum to 10000."""


# ═══════════════════════════════════════════════════════════════
#  DistributionService
# ═══════════════════════════════════════════════════════════════

class DistributionService:
    """Stateless fan-out distribution calculator and TX builder.

    All math uses Python int (Wei). No floats anywhere.

    Usage::

        svc = DistributionService()

        result = svc.calculate_distribution(
            incoming_amount_wei="1000000000000000000",  # 1 ETH
            fee_bps=250,                                 # 2.5%
            recipients=[
                {"address": "0xAAA...", "percent_bps": 5000},
                {"address": "0xBBB...", "percent_bps": 5000},
            ],
            fee_handling="deduct_from_total",
        )

        # Batch contract call
        calldata = svc.prepare_batch_calldata(
            result, contract_address="0xCCC..."
        )

        # Or sequential TXs
        txs = svc.prepare_sequential_txs(
            result,
            signer_address="0xDDD...",
            start_nonce=42,
            chain_id=8453,
        )
    """

    # ── calculate_distribution ────────────────────────────────

    def calculate_distribution(
        self,
        incoming_amount_wei: str,
        fee_bps: int,
        recipients: list[dict],
        fee_handling: str = "deduct_from_total",
    ) -> DistributionResult:
        """Calculate Wei distribution across recipients.

        Args:
            incoming_amount_wei: Total incoming amount as string (Wei).
            fee_bps: Platform fee in basis points (0–10000).
            recipients: List of dicts with ``address`` and ``percent_bps``.
            fee_handling: ``"deduct_from_total"`` or ``"add_on_top"``.

        Returns:
            DistributionResult with items, fee, and distributable amounts.

        Raises:
            InvalidAmountError: If amount is zero or negative.
            InvalidRecipientsError: If recipients are invalid.
            BpsError: If percent_bps don't sum to 10000.
        """
        # ── Parse and validate amount ─────────────────────────
        incoming = int(incoming_amount_wei)
        if incoming <= 0:
            raise InvalidAmountError(
                f"Incoming amount must be positive, got {incoming}"
            )

        # ── Validate fee_bps ──────────────────────────────────
        if not isinstance(fee_bps, int) or fee_bps < 0 or fee_bps > 10000:
            raise DistributionError(
                f"fee_bps must be int 0–10000, got {fee_bps}"
            )

        # ── Validate fee_handling ─────────────────────────────
        if fee_handling not in ("deduct_from_total", "add_on_top"):
            raise DistributionError(
                f"fee_handling must be 'deduct_from_total' or 'add_on_top', "
                f"got '{fee_handling}'"
            )

        # ── Validate recipients ───────────────────────────────
        if not recipients:
            raise InvalidRecipientsError("Recipients list is empty")

        addresses_seen: set[str] = set()
        total_bps = 0

        for r in recipients:
            addr = r.get("address", "")
            bps = r.get("percent_bps", 0)

            if not isinstance(addr, str) or not ADDRESS_RE.match(addr):
                raise InvalidRecipientsError(
                    f"Invalid address: {addr!r}"
                )

            addr_lower = addr.lower()
            if addr_lower in addresses_seen:
                raise InvalidRecipientsError(
                    f"Duplicate address: {addr}"
                )
            addresses_seen.add(addr_lower)

            if not isinstance(bps, int) or bps < 1 or bps > 10000:
                raise InvalidRecipientsError(
                    f"percent_bps must be int 1–10000, got {bps} for {addr}"
                )
            total_bps += bps

        if total_bps != 10000:
            raise BpsError(
                f"percent_bps must sum to 10000, got {total_bps}"
            )

        # ── Calculate fee ─────────────────────────────────────
        fee_wei = incoming * fee_bps // 10000

        if fee_handling == "deduct_from_total":
            distributable = incoming - fee_wei
        else:  # add_on_top
            distributable = incoming

        # ── Distribute across recipients ──────────────────────
        items: list[DistributionItem] = []
        allocated = 0

        for i, r in enumerate(recipients):
            addr = r["address"]
            bps = r["percent_bps"]

            if i < len(recipients) - 1:
                # All except last: floor division
                amount = distributable * bps // 10000
            else:
                # Last recipient: gets remainder (dust handling)
                amount = distributable - allocated

            items.append(DistributionItem(
                recipient=addr,
                amount_wei=amount,
                percent_bps=bps,
            ))
            allocated += amount

        # ── Post-calculation assertions ───────────────────────
        total_distributed = sum(item.amount_wei for item in items)
        assert total_distributed == distributable, (
            f"Distribution invariant violated: "
            f"sum({total_distributed}) != distributable({distributable})"
        )
        for item in items:
            assert item.amount_wei > 0, (
                f"Zero/negative amount for {item.recipient}: "
                f"{item.amount_wei}"
            )

        return DistributionResult(
            items=tuple(items),
            fee_wei=fee_wei,
            distributable_wei=distributable,
            incoming_wei=incoming,
            fee_bps=fee_bps,
            fee_handling=fee_handling,
        )

    # ── prepare_batch_calldata ────────────────────────────────

    def prepare_batch_calldata(
        self,
        distribution: DistributionResult,
        contract_address: str,
    ) -> dict:
        """Encode distributeETH(address[],uint256[]) calldata.

        Args:
            distribution: Result from calculate_distribution().
            contract_address: RSendsBatchDistributor contract address.

        Returns:
            Dict with ``to``, ``data``, ``value``, ``gas_estimate``.
        """
        addresses = [item.recipient for item in distribution.items]
        amounts = [item.amount_wei for item in distribution.items]

        # ABI encode: distributeETH(address[],uint256[])
        encoded_args = encode(
            ["address[]", "uint256[]"],
            [addresses, amounts],
        )
        calldata = DISTRIBUTE_ETH_SELECTOR + encoded_args

        # Total ETH value to send with the call
        total_value = sum(amounts)

        # Gas estimate: base + per-recipient + 20% buffer
        raw_gas = GAS_PER_BATCH_BASE + (
            GAS_PER_BATCH_RECIPIENT * len(addresses)
        )
        gas_estimate = raw_gas + (raw_gas * BATCH_GAS_BUFFER_BPS // 10000)

        return {
            "to": contract_address,
            "data": "0x" + calldata.hex(),
            "value": total_value,
            "gas_estimate": gas_estimate,
        }

    # ── prepare_sequential_txs ────────────────────────────────

    def prepare_sequential_txs(
        self,
        distribution: DistributionResult,
        signer_address: str,
        start_nonce: int,
        chain_id: int,
        gas_price_wei: Optional[int] = None,
        token_address: Optional[str] = None,
    ) -> list[dict]:
        """Build N individual transaction dicts with sequential nonces.

        Args:
            distribution: Result from calculate_distribution().
            signer_address: Hot wallet address (from field).
            start_nonce: First nonce to use.
            chain_id: EVM chain ID.
            gas_price_wei: Gas price in Wei (optional).
            token_address: ERC-20 contract address or None for ETH.

        Returns:
            List of unsigned TX dicts ready for signing.
        """
        txs: list[dict] = []

        for i, item in enumerate(distribution.items):
            nonce = start_nonce + i

            if token_address:
                # ERC-20 transfer(address,uint256)
                encoded_args = encode(
                    ["address", "uint256"],
                    [item.recipient, item.amount_wei],
                )
                data = ERC20_TRANSFER_SELECTOR + encoded_args

                tx = {
                    "from": signer_address,
                    "to": token_address,
                    "value": 0,
                    "data": "0x" + data.hex(),
                    "nonce": nonce,
                    "gas": 65_000,
                    "chainId": chain_id,
                }
            else:
                # Native ETH transfer
                tx = {
                    "from": signer_address,
                    "to": item.recipient,
                    "value": item.amount_wei,
                    "nonce": nonce,
                    "gas": GAS_PER_ETH_TRANSFER,
                    "chainId": chain_id,
                }

            if gas_price_wei is not None:
                tx["gasPrice"] = gas_price_wei

            txs.append(tx)

        return txs

    # ── validate_post_execution ───────────────────────────────

    def validate_post_execution(
        self,
        distribution: DistributionResult,
        receipt: dict,
    ) -> ValidationResult:
        """Verify on-chain SingleTransfer events match expected amounts.

        Parses ``logs`` from the transaction receipt and compares each
        event's (recipient, amount) against the distribution items.

        Args:
            distribution: The original DistributionResult.
            receipt: Transaction receipt dict from eth_getTransactionReceipt.

        Returns:
            ValidationResult with match counts and details.
        """
        logs = receipt.get("logs", [])
        details: list[dict] = []

        # Build expected map: lowercase address → amount_wei
        expected: dict[str, int] = {}
        for item in distribution.items:
            expected[item.recipient.lower()] = item.amount_wei

        matched = 0
        mismatched = 0
        found_addresses: set[str] = set()

        for log_entry in logs:
            topics = log_entry.get("topics", [])
            if not topics or topics[0] != SINGLE_TRANSFER_TOPIC:
                continue

            # Parse: topic[1] = recipient address (32 bytes, last 20)
            if len(topics) < 2:
                continue

            raw_addr = topics[1]
            # Extract last 40 hex chars (20 bytes) from the 32-byte topic
            if raw_addr.startswith("0x"):
                raw_addr = raw_addr[2:]
            recipient = "0x" + raw_addr[-40:].lower()

            # Parse amount from log data
            data = log_entry.get("data", "0x")
            if data.startswith("0x"):
                data = data[2:]
            if len(data) >= 64:
                amount = int(data[:64], 16)
            else:
                continue

            found_addresses.add(recipient)
            expected_amount = expected.get(recipient)

            if expected_amount is not None and expected_amount == amount:
                matched += 1
                details.append({
                    "recipient": recipient,
                    "expected": expected_amount,
                    "actual": amount,
                    "status": "matched",
                })
            else:
                mismatched += 1
                details.append({
                    "recipient": recipient,
                    "expected": expected_amount,
                    "actual": amount,
                    "status": "mismatched",
                })

        # Check for missing recipients (not found in logs)
        missing = 0
        for item in distribution.items:
            if item.recipient.lower() not in found_addresses:
                missing += 1
                details.append({
                    "recipient": item.recipient,
                    "expected": item.amount_wei,
                    "actual": None,
                    "status": "missing",
                })

        valid = matched == len(distribution.items) and mismatched == 0 and missing == 0

        return ValidationResult(
            valid=valid,
            matched=matched,
            mismatched=mismatched,
            missing=missing,
            details=details,
        )
