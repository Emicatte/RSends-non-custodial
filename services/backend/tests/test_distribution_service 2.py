"""
RSends Backend — Distribution Service Tests.

Tests:
  - 2 recipients 50/50
  - 3 recipients 33/33/34 (rounding)
  - 100 equal recipients
  - 500 random recipients
  - Dust always goes to last recipient
  - sum always equals distributable (property test)
  - Fee modes: deduct_from_total vs add_on_top
  - Rejects: percent!=10000, duplicates, zero amount
  - CRITICAL: verify no float anywhere in the code
"""

import ast
import inspect
import os
import random
import re

import pytest

from app.services.distribution_service import (
    BpsError,
    DistributionError,
    DistributionItem,
    DistributionResult,
    DistributionService,
    InvalidAmountError,
    InvalidRecipientsError,
    ValidationResult,
)


# ═══════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def svc():
    return DistributionService()


def _make_addr(i: int) -> str:
    """Generate a deterministic valid Ethereum address."""
    return "0x" + f"{i:040x}"


# ═══════════════════════════════════════════════════════════════
#  Basic Distribution Tests
# ═══════════════════════════════════════════════════════════════

class TestCalculateDistribution:

    def test_two_recipients_50_50(self, svc):
        """Even split between two recipients."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000000000000000000",  # 1 ETH
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )
        assert len(result.items) == 2
        assert result.items[0].amount_wei == 500000000000000000
        assert result.items[1].amount_wei == 500000000000000000
        assert result.fee_wei == 0
        assert result.distributable_wei == 1000000000000000000

    def test_two_recipients_50_50_with_fee(self, svc):
        """Even split with 2.5% fee deducted."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000000000000000000",  # 1 ETH
            fee_bps=250,  # 2.5%
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
            fee_handling="deduct_from_total",
        )
        assert result.fee_wei == 25000000000000000  # 0.025 ETH
        assert result.distributable_wei == 975000000000000000
        assert result.items[0].amount_wei == 487500000000000000
        assert result.items[1].amount_wei == 487500000000000000
        total = sum(i.amount_wei for i in result.items)
        assert total == result.distributable_wei

    def test_three_recipients_33_33_34_rounding(self, svc):
        """3-way split with rounding — dust goes to last recipient."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000000000000000000",  # 1 ETH
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 3333},
                {"address": _make_addr(2), "percent_bps": 3333},
                {"address": _make_addr(3), "percent_bps": 3334},
            ],
        )
        # First two: floor(1e18 * 3333 / 10000) = 333300000000000000
        assert result.items[0].amount_wei == 333300000000000000
        assert result.items[1].amount_wei == 333300000000000000
        # Last gets remainder: 1e18 - 2 * 333300000000000000 = 333400000000000000
        assert result.items[2].amount_wei == 333400000000000000
        total = sum(i.amount_wei for i in result.items)
        assert total == 1000000000000000000

    def test_three_equal_thirds(self, svc):
        """3 recipients at 3333/3333/3334 on an odd amount."""
        # Use an amount that doesn't divide evenly
        result = svc.calculate_distribution(
            incoming_amount_wei="1000000000000000001",  # 1 ETH + 1 wei
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 3333},
                {"address": _make_addr(2), "percent_bps": 3333},
                {"address": _make_addr(3), "percent_bps": 3334},
            ],
        )
        total = sum(i.amount_wei for i in result.items)
        assert total == 1000000000000000001
        # Dust absorbed by last
        assert result.items[2].amount_wei >= result.items[0].amount_wei

    def test_100_equal_recipients(self, svc):
        """100 recipients, each 100 bps (1%)."""
        recipients = [
            {"address": _make_addr(i), "percent_bps": 100}
            for i in range(100)
        ]
        result = svc.calculate_distribution(
            incoming_amount_wei="10000000000000000000",  # 10 ETH
            fee_bps=0,
            recipients=recipients,
        )
        assert len(result.items) == 100
        total = sum(i.amount_wei for i in result.items)
        assert total == 10000000000000000000
        # All amounts must be positive
        assert all(i.amount_wei > 0 for i in result.items)

    def test_500_random_recipients(self, svc):
        """500 recipients with random bps summing to 10000."""
        random.seed(42)  # deterministic

        # Generate 499 random breakpoints in [1, 9999]
        breakpoints = sorted(random.sample(range(1, 10000), 499))
        bps_list = []
        prev = 0
        for bp in breakpoints:
            bps_list.append(bp - prev)
            prev = bp
        bps_list.append(10000 - prev)

        assert sum(bps_list) == 10000
        assert len(bps_list) == 500

        recipients = [
            {"address": _make_addr(i), "percent_bps": bps}
            for i, bps in enumerate(bps_list)
        ]

        result = svc.calculate_distribution(
            incoming_amount_wei="123456789012345678901234",  # large amount
            fee_bps=150,  # 1.5%
            recipients=recipients,
        )
        assert len(result.items) == 500
        total = sum(i.amount_wei for i in result.items)
        assert total == result.distributable_wei
        assert all(i.amount_wei > 0 for i in result.items)


# ═══════════════════════════════════════════════════════════════
#  Dust Handling Tests
# ═══════════════════════════════════════════════════════════════

class TestDustHandling:

    def test_dust_goes_to_last_recipient(self, svc):
        """When floor division loses dust, last recipient absorbs it."""
        # 1 wei split 3 ways: each gets 0 by floor → only last gets 1?
        # Actually with 3333/3333/3334 on 7 wei:
        # first: 7 * 3333 // 10000 = 2
        # second: 7 * 3333 // 10000 = 2
        # last: 7 - 4 = 3
        result = svc.calculate_distribution(
            incoming_amount_wei="7",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 3333},
                {"address": _make_addr(2), "percent_bps": 3333},
                {"address": _make_addr(3), "percent_bps": 3334},
            ],
        )
        assert result.items[0].amount_wei == 2
        assert result.items[1].amount_wei == 2
        assert result.items[2].amount_wei == 3  # dust
        assert sum(i.amount_wei for i in result.items) == 7

    def test_dust_with_fee(self, svc):
        """Dust handling with fee deduction."""
        result = svc.calculate_distribution(
            incoming_amount_wei="100",
            fee_bps=300,  # 3%
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )
        # fee = 100 * 300 // 10000 = 3
        assert result.fee_wei == 3
        # distributable = 97
        assert result.distributable_wei == 97
        # first: 97 * 5000 // 10000 = 48
        assert result.items[0].amount_wei == 48
        # last: 97 - 48 = 49 (dust)
        assert result.items[1].amount_wei == 49
        assert sum(i.amount_wei for i in result.items) == 97

    def test_dust_property_many_splits(self, svc):
        """Property: sum always equals distributable for any valid input."""
        random.seed(99)
        for _ in range(50):
            n = random.randint(2, 20)
            bps_parts = []
            remaining = 10000
            for j in range(n - 1):
                max_part = remaining - (n - j - 1)
                part = random.randint(1, max(1, max_part))
                bps_parts.append(part)
                remaining -= part
            bps_parts.append(remaining)

            # Skip if any part is 0 or negative
            if any(b < 1 for b in bps_parts):
                continue

            recipients = [
                {"address": _make_addr(i), "percent_bps": b}
                for i, b in enumerate(bps_parts)
            ]
            amount = random.randint(1, 10**24)
            fee = random.randint(0, 5000)

            result = svc.calculate_distribution(
                incoming_amount_wei=str(amount),
                fee_bps=fee,
                recipients=recipients,
            )
            total = sum(i.amount_wei for i in result.items)
            assert total == result.distributable_wei, (
                f"Invariant broken: sum={total} != distributable="
                f"{result.distributable_wei} (n={n}, amount={amount}, fee={fee})"
            )
            assert all(i.amount_wei > 0 for i in result.items)


# ═══════════════════════════════════════════════════════════════
#  Fee Mode Tests
# ═══════════════════════════════════════════════════════════════

class TestFeeHandling:

    def test_deduct_from_total(self, svc):
        """Fee is deducted: distributable = incoming - fee."""
        result = svc.calculate_distribution(
            incoming_amount_wei="10000",
            fee_bps=1000,  # 10%
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        assert result.fee_wei == 1000
        assert result.distributable_wei == 9000
        assert result.items[0].amount_wei == 9000

    def test_add_on_top(self, svc):
        """Fee is add-on: distributable = incoming (fee is extra)."""
        result = svc.calculate_distribution(
            incoming_amount_wei="10000",
            fee_bps=1000,  # 10%
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
            fee_handling="add_on_top",
        )
        assert result.fee_wei == 1000
        assert result.distributable_wei == 10000  # full amount distributed
        assert result.items[0].amount_wei == 10000

    def test_zero_fee(self, svc):
        """Zero fee: distributable equals incoming in both modes."""
        for mode in ("deduct_from_total", "add_on_top"):
            result = svc.calculate_distribution(
                incoming_amount_wei="1000000",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 5000},
                    {"address": _make_addr(2), "percent_bps": 5000},
                ],
                fee_handling=mode,
            )
            assert result.fee_wei == 0
            assert result.distributable_wei == 1000000


# ═══════════════════════════════════════════════════════════════
#  Validation / Rejection Tests
# ═══════════════════════════════════════════════════════════════

class TestRejections:

    def test_rejects_bps_not_10000_over(self, svc):
        """Rejects if percent_bps sum > 10000."""
        with pytest.raises(BpsError, match="10000"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 6000},
                    {"address": _make_addr(2), "percent_bps": 6000},
                ],
            )

    def test_rejects_bps_not_10000_under(self, svc):
        """Rejects if percent_bps sum < 10000."""
        with pytest.raises(BpsError, match="10000"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 3000},
                    {"address": _make_addr(2), "percent_bps": 3000},
                ],
            )

    def test_rejects_duplicate_addresses(self, svc):
        """Rejects if the same address appears twice."""
        addr = _make_addr(1)
        with pytest.raises(InvalidRecipientsError, match="Duplicate"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": addr, "percent_bps": 5000},
                    {"address": addr, "percent_bps": 5000},
                ],
            )

    def test_rejects_duplicate_addresses_case_insensitive(self, svc):
        """Duplicate detection is case-insensitive."""
        with pytest.raises(InvalidRecipientsError, match="Duplicate"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": "0x" + "aA" * 20, "percent_bps": 5000},
                    {"address": "0x" + "Aa" * 20, "percent_bps": 5000},
                ],
            )

    def test_rejects_zero_amount(self, svc):
        """Rejects zero incoming amount."""
        with pytest.raises(InvalidAmountError, match="positive"):
            svc.calculate_distribution(
                incoming_amount_wei="0",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 10000},
                ],
            )

    def test_rejects_negative_amount(self, svc):
        """Rejects negative incoming amount."""
        with pytest.raises(InvalidAmountError, match="positive"):
            svc.calculate_distribution(
                incoming_amount_wei="-100",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 10000},
                ],
            )

    def test_rejects_empty_recipients(self, svc):
        """Rejects empty recipients list."""
        with pytest.raises(InvalidRecipientsError, match="empty"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[],
            )

    def test_rejects_invalid_address(self, svc):
        """Rejects malformed Ethereum address."""
        with pytest.raises(InvalidRecipientsError, match="Invalid address"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": "not-an-address", "percent_bps": 10000},
                ],
            )

    def test_rejects_zero_bps(self, svc):
        """Rejects 0 percent_bps for a recipient."""
        with pytest.raises(InvalidRecipientsError, match="percent_bps"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 0},
                    {"address": _make_addr(2), "percent_bps": 10000},
                ],
            )

    def test_rejects_invalid_fee_handling(self, svc):
        """Rejects unknown fee_handling mode."""
        with pytest.raises(DistributionError, match="fee_handling"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=0,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 10000},
                ],
                fee_handling="unknown_mode",
            )


# ═══════════════════════════════════════════════════════════════
#  Batch Calldata Tests
# ═══════════════════════════════════════════════════════════════

class TestPrepareBatchCalldata:

    def test_calldata_structure(self, svc):
        """Calldata has correct selector, value, and gas estimate."""
        result = svc.calculate_distribution(
            incoming_amount_wei="2000000000000000000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )
        contract = _make_addr(999)
        calldata = svc.prepare_batch_calldata(result, contract)

        assert calldata["to"] == contract
        assert calldata["data"].startswith("0x27945eff")
        assert calldata["value"] == 2000000000000000000
        assert isinstance(calldata["gas_estimate"], int)
        assert calldata["gas_estimate"] > 0

    def test_calldata_value_matches_distribution(self, svc):
        """Total value in calldata equals sum of all distribution items."""
        result = svc.calculate_distribution(
            incoming_amount_wei="5000000000000000000",
            fee_bps=500,
            recipients=[
                {"address": _make_addr(i), "percent_bps": 2000}
                for i in range(5)
            ],
        )
        calldata = svc.prepare_batch_calldata(result, _make_addr(999))
        assert calldata["value"] == result.distributable_wei

    def test_gas_includes_buffer(self, svc):
        """Gas estimate includes 20% buffer over base calculation."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        calldata = svc.prepare_batch_calldata(result, _make_addr(999))
        raw_gas = 30000 + 9500 * 1
        expected_gas = raw_gas + (raw_gas * 2000 // 10000)
        assert calldata["gas_estimate"] == expected_gas


# ═══════════════════════════════════════════════════════════════
#  Sequential TX Tests
# ═══════════════════════════════════════════════════════════════

class TestPrepareSequentialTxs:

    def test_correct_nonce_sequence(self, svc):
        """Each TX has a sequential nonce starting from start_nonce."""
        result = svc.calculate_distribution(
            incoming_amount_wei="3000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 3333},
                {"address": _make_addr(2), "percent_bps": 3333},
                {"address": _make_addr(3), "percent_bps": 3334},
            ],
        )
        txs = svc.prepare_sequential_txs(
            result,
            signer_address=_make_addr(100),
            start_nonce=42,
            chain_id=8453,
        )
        assert len(txs) == 3
        assert txs[0]["nonce"] == 42
        assert txs[1]["nonce"] == 43
        assert txs[2]["nonce"] == 44

    def test_eth_transfer_fields(self, svc):
        """ETH transfers have correct to, value, gas fields."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        txs = svc.prepare_sequential_txs(
            result,
            signer_address=_make_addr(100),
            start_nonce=0,
            chain_id=8453,
            gas_price_wei=1000000000,
        )
        tx = txs[0]
        assert tx["to"] == _make_addr(1)
        assert tx["value"] == 1000
        assert tx["gas"] == 21000
        assert tx["chainId"] == 8453
        assert tx["gasPrice"] == 1000000000
        assert tx["from"] == _make_addr(100)
        assert "data" not in tx

    def test_erc20_transfer_fields(self, svc):
        """ERC-20 transfers encode transfer(address,uint256) calldata."""
        token = _make_addr(50)
        result = svc.calculate_distribution(
            incoming_amount_wei="500000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        txs = svc.prepare_sequential_txs(
            result,
            signer_address=_make_addr(100),
            start_nonce=0,
            chain_id=8453,
            token_address=token,
        )
        tx = txs[0]
        assert tx["to"] == token  # send to token contract
        assert tx["value"] == 0  # no ETH value
        assert tx["gas"] == 65000
        assert tx["data"].startswith("0xa9059cbb")

    def test_amounts_match_distribution(self, svc):
        """TX values match distribution item amounts."""
        result = svc.calculate_distribution(
            incoming_amount_wei="10000",
            fee_bps=100,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 7000},
                {"address": _make_addr(2), "percent_bps": 3000},
            ],
        )
        txs = svc.prepare_sequential_txs(
            result,
            signer_address=_make_addr(100),
            start_nonce=0,
            chain_id=8453,
        )
        assert txs[0]["value"] == result.items[0].amount_wei
        assert txs[1]["value"] == result.items[1].amount_wei


# ═══════════════════════════════════════════════════════════════
#  Post-Execution Validation Tests
# ═══════════════════════════════════════════════════════════════

class TestValidatePostExecution:

    def test_valid_receipt_all_matched(self, svc):
        """All events match expected distribution."""
        result = svc.calculate_distribution(
            incoming_amount_wei="2000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )

        # Build a mock receipt with matching SingleTransfer events
        single_transfer_topic = (
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        receipt = {
            "logs": [
                {
                    "topics": [
                        single_transfer_topic,
                        "0x" + "0" * 24 + _make_addr(1)[2:],
                    ],
                    "data": "0x" + hex(1000)[2:].zfill(64),
                },
                {
                    "topics": [
                        single_transfer_topic,
                        "0x" + "0" * 24 + _make_addr(2)[2:],
                    ],
                    "data": "0x" + hex(1000)[2:].zfill(64),
                },
            ],
        }

        validation = svc.validate_post_execution(result, receipt)
        assert validation.valid is True
        assert validation.matched == 2
        assert validation.mismatched == 0
        assert validation.missing == 0

    def test_missing_event(self, svc):
        """Missing event for one recipient marks it as missing."""
        result = svc.calculate_distribution(
            incoming_amount_wei="2000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )
        receipt = {"logs": []}  # no events at all

        validation = svc.validate_post_execution(result, receipt)
        assert validation.valid is False
        assert validation.missing == 2
        assert validation.matched == 0

    def test_mismatched_amount(self, svc):
        """Wrong amount in event flags as mismatched."""
        result = svc.calculate_distribution(
            incoming_amount_wei="2000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )

        single_transfer_topic = (
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        )
        receipt = {
            "logs": [
                {
                    "topics": [
                        single_transfer_topic,
                        "0x" + "0" * 24 + _make_addr(1)[2:],
                    ],
                    "data": "0x" + hex(999)[2:].zfill(64),  # wrong amount
                },
            ],
        }

        validation = svc.validate_post_execution(result, receipt)
        assert validation.valid is False
        assert validation.mismatched == 1


# ═══════════════════════════════════════════════════════════════
#  CRITICAL: No Float Verification
# ═══════════════════════════════════════════════════════════════

class TestNoFloatInCode:
    """Verify that distribution_service.py uses NO floats for math."""

    def test_no_float_literals_in_source(self):
        """Parse the AST and ensure no float literals exist in the module."""
        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "app",
            "services",
            "distribution_service.py",
        )
        source_path = os.path.normpath(source_path)

        with open(source_path) as f:
            source = f.read()

        tree = ast.parse(source)

        float_nodes = []
        for node in ast.walk(tree):
            # Check for float literals (e.g., 0.5, 1.0)
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                float_nodes.append(
                    f"line {node.lineno}: {node.value}"
                )

        assert not float_nodes, (
            f"Float literals found in distribution_service.py:\n"
            + "\n".join(float_nodes)
        )

    def test_no_float_division_operator(self):
        """Ensure no true division (/) is used — only floor division (//)."""
        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "app",
            "services",
            "distribution_service.py",
        )
        source_path = os.path.normpath(source_path)

        with open(source_path) as f:
            source = f.read()

        tree = ast.parse(source)

        div_nodes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                div_nodes.append(f"line {node.lineno}")

        assert not div_nodes, (
            f"True division (/) found in distribution_service.py:\n"
            + "\n".join(div_nodes)
        )

    def test_no_float_builtin_calls(self):
        """Ensure float() is never called in the module."""
        source_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "app",
            "services",
            "distribution_service.py",
        )
        source_path = os.path.normpath(source_path)

        with open(source_path) as f:
            source = f.read()

        tree = ast.parse(source)

        float_calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                float_calls.append(f"line {node.lineno}")

        assert not float_calls, (
            f"float() calls found in distribution_service.py:\n"
            + "\n".join(float_calls)
        )

    def test_all_amounts_are_int_at_runtime(self, svc):
        """Runtime check: all amount fields are Python int, never float."""
        result = svc.calculate_distribution(
            incoming_amount_wei="999999999999999999",
            fee_bps=333,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 2500},
                {"address": _make_addr(2), "percent_bps": 2500},
                {"address": _make_addr(3), "percent_bps": 2500},
                {"address": _make_addr(4), "percent_bps": 2500},
            ],
        )
        assert isinstance(result.fee_wei, int)
        assert isinstance(result.distributable_wei, int)
        assert isinstance(result.incoming_wei, int)
        for item in result.items:
            assert isinstance(item.amount_wei, int), (
                f"amount_wei is {type(item.amount_wei).__name__}, not int"
            )
            assert isinstance(item.percent_bps, int)


