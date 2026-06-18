"""
RSend AML Service — Anti-Money Laundering checks (3 livelli).

1. ADDRESS SCREENING (pre-transazione)
   - OFAC SDN List (US sanctions)
   - EU Consolidated Sanctions List
   - Database locale (sanctions_list + blacklisted_wallets)
   - Hardcoded Tornado Cash addresses

2. TRANSACTION MONITORING (post-transazione)
   - Single tx > €1,000 → flag per review
   - Daily cumulative per wallet > €5,000 → flag
   - Monthly cumulative per wallet > €15,000 → KYC required (DAC8)
   - > 10 tx/hour → velocity alert
   - Structuring detection (many tx just below threshold)

3. REPORTING
   - Creates AMLAlert records for compliance officers
   - Integrates with DAC8 service for regulatory reporting

Backward-compatible: screen_transaction() and is_blacklisted() keep
the same signature for existing callers in sweep_service.py.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import select, func

from app.db.session import async_session
from app.models.aml_models import (
    BlacklistedWallet,
    SanctionEntry,
    AMLAlert,
    AMLConfig,
    AlertType,
    RiskLevel,
    AlertStatus,
)

logger = logging.getLogger("aml")

# Lua script: atomic increment + SET EX in a single Redis call.
# Prevents the race where concurrent INCRBYFLOAT + EXPIRE are not atomic,
# and where multiple callers read a stale total before any increment lands.
_AML_DAILY_INCR_LUA = """
local key = KEYS[1]
local add_amount = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = tonumber(redis.call('GET', key) or '0')
local new_total = current + add_amount
redis.call('SET', key, tostring(new_total), 'EX', ttl)
return tostring(new_total)
"""


# ═══════════════════════════════════════════════════════════════
#  Well-known sanctioned addresses (always checked, no DB needed)
# ═══════════════════════════════════════════════════════════════

HARDCODED_BLACKLIST: dict[str, str] = {
    # Tornado Cash (OFAC SDN — CYBER2 program)
    "0x8589427373d6d84e98730d7795d8f6f8731fda16": "Tornado Cash: Proxy",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b": "Tornado Cash: Router",
    "0xd96f2b1cf787cf7e7f2fe874e2b540fb32995cb8": "Tornado Cash: Vault",
    "0x4736dcf1b7a3d580672cce6e7c65cd5cc9cfbf68": "Tornado Cash: Mining",
    "0x722122df12d4e14e13ac3b6895a86e84145b6967": "Tornado Cash: 0.1 ETH",
    "0xdd4c48c0b24039969fc16d1cdf626eab821d3384": "Tornado Cash: 1 ETH",
    "0xd4b88df4d29f5cedd6857912842cff3b20c8cfa3": "Tornado Cash: 10 ETH",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf": "Tornado Cash: 100 ETH",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291": "Tornado Cash: 100 ETH (2)",
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc": "Tornado Cash: 0.1 ETH (2)",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936": "Tornado Cash: 1 ETH (2)",
    "0x23773e65ed146a459791799d01336db287f25334": "Tornado Cash: 10 ETH (2)",
    # Lazarus Group (DPRK)
    "0x098b716b8aaf21512996dc57eb0615e2383e2f96": "Lazarus Group",
    "0xa0e1c89ef1a489c9c7de96311ed5ce5d32c20e4b": "Lazarus Group (2)",
    # Blender.io (OFAC SDN)
    "0xb6f5ec1a0a9cd1526536d3f0426c429529471f40": "Blender.io",
}


# ═══════════════════════════════════════════════════════════════
#  AML Check Result (returned by all check functions)
# ═══════════════════════════════════════════════════════════════

@dataclass
class AMLCheckResult:
    approved: bool
    risk_level: str              # "low", "medium", "high", "blocked"
    alerts: list[str] = field(default_factory=list)
    details: str = ""
    requires_kyc: bool = False
    requires_manual_review: bool = False
    blocked: bool = False        # backward-compat with screen_transaction()


# ═══════════════════════════════════════════════════════════════
#  Default thresholds (overridden by AMLConfig in DB)
# ═══════════════════════════════════════════════════════════════

_DEFAULT_THRESHOLD_SINGLE_EUR = 1000.0
_DEFAULT_THRESHOLD_DAILY_EUR = 5000.0
_DEFAULT_THRESHOLD_MONTHLY_EUR = 15000.0
_DEFAULT_VELOCITY_LIMIT = 10


async def _get_thresholds() -> dict:
    """Load AML thresholds from DB, fallback to defaults."""
    try:
        async with async_session() as db:
            result = await db.execute(select(AMLConfig).where(AMLConfig.id == 1))
            cfg = result.scalar_one_or_none()
            if cfg:
                return {
                    "single": cfg.threshold_single_eur,
                    "daily": cfg.threshold_daily_eur,
                    "monthly": cfg.threshold_monthly_eur,
                    "velocity": cfg.velocity_limit_per_hour,
                    "structuring_window_hours": cfg.structuring_window_hours,
                    "structuring_min_count": cfg.structuring_min_count,
                    "structuring_threshold_pct": cfg.structuring_threshold_pct,
                }
    except Exception as e:
        logger.warning("AML config load failed (using defaults): %s", e)

    return {
        "single": _DEFAULT_THRESHOLD_SINGLE_EUR,
        "daily": _DEFAULT_THRESHOLD_DAILY_EUR,
        "monthly": _DEFAULT_THRESHOLD_MONTHLY_EUR,
        "velocity": _DEFAULT_VELOCITY_LIMIT,
        "structuring_window_hours": 24,
        "structuring_min_count": 5,
        "structuring_threshold_pct": 0.9,
    }


# ═══════════════════════════════════════════════════════════════
#  1. ADDRESS SCREENING
# ═══════════════════════════════════════════════════════════════

async def is_blacklisted(address: str) -> tuple[bool, Optional[str]]:
    """Check if an address is blacklisted/sanctioned.

    Returns (is_blocked, reason).
    Backward-compatible with existing callers.
    """
    addr_lower = address.lower()

    # Hardcoded list (always available, even without DB)
    if addr_lower in HARDCODED_BLACKLIST:
        return True, f"OFAC sanctioned: {HARDCODED_BLACKLIST[addr_lower]}"

    # Check sanctions_list table
    try:
        async with async_session() as db:
            result = await db.execute(
                select(SanctionEntry).where(
                    SanctionEntry.address == addr_lower,
                    SanctionEntry.is_active == True,  # noqa: E712
                ).limit(1)
            )
            entry = result.scalar_one_or_none()
            if entry:
                return True, (
                    f"Sanctioned: {entry.name or 'Unknown'} "
                    f"(source: {entry.source}, program: {entry.program or 'N/A'})"
                )
    except Exception as e:
        logger.warning("Sanctions DB check failed (continuing with legacy): %s", e)

    # Legacy blacklisted_wallets table
    try:
        async with async_session() as db:
            result = await db.execute(
                select(BlacklistedWallet).where(
                    BlacklistedWallet.address == addr_lower,
                    BlacklistedWallet.is_active == True,  # noqa: E712
                )
            )
            entry = result.scalar_one_or_none()
            if entry:
                return True, f"Blacklisted: {entry.reason} (source: {entry.source})"
    except Exception as e:
        from app.services.aml_exceptions import AMLBlockedError
        logger.error("AML DB check failed (fail-closed): %s", e)
        raise AMLBlockedError(f"AML screening unavailable: {e}")

    return False, None


async def screen_addresses(sender: str, recipient: str) -> AMLCheckResult:
    """Screen both sender and recipient against sanctions lists."""
    for addr, role in [(sender, "Sender"), (recipient, "Recipient")]:
        blocked, reason = await is_blacklisted(addr)
        if blocked:
            return AMLCheckResult(
                approved=False,
                risk_level="blocked",
                alerts=[f"{role} sanctioned: {reason}"],
                details=f"{role} {addr[:10]}... matches sanctions/blacklist",
                blocked=True,
            )
    return AMLCheckResult(approved=True, risk_level="low")


# ═══════════════════════════════════════════════════════════════
#  2. TRANSACTION MONITORING
# ═══════════════════════════════════════════════════════════════

async def _get_daily_total_eur(sender: str) -> float:
    """Get daily EUR total from Redis (fast) with DB fallback."""
    sender_lower = sender.lower()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    redis_key = f"aml:daily:{sender_lower}:{today}"

    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        if r:
            cached = await r.get(redis_key)
            if cached is not None:
                return float(cached)
    except Exception:
        pass

    # Fallback: query AMLAlert table for today's amounts
    try:
        start_of_day = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with async_session() as db:
            result = await db.execute(
                select(func.coalesce(func.sum(AMLAlert.amount_eur), 0.0)).where(
                    AMLAlert.sender == sender_lower,
                    AMLAlert.created_at >= start_of_day,
                )
            )
            return float(result.scalar_one())
    except Exception as e:
        from app.services.aml_exceptions import AMLDataUnavailableError
        raise AMLDataUnavailableError(f"Daily total unavailable: {e}")


async def _update_daily_total(sender: str, add_eur: float) -> float:
    """Atomically increment daily EUR total in Redis. Returns new total."""
    sender_lower = sender.lower()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    redis_key = f"aml:daily:{sender_lower}:{today}"

    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        if not r:
            from app.services.aml_exceptions import AMLDataUnavailableError
            raise AMLDataUnavailableError("Redis unavailable for daily total update")
        result = await r.eval(_AML_DAILY_INCR_LUA, 1, redis_key, str(add_eur), "86400")
        return float(result)
    except AMLDataUnavailableError:
        raise
    except Exception as e:
        from app.services.aml_exceptions import AMLDataUnavailableError
        raise AMLDataUnavailableError(f"Daily total update failed: {e}")


async def _get_monthly_total_eur(sender: str) -> float:
    """Get 30-day rolling EUR total from Postgres."""
    sender_lower = sender.lower()
    since = datetime.now(timezone.utc) - timedelta(days=30)

    try:
        async with async_session() as db:
            result = await db.execute(
                select(func.coalesce(func.sum(AMLAlert.amount_eur), 0.0)).where(
                    AMLAlert.sender == sender_lower,
                    AMLAlert.created_at >= since,
                )
            )
            return float(result.scalar_one())
    except Exception as e:
        from app.services.aml_exceptions import AMLDataUnavailableError
        raise AMLDataUnavailableError(f"Monthly total unavailable: {e}")


async def _get_velocity_count(sender: str) -> int:
    """Get hourly transaction count from Redis."""
    sender_lower = sender.lower()
    redis_key = f"aml:velocity:{sender_lower}"

    try:
        from app.services.cache_service import get_redis
        r = await get_redis()
        if not r:
            from app.services.aml_exceptions import AMLDataUnavailableError
            raise AMLDataUnavailableError("Redis unavailable for velocity count")
        count = await r.incr(redis_key)
        if count == 1:
            await r.expire(redis_key, 3600)
        return int(count)
    except AMLDataUnavailableError:
        raise
    except Exception as e:
        from app.services.aml_exceptions import AMLDataUnavailableError
        raise AMLDataUnavailableError(f"Velocity count unavailable: {e}")


async def _check_structuring(
    sender: str,
    amount_eur: float,
    threshold_single: float,
    cfg: dict,
) -> bool:
    """Detect structuring: many transactions just below the single threshold.

    Returns True if structuring pattern detected.
    """
    sender_lower = sender.lower()
    window = timedelta(hours=cfg["structuring_window_hours"])
    since = datetime.now(timezone.utc) - window
    near_threshold = threshold_single * cfg["structuring_threshold_pct"]

    # Only trigger if current amount is suspiciously close to threshold
    if amount_eur < near_threshold:
        return False

    try:
        async with async_session() as db:
            result = await db.execute(
                select(func.count()).select_from(AMLAlert).where(
                    AMLAlert.sender == sender_lower,
                    AMLAlert.created_at >= since,
                    AMLAlert.amount_eur >= near_threshold,
                    AMLAlert.amount_eur < threshold_single,
                )
            )
            count = result.scalar_one()
            return count >= cfg["structuring_min_count"]
    except Exception:
        return True


async def monitor_transaction(
    sender: str,
    recipient: str,
    amount_eur: float,
    *,
    chain_id: int = 0,
    tx_hash: Optional[str] = None,
    token_symbol: str = "ETH",
) -> AMLCheckResult:
    """Post-transaction monitoring: thresholds, velocity, structuring.

    Does NOT block transactions (approved is always True unless sanctioned).
    Creates AMLAlert records for compliance review.
    """
    from app.services.aml_exceptions import AMLDataUnavailableError

    alerts: list[str] = []
    risk = "low"
    requires_kyc = False
    requires_review = False
    daily_total = 0.0
    monthly_total = 0.0
    velocity = 0

    cfg = await _get_thresholds()

    # ── Single transaction threshold ─────────────────────
    if amount_eur > cfg["single"]:
        alerts.append(AlertType.threshold_single.value)
        risk = "medium"
        requires_review = True

    # ── Daily cumulative ─────────────────────────────────
    try:
        daily_total = await _update_daily_total(sender, amount_eur)
        if daily_total > cfg["daily"]:
            alerts.append(AlertType.threshold_daily.value)
            risk = "high"
            requires_review = True
    except AMLDataUnavailableError:
        logger.error("AML daily counter unavailable — forcing review (fail-closed)")
        risk = "high"
        requires_review = True

    # ── Monthly cumulative (DAC8: >€15K → KYC required) ──
    try:
        monthly_total = await _get_monthly_total_eur(sender) + amount_eur
        if monthly_total > cfg["monthly"]:
            alerts.append(AlertType.threshold_monthly.value)
            risk = "high"
            requires_kyc = True
            requires_review = True
    except AMLDataUnavailableError:
        logger.error("AML monthly counter unavailable — forcing review (fail-closed)")
        risk = "high"
        requires_review = True

    # ── Velocity check ───────────────────────────────────
    try:
        velocity = await _get_velocity_count(sender)
        if velocity > cfg["velocity"]:
            alerts.append(AlertType.velocity.value)
            risk = "high"
            requires_review = True
    except AMLDataUnavailableError:
        logger.error("AML velocity counter unavailable — forcing review (fail-closed)")
        risk = "high"
        requires_review = True

    # ── Structuring detection ────────────────────────────
    if await _check_structuring(sender, amount_eur, cfg["single"], cfg):
        alerts.append(AlertType.structuring.value)
        risk = "high"
        requires_review = True

    # ── Persist alerts to DB ─────────────────────────────
    if alerts:
        details = (
            f"Daily: €{daily_total:.0f}, Monthly: €{monthly_total:.0f}, "
            f"Velocity: {velocity}/h"
        )
        for alert_type_str in alerts:
            await _create_alert(
                sender=sender,
                recipient=recipient,
                chain_id=chain_id,
                tx_hash=tx_hash,
                amount_eur=amount_eur,
                token_symbol=token_symbol,
                alert_type=AlertType(alert_type_str),
                risk_level=RiskLevel(risk),
                details=details,
                requires_kyc=requires_kyc,
            )

    return AMLCheckResult(
        approved=True,
        risk_level=risk,
        alerts=alerts,
        details=(
            f"Daily: €{daily_total:.0f}, Monthly: €{monthly_total:.0f}, "
            f"Velocity: {velocity}/h"
        ),
        requires_kyc=requires_kyc,
        requires_manual_review=requires_review,
    )


async def _create_alert(
    *,
    sender: str,
    recipient: str,
    chain_id: int,
    tx_hash: Optional[str],
    amount_eur: float,
    token_symbol: str,
    alert_type: AlertType,
    risk_level: RiskLevel,
    details: str,
    requires_kyc: bool,
) -> Optional[int]:
    """Create an AML alert record in the database."""
    try:
        async with async_session() as db:
            alert = AMLAlert(
                sender=sender.lower(),
                recipient=recipient.lower(),
                chain_id=chain_id,
                tx_hash=tx_hash,
                amount_eur=amount_eur,
                token_symbol=token_symbol,
                alert_type=alert_type,
                risk_level=risk_level,
                details=details,
                requires_kyc=requires_kyc,
                status=AlertStatus.pending,
            )
            db.add(alert)
            await db.commit()
            await db.refresh(alert)
            logger.info(
                "AML alert #%d: %s (%s) sender=%s amount=€%.0f",
                alert.id, alert_type.value, risk_level.value,
                sender[:10], amount_eur,
                extra={"service": "aml"},
            )
            return alert.id
    except Exception as e:
        logger.error("Failed to create AML alert: %s", e, extra={"service": "aml"})
        return None


# ═══════════════════════════════════════════════════════════════
#  3. FULL CHECK (screening + monitoring combined)
# ═══════════════════════════════════════════════════════════════

async def full_aml_check(
    sender: str,
    recipient: str,
    amount_eur: float,
    *,
    chain_id: int = 0,
    tx_hash: Optional[str] = None,
    token_symbol: str = "ETH",
) -> AMLCheckResult:
    """Complete AML check: address screening + transaction monitoring.

    Called by the oracle signing endpoint.
    If address screening blocks → transaction is REJECTED.
    If monitoring flags → transaction proceeds with alerts for review.
    """
    # Phase 1: Address screening (can block)
    screening = await screen_addresses(sender, recipient)
    if not screening.approved:
        # Create a sanctions_hit alert
        await _create_alert(
            sender=sender,
            recipient=recipient,
            chain_id=chain_id,
            tx_hash=tx_hash,
            amount_eur=amount_eur,
            token_symbol=token_symbol,
            alert_type=AlertType.sanctions_hit,
            risk_level=RiskLevel.blocked,
            details=screening.details,
            requires_kyc=False,
        )
        return screening

    # Phase 2: Transaction monitoring (flags but doesn't block)
    monitoring = await monitor_transaction(
        sender, recipient, amount_eur,
        chain_id=chain_id, tx_hash=tx_hash, token_symbol=token_symbol,
    )

    return monitoring


# ═══════════════════════════════════════════════════════════════
#  BACKWARD-COMPATIBLE API
#  (used by sweep_service.py process_incoming_tx)
# ═══════════════════════════════════════════════════════════════

async def screen_transaction(
    from_addr: str,
    to_addr: str,
    amount_wei: str,
    token: str = "ETH",
) -> dict:
    """Screen a transaction against AML rules.

    Returns dict with backward-compatible keys: passed, flags, blocked.
    """
    results: dict = {"passed": True, "flags": [], "blocked": False}

    # Address screening
    for addr, role in [(from_addr, "Sender"), (to_addr, "Recipient")]:
        blocked, reason = await is_blacklisted(addr)
        if blocked:
            results["passed"] = False
            results["blocked"] = True
            results["flags"].append(f"{role} blacklisted: {reason}")
            logger.warning(
                "AML BLOCK: %s %s is blacklisted: %s",
                role.lower(), addr[:10], reason,
            )

    # Volume check (high-value alert, non-blocking)
    try:
        amount_int = int(amount_wei)
        if amount_int > 10 * 10**18:  # > 10 ETH
            results["flags"].append(
                f"High value transaction: {amount_int / 10**18:.4f} ETH"
            )
    except (ValueError, TypeError):
        pass

    return results


# ═══════════════════════════════════════════════════════════════
#  SANCTIONS LIST MANAGEMENT
# ═══════════════════════════════════════════════════════════════

async def load_sanctions_from_json(data: dict) -> int:
    """Load sanctions entries from JSON (OFAC format).

    Expected format:
    {
        "source": "OFAC_SDN",
        "addresses": [
            {"address": "0x...", "name": "...", "program": "..."},
        ]
    }

    Returns number of entries added.
    """
    source = data.get("source", "unknown")
    entries = data.get("addresses", [])
    added = 0

    async with async_session() as db:
        for entry in entries:
            addr = entry.get("address", "").lower()
            if not addr or len(addr) != 42:
                continue

            # Check if already exists
            existing = await db.execute(
                select(SanctionEntry.id).where(
                    SanctionEntry.address == addr,
                    SanctionEntry.source == source,
                ).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                continue

            db.add(SanctionEntry(
                address=addr,
                name=entry.get("name"),
                program=entry.get("program"),
                source=source,
                source_id=entry.get("id"),
                is_active=True,
            ))
            added += 1

        if added > 0:
            await db.commit()

    logger.info("Loaded %d sanctions entries from %s", added, source)
    return added


async def add_to_blacklist(
    address: str,
    reason: str,
    source: str = "manual",
    added_by: Optional[str] = None,
):
    """Add an address to the blacklist (legacy + new sanctions table)."""
    addr_lower = address.lower()

    # Add to legacy table
    async with async_session() as db:
        entry = BlacklistedWallet(
            address=addr_lower,
            reason=reason,
            source=source,
            added_by=added_by,
        )
        db.add(entry)

        # Also add to sanctions_list for consistency
        db.add(SanctionEntry(
            address=addr_lower,
            name=reason,
            source=source,
            is_active=True,
        ))
        await db.commit()

    logger.warning("AML: Address %s added to blacklist: %s", address[:10], reason)


async def check_split_plan(
    source_wallet: str,
    recipients: list[str],
    amounts_eur: list[float],
    chain_id: int = 0,
) -> AMLCheckResult:
    """AML check specific to split plans: detects structuring via splitting.

    Red flags:
    - >70% of amounts are just below single threshold (€800–€999)
    - > 5 distinct recipients in a single operation
    - Aggregate total > daily threshold but individual amounts < single threshold
    """
    alerts: list[str] = []
    total = sum(amounts_eur)
    cfg = await _get_thresholds()
    threshold_single = cfg["single"]

    # Anti-structuring: if >70% of amounts are between 80%–99% of single threshold
    near_floor = threshold_single * 0.8
    near_threshold = [a for a in amounts_eur if near_floor <= a < threshold_single]
    if len(amounts_eur) >= 3 and len(near_threshold) > len(amounts_eur) * 0.7:
        alerts.append(AlertType.structuring.value)

    # Many recipients = dispersion risk
    if len(recipients) > 5:
        alerts.append(AlertType.velocity.value)

    # Aggregate exceeds daily threshold while individual amounts are below single
    all_below_single = all(a < threshold_single for a in amounts_eur)
    if all_below_single and total > cfg["daily"]:
        alerts.append(AlertType.threshold_daily.value)

    # Monthly check on aggregate
    monthly_total = await _get_monthly_total_eur(source_wallet) + total
    requires_kyc = monthly_total > cfg["monthly"]
    if requires_kyc:
        alerts.append(AlertType.threshold_monthly.value)

    # Determine risk level
    if AlertType.structuring.value in alerts:
        risk = "high"
    elif alerts:
        risk = "medium"
    else:
        risk = "low"

    requires_review = risk in ("medium", "high")

    # Persist alerts
    if alerts:
        details = (
            f"Split: {len(recipients)} recipients, total €{total:.0f}, "
            f"monthly €{monthly_total:.0f}"
        )
        for alert_type_str in alerts:
            await _create_alert(
                sender=source_wallet,
                recipient="SPLIT_AGGREGATE",
                chain_id=chain_id,
                tx_hash=None,
                amount_eur=total,
                token_symbol="SPLIT",
                alert_type=AlertType(alert_type_str),
                risk_level=RiskLevel(risk),
                details=details,
                requires_kyc=requires_kyc,
            )

    return AMLCheckResult(
        approved=True,  # splits are flagged, not blocked by monitoring
        risk_level=risk,
        alerts=alerts,
        details=f"Split: {len(recipients)} recipients, total €{total:.0f}",
        requires_kyc=requires_kyc,
        requires_manual_review=requires_review,
    )


async def remove_from_blacklist(address: str):
    """Soft-remove an address from the blacklist."""
    from sqlalchemy import update

    addr_lower = address.lower()
    async with async_session() as db:
        await db.execute(
            update(BlacklistedWallet)
            .where(BlacklistedWallet.address == addr_lower)
            .values(is_active=False)
        )
        await db.execute(
            update(SanctionEntry)
            .where(SanctionEntry.address == addr_lower)
            .values(is_active=False)
        )
        await db.commit()
