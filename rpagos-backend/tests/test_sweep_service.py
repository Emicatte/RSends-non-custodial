"""
RPagos Backend — Test: Sweep Service Logic

Testa la logica interna del sweep_service v3 SENZA fare chiamate RPC reali:
  - Threshold check (via process_incoming_tx flow)
  - Cooldown enforcement
  - Gas limit check
  - Schedule check (day/hour/timezone)
  - Split routing calculation
  - Max daily volume
  - Token filter
  - ERC-20 calldata building
  - Token unit conversion

Come eseguire:
  cd rpagos-backend
  DATABASE_URL="sqlite+aiosqlite://" DEBUG=1 pytest tests/test_sweep_service.py -v
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

from app.db.session import engine, async_session
from app.models.db_models import Base
from app.models.forwarding_models import (
    ForwardingRule, SweepLog, SweepStatus, GasStrategy,
)
from app.services.sweep_service import (
    _check_schedule,
    _check_token_filter,
    _build_erc20_transfer_data,
    _get_token_decimals,
    _human_to_token_units,
    _is_transient,
    TOKEN_REGISTRY,
    GAS_MULT,
    validate_all_conditions,
    _check_cooldown,
    _check_daily_volume,
    _check_gas_limit,
)


# ── Helpers ───────────────────────────────────────────────

from contextlib import contextmanager


@contextmanager
def patch_rpc():
    """Patch the RPC layer used by sweep_service. The old module-level
    _rpc_call(chain, method, params) was replaced by
    get_rpc_manager(chain).call(method, params); this yields the manager's
    `.call` AsyncMock so existing `mock_rpc.return_value/side_effect` usage
    keeps working."""
    mock_call = AsyncMock()
    mgr = MagicMock()
    mgr.call = mock_call
    with patch("app.services.sweep_service.get_rpc_manager", return_value=mgr):
        yield mock_call


# ── Fixtures ──────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Crea e distrugge le tabelle per ogni test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _make_rule(**overrides) -> ForwardingRule:
    """Crea un oggetto ForwardingRule in-memory per i test."""
    defaults = {
        "id": 1,
        "user_id": "0x" + "aa" * 20,
        "source_wallet": "0x" + "bb" * 20,
        "destination_wallet": "0x" + "cc" * 20,
        "is_active": True,
        "is_paused": False,
        "min_threshold": 0.01,
        "gas_strategy": GasStrategy.normal,
        "max_gas_percent": 10.0,
        "gas_limit_gwei": 50,
        "cooldown_sec": 60,
        "max_daily_vol": None,
        "token_address": None,
        "token_symbol": "ETH",
        "token_filter": None,
        "schedule_json": None,
        "chain_id": 8453,
        "split_enabled": False,
        "split_percent": 100,
        "split_destination": None,
        "notify_enabled": False,
    }
    defaults.update(overrides)
    rule = ForwardingRule()
    for k, v in defaults.items():
        setattr(rule, k, v)
    return rule


# ═══════════════════════════════════════════════════════════
#  1. Schedule Check
# ═══════════════════════════════════════════════════════════

class TestScheduleCheck:
    """Test _check_schedule validation."""

    def test_no_schedule(self):
        """Nessun schedule → sempre OK."""
        rule = _make_rule(schedule_json=None)
        ok, reason = _check_schedule(rule)
        assert ok is True
        assert reason is None

    def test_schedule_within_hours(self):
        """Ora corrente dentro la finestra → OK."""
        now_hour = datetime.now().hour
        rule = _make_rule(schedule_json={
            "hours_start": 0,
            "hours_end": 24,
            "timezone": "UTC",
        })
        ok, reason = _check_schedule(rule)
        assert ok is True

    def test_schedule_outside_hours(self):
        """Ora corrente fuori dalla finestra → FAIL."""
        now_hour = datetime.now().hour
        # Crea una finestra che esclude l'ora corrente
        bad_start = (now_hour + 2) % 24
        bad_end = (now_hour + 4) % 24
        if bad_start >= bad_end:
            bad_start, bad_end = 0, 0  # skip if wraps

        if bad_start < bad_end:
            rule = _make_rule(schedule_json={
                "hours_start": bad_start,
                "hours_end": bad_end,
                "timezone": "UTC",
            })
            ok, reason = _check_schedule(rule)
            assert ok is False
            assert "Schedule" in reason

    def test_schedule_wrong_day(self):
        """Giorno corrente non in lista → FAIL."""
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("UTC")).weekday()
        # Exclude today
        other_days = [d for d in range(7) if d != today]
        rule = _make_rule(schedule_json={
            "days": other_days,
            "timezone": "UTC",
        })
        ok, reason = _check_schedule(rule)
        assert ok is False
        assert "day" in reason.lower()

    def test_schedule_correct_day(self):
        """Giorno corrente in lista → OK."""
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("UTC")).weekday()
        rule = _make_rule(schedule_json={
            "days": [today],
            "hours_start": 0,
            "hours_end": 24,
            "timezone": "UTC",
        })
        ok, reason = _check_schedule(rule)
        assert ok is True

    def test_schedule_invalid_timezone(self):
        """Timezone non valida → fallback a UTC."""
        rule = _make_rule(schedule_json={
            "hours_start": 0,
            "hours_end": 24,
            "timezone": "Invalid/Zone",
        })
        ok, reason = _check_schedule(rule)
        assert ok is True  # Falls back to UTC, 0-24 is always valid


# ═══════════════════════════════════════════════════════════
#  2. Token Filter
# ═══════════════════════════════════════════════════════════

class TestTokenFilter:
    """Test _check_token_filter validation."""

    def test_no_filter(self):
        """Nessun filtro → tutto accettato."""
        rule = _make_rule(token_filter=None)
        ok, reason = _check_token_filter(rule, "ETH")
        assert ok is True

    def test_empty_filter(self):
        """Filtro vuoto → tutto accettato."""
        rule = _make_rule(token_filter=[])
        ok, reason = _check_token_filter(rule, "USDC")
        assert ok is True

    def test_token_in_filter(self):
        """Token presente nel filtro → OK."""
        rule = _make_rule(token_filter=["ETH", "USDC"])
        ok, reason = _check_token_filter(rule, "usdc")
        assert ok is True  # Case-insensitive

    def test_token_not_in_filter(self):
        """Token non presente nel filtro → FAIL."""
        rule = _make_rule(token_filter=["USDC", "USDT"])
        ok, reason = _check_token_filter(rule, "ETH")
        assert ok is False
        assert "not in filter" in reason


# ═══════════════════════════════════════════════════════════
#  3. Gas Limit Check
# ═══════════════════════════════════════════════════════════

class TestGasLimit:
    """Test _check_gas_limit — mock RPC."""

    @pytest.mark.asyncio
    async def test_gas_below_limit(self):
        """Gas sotto il limite → OK."""
        # 10 gwei = 10 * 1e9 = 10000000000 = 0x2540be400
        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(10 * 1e9))
            ok, gas_gwei, reason = await _check_gas_limit(8453, 50)
            assert ok is True
            assert abs(gas_gwei - 10.0) < 0.01

    @pytest.mark.asyncio
    async def test_gas_above_limit(self):
        """Gas sopra il limite → FAIL."""
        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(100 * 1e9))
            ok, gas_gwei, reason = await _check_gas_limit(8453, 50)
            assert ok is False
            assert "100" in reason  # gas value in message

    @pytest.mark.asyncio
    async def test_gas_rpc_failure(self):
        """RPC failure → fail-open (OK)."""
        with patch_rpc() as mock_rpc:
            mock_rpc.side_effect = Exception("RPC down")
            ok, gas_gwei, reason = await _check_gas_limit(8453, 50)
            assert ok is True  # fail-open


# ═══════════════════════════════════════════════════════════
#  4. Cooldown Enforcement
# ═══════════════════════════════════════════════════════════

class TestCooldown:
    """Test _check_cooldown — uses DB."""

    @pytest.mark.asyncio
    async def test_no_previous_sweep(self):
        """Nessun sweep precedente → OK."""
        rule = _make_rule(cooldown_sec=60)
        ok, reason = await _check_cooldown(rule)
        assert ok is True

    @pytest.mark.asyncio
    async def test_cooldown_zero(self):
        """Cooldown = 0 → sempre OK."""
        rule = _make_rule(cooldown_sec=0)
        ok, reason = await _check_cooldown(rule)
        assert ok is True

    @pytest.mark.asyncio
    async def test_cooldown_not_elapsed(self):
        """Sweep recente → cooldown non elapsed."""
        rule = _make_rule(cooldown_sec=3600)  # 1 hour

        # Inserisci un sweep log recente
        # Nota: SQLite non gestisce tz-aware — usa naive UTC
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            db.add(ForwardingRule(
                id=1, user_id=rule.user_id,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                chain_id=rule.chain_id,
            ))
            await db.flush()

            log = SweepLog(
                rule_id=1,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                amount_wei="1000000000000000000",
                amount_human=1.0,
                status=SweepStatus.completed,
                executed_at=now,
            )
            db.add(log)
            await db.commit()

        # Mock datetime.now(utc) to match the naive datetime from SQLite
        with patch("app.services.sweep_service.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, reason = await _check_cooldown(rule)

        assert ok is False
        assert "remaining" in reason.lower()

    @pytest.mark.asyncio
    async def test_cooldown_elapsed(self):
        """Sweep vecchio → cooldown elapsed."""
        rule = _make_rule(cooldown_sec=60)

        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=120)

        async with async_session() as db:
            db.add(ForwardingRule(
                id=1, user_id=rule.user_id,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                chain_id=rule.chain_id,
            ))
            await db.flush()

            log = SweepLog(
                rule_id=1,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                amount_wei="1000000000000000000",
                amount_human=1.0,
                status=SweepStatus.completed,
                executed_at=old,
            )
            db.add(log)
            await db.commit()

        with patch("app.services.sweep_service.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            ok, reason = await _check_cooldown(rule)

        assert ok is True


# ═══════════════════════════════════════════════════════════
#  5. Max Daily Volume
# ═══════════════════════════════════════════════════════════

class TestDailyVolume:
    """Test _check_daily_volume — uses DB."""

    @pytest.mark.asyncio
    async def test_no_limit(self):
        """Nessun limite → OK."""
        rule = _make_rule(max_daily_vol=None)
        ok, reason = await _check_daily_volume(rule)
        assert ok is True

    @pytest.mark.asyncio
    async def test_volume_under_limit(self):
        """Volume sotto il limite → OK."""
        rule = _make_rule(max_daily_vol=Decimal("10.0"))

        async with async_session() as db:
            db.add(ForwardingRule(
                id=1, user_id=rule.user_id,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                chain_id=rule.chain_id,
            ))
            await db.flush()

            log = SweepLog(
                rule_id=1,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                amount_wei="5000000000000000000",
                amount_human=5.0,
                status=SweepStatus.completed,
            )
            db.add(log)
            await db.commit()

        ok, reason = await _check_daily_volume(rule)
        assert ok is True

    @pytest.mark.asyncio
    async def test_volume_over_limit(self):
        """Volume sopra il limite → FAIL.

        Nota: _check_daily_volume usa cast(created_at, Date) == today.
        Su SQLite il cast a Date non funziona come su PostgreSQL,
        quindi il confronto data non matcha. Testiamo la logica
        passando direttamente al confronto numerico.
        """
        rule = _make_rule(max_daily_vol=Decimal("5.0"))

        # Inseriamo un sweep log e poi verifichiamo manualmente
        # che la funzione restituisca FAIL quando il volume è sopra
        async with async_session() as db:
            db.add(ForwardingRule(
                id=1, user_id=rule.user_id,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                chain_id=rule.chain_id,
            ))
            await db.flush()

            log = SweepLog(
                rule_id=1,
                source_wallet=rule.source_wallet,
                destination_wallet=rule.destination_wallet,
                amount_wei="6000000000000000000",
                amount_human=6.0,
                status=SweepStatus.completed,
                created_at=datetime.now(timezone.utc),
            )
            db.add(log)
            await db.commit()

        # On SQLite, cast(DateTime, Date) doesn't work reliably.
        # The production DB (PostgreSQL) handles this correctly.
        # Here we verify the logic by mocking the DB query result.
        with patch("app.services.sweep_service.async_session") as mock_session_ctx:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar.return_value = 6.0  # Simulate volume = 6.0
            mock_db.execute.return_value = mock_result
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            ok, reason = await _check_daily_volume(rule)

        assert ok is False
        assert "Daily volume limit" in reason


# ═══════════════════════════════════════════════════════════
#  6. Split Routing Calculation
# ═══════════════════════════════════════════════════════════

class TestSplitRouting:
    """Test split percentage calculations."""

    def test_split_70_30(self):
        """70/30 split di 1 ETH."""
        total_raw = _human_to_token_units(1.0, 18)
        pct1 = 70
        pct2 = 30
        amt1 = (total_raw * pct1) // 100
        amt2 = total_raw - amt1
        assert amt1 + amt2 == total_raw
        # 70% of 1e18
        assert amt1 == 700000000000000000
        assert amt2 == 300000000000000000

    def test_split_50_50(self):
        """50/50 split di 1 USDC (6 decimals)."""
        total_raw = _human_to_token_units(100.0, 6)
        pct1 = 50
        amt1 = (total_raw * pct1) // 100
        amt2 = total_raw - amt1
        assert amt1 == 50_000_000
        assert amt2 == 50_000_000

    def test_split_99_1(self):
        """99/1 split estremo."""
        total_raw = _human_to_token_units(10.0, 18)
        pct1 = 99
        amt1 = (total_raw * pct1) // 100
        amt2 = total_raw - amt1
        assert amt1 + amt2 == total_raw
        assert amt2 > 0


# ═══════════════════════════════════════════════════════════
#  7. ERC-20 Calldata Building
# ═══════════════════════════════════════════════════════════

class TestERC20:
    """Test ERC-20 transfer calldata building."""

    def test_build_transfer_data(self):
        """Genera calldata ERC-20 transfer corretto."""
        to = "0x" + "cc" * 20
        amount = 1_000_000  # 1 USDC (6 decimals)

        data = _build_erc20_transfer_data(to, amount)

        # Deve iniziare con il selector a9059cbb
        assert data.startswith("0xa9059cbb")
        # Lunghezza: 0x + 8 (selector) + 64 (address) + 64 (amount) = 138
        assert len(data) == 138
        # L'indirizzo deve essere presente (padded)
        assert "cc" * 20 in data

    def test_build_transfer_large_amount(self):
        """Gestisce importi grandi (18 decimals)."""
        to = "0x" + "dd" * 20
        amount = 10 ** 18  # 1 ETH in wei

        data = _build_erc20_transfer_data(to, amount)
        assert data.startswith("0xa9059cbb")
        assert len(data) == 138

    def test_get_token_decimals_known(self):
        """Token conosciuto dal registry → decimali corretti."""
        assert _get_token_decimals(8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913") == 6  # USDC
        assert _get_token_decimals(8453, "0x4200000000000000000000000000000000000006") == 18  # WETH

    def test_get_token_decimals_unknown(self):
        """Token sconosciuto → default 18."""
        assert _get_token_decimals(8453, "0x" + "ff" * 20) == 18

    def test_human_to_token_units(self):
        """Conversione human → raw units."""
        assert _human_to_token_units(1.0, 18) == 10 ** 18
        assert _human_to_token_units(100.0, 6) == 100_000_000
        assert _human_to_token_units(0.5, 8) == 50_000_000
        assert _human_to_token_units(1.123456, 6) == 1_123_456

    def test_human_to_token_units_precision(self):
        """Conversione decimal-safe (no floating point drift)."""
        # 0.1 + 0.2 != 0.3 in float, ma Decimal lo gestisce
        result = _human_to_token_units(0.1, 18)
        assert result == 100_000_000_000_000_000


# ═══════════════════════════════════════════════════════════
#  8. Transient Error Detection
# ═══════════════════════════════════════════════════════════

class TestTransientErrors:
    """Test _is_transient helper."""

    def test_transient_nonce(self):
        assert _is_transient("nonce too low") is True
        assert _is_transient("Nonce Too High for next block") is True

    def test_transient_timeout(self):
        assert _is_transient("Request timeout after 15s") is True

    def test_transient_connection(self):
        assert _is_transient("Connection reset by peer") is True

    def test_permanent_balance(self):
        assert _is_transient("insufficient funds for transfer") is False

    def test_permanent_reverted(self):
        assert _is_transient("execution reverted: ERC20: transfer amount exceeds balance") is False

    def test_empty(self):
        assert _is_transient("") is False
        assert _is_transient(None) is False


# ═══════════════════════════════════════════════════════════
#  9. Token Registry
# ═══════════════════════════════════════════════════════════

class TestTokenRegistry:
    """Test TOKEN_REGISTRY completeness."""

    def test_usdc_base(self):
        info = TOKEN_REGISTRY.get((8453, "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"))
        assert info is not None
        assert info["symbol"] == "USDC"
        assert info["decimals"] == 6

    def test_weth_base(self):
        info = TOKEN_REGISTRY.get((8453, "0x4200000000000000000000000000000000000006"))
        assert info is not None
        assert info["symbol"] == "WETH"
        assert info["decimals"] == 18

    def test_cbbtc_base(self):
        info = TOKEN_REGISTRY.get((8453, "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"))
        assert info is not None
        assert info["symbol"] == "cbBTC"
        assert info["decimals"] == 8


# ═══════════════════════════════════════════════════════════
#  10. Gas Strategy Multipliers
# ═══════════════════════════════════════════════════════════

class TestGasStrategy:
    """Test GAS_MULT values."""

    def test_multiplier_values(self):
        assert GAS_MULT[GasStrategy.fast] == 1.5
        assert GAS_MULT[GasStrategy.normal] == 1.1
        assert GAS_MULT[GasStrategy.slow] == 0.9

    def test_fast_higher_than_normal(self):
        assert GAS_MULT[GasStrategy.fast] > GAS_MULT[GasStrategy.normal]

    def test_normal_higher_than_slow(self):
        assert GAS_MULT[GasStrategy.normal] > GAS_MULT[GasStrategy.slow]


# ═══════════════════════════════════════════════════════════
#  11. validate_all_conditions (integrated)
# ═══════════════════════════════════════════════════════════

class TestValidateAll:
    """Test validate_all_conditions — mock RPC, uses DB."""

    @pytest.mark.asyncio
    async def test_all_pass(self):
        """Tutte le condizioni soddisfatte → OK."""
        rule = _make_rule(cooldown_sec=0, schedule_json=None, max_daily_vol=None)

        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(5 * 1e9))  # 5 gwei gas
            ok, reason = await validate_all_conditions(rule, "ETH")
            assert ok is True
            assert reason is None

    @pytest.mark.asyncio
    async def test_schedule_blocks(self):
        """Schedule non soddisfatto → FAIL."""
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("UTC")).weekday()
        other_days = [d for d in range(7) if d != today]

        rule = _make_rule(
            cooldown_sec=0,
            schedule_json={"days": other_days, "timezone": "UTC"},
        )

        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(5 * 1e9))
            ok, reason = await validate_all_conditions(rule, "ETH")
            assert ok is False
            assert "Schedule" in reason

    @pytest.mark.asyncio
    async def test_token_filter_blocks(self):
        """Token filter non soddisfatto → FAIL."""
        rule = _make_rule(
            cooldown_sec=0,
            token_filter=["USDC"],
        )

        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(5 * 1e9))
            ok, reason = await validate_all_conditions(rule, "ETH")
            assert ok is False
            assert "not in filter" in reason

    @pytest.mark.asyncio
    async def test_gas_limit_blocks(self):
        """Gas troppo alto → FAIL."""
        rule = _make_rule(cooldown_sec=0, gas_limit_gwei=10)

        with patch_rpc() as mock_rpc:
            mock_rpc.return_value = hex(int(50 * 1e9))  # 50 gwei > limit 10
            ok, reason = await validate_all_conditions(rule, "ETH")
            assert ok is False
            assert "gwei" in reason.lower()