# ═══════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_single_recipient_100_percent(self, svc):
        """Single recipient gets everything."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        assert result.items[0].amount_wei == 1
        assert len(result.items) == 1

    def test_minimum_viable_amount(self, svc):
        """1 wei with single recipient works."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        assert result.items[0].amount_wei == 1

    def test_very_large_amount(self, svc):
        """Handles amounts larger than 2^256 (Python int has no limit)."""
        huge = str(10**77)  # larger than uint256 max
        result = svc.calculate_distribution(
            incoming_amount_wei=huge,
            fee_bps=100,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 5000},
                {"address": _make_addr(2), "percent_bps": 5000},
            ],
        )
        total = sum(i.amount_wei for i in result.items)
        assert total == result.distributable_wei

    def test_max_fee_10000_bps(self, svc):
        """100% fee leaves 0 distributable — should fail assertion."""
        # 100% fee means distributable = 0, and then distribution fails
        # because amounts would be 0
        with pytest.raises(AssertionError, match="Zero/negative"):
            svc.calculate_distribution(
                incoming_amount_wei="1000",
                fee_bps=10000,
                recipients=[
                    {"address": _make_addr(1), "percent_bps": 10000},
                ],
            )

    def test_result_is_immutable(self, svc):
        """DistributionResult is a frozen dataclass."""
        result = svc.calculate_distribution(
            incoming_amount_wei="1000",
            fee_bps=0,
            recipients=[
                {"address": _make_addr(1), "percent_bps": 10000},
            ],
        )
        with pytest.raises(AttributeError):
            result.fee_wei = 999

    def test_checksum_and_lowercase_addresses(self, svc):
        """Mixed-case addresses are accepted (EIP-55 compatible)."""
        addr = "0xAaBbCcDdEeFf00112233445566778899AaBbCcDd"
        result = svc.calculate_distribution(
            incoming_amount_wei="1000",
            fee_bps=0,
            recipients=[
                {"address": addr, "percent_bps": 10000},
            ],
        )
        assert result.items[0].recipient == addr
