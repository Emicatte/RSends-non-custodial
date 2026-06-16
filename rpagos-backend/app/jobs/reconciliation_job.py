"""
RSends Backend — Reconciliation Job.

Job periodico (ogni ora) che esegue tutte le verifiche di riconciliazione:
  1. check_ledger_balance — per-transaction DEBIT == CREDIT
  2. check_system_balance — somma globale bilanciata
  3. check_stale_transactions — transazioni bloccate in PROCESSING
  4. reconcile_onchain — saldo ledger vs on-chain (opzionale, solo con API key)

Risultati loggati nell'audit trail e esposti via /health/deep.
Usa asyncio.Task schedulato dal lifespan di FastAPI (nessuna dipendenza esterna).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.config import get_settings
from app.db.session import async_session
from app.services.alert_service import fire_alert, AlertType
from app.services.reconciliation_service import (
    FullReconciliationReport,
    ONCHAIN_DISCREPANCY_THRESHOLD_WEI,
    RULE_DISCREPANCY_THRESHOLD_ETH,
    STALE_THRESHOLD_MINUTES,
    check_ledger_balance,
    check_stale_transactions,
    check_system_balance,
    reconcile_onchain,
    reconcile_and_enforce,
    save_daily_snapshot,
)

logger = logging.getLogger(__name__)

# Intervallo di default: 1 ora (3600 secondi)
RECONCILIATION_INTERVAL_SECONDS = 3600

# Ultimo report di riconciliazione (accessibile da /health/deep)
_last_report: Optional[FullReconciliationReport] = None
_job_task: Optional[asyncio.Task] = None


def get_last_report() -> Optional[FullReconciliationReport]:
    """Restituisce l'ultimo report di riconciliazione."""
    return _last_report


def _format_onchain_discrepancies(items: list[dict]) -> str:
    lines = []
    for d in items:
        lines.append(
            f"• {d['chain_id']}:{d['address'][:10]}… "
            f"ledger={d['ledger_balance']} onchain={d['onchain_balance_eth']} "
            f"Δ={d['discrepancy']}"
        )
    return "\n".join(lines)


async def run_reconciliation() -> FullReconciliationReport:
    """Esegue tutte le verifiche di riconciliazione in una singola sessione.

    Returns:
        FullReconciliationReport con tutti i risultati.
    """
    global _last_report

    # Import lazy per evitare import circolari con Prometheus
    try:
        from app.jobs.reconciliation_metrics import (
            RECONCILIATION_DURATION,
            LEDGER_DISCREPANCIES,
            STALE_TRANSACTIONS_GAUGE,
            ONCHAIN_DISCREPANCY,
        )
        has_metrics = True
    except ImportError:
        has_metrics = False

    start_time = time.monotonic()
    report = FullReconciliationReport()
    report.last_reconciliation = datetime.now(timezone.utc)

    async with async_session() as session:
        try:
            # 1. Ledger balance check (per-transaction)
            discrepancies = await check_ledger_balance(session)
            report.discrepancies = discrepancies
            report.ledger_balanced = len(discrepancies) == 0

            if has_metrics and discrepancies:
                LEDGER_DISCREPANCIES.inc(len(discrepancies))

            if discrepancies:
                sample_ids = [str(d.transaction_id) for d in discrepancies[:5]]
                max_diff = max((abs(d.difference) for d in discrepancies), default=Decimal(0))
                ledger_critical = (
                    len(discrepancies) >= 5 or max_diff >= RULE_DISCREPANCY_THRESHOLD_ETH
                )
                await fire_alert(
                    AlertType.LEDGER_DISCREPANCY_CRITICAL if ledger_critical
                    else AlertType.LEDGER_DISCREPANCY,
                    f"Ledger discrepancy: {len(discrepancies)} unbalanced transaction(s); "
                    f"max difference {max_diff}",
                    {
                        "discrepancy_count": len(discrepancies),
                        "max_difference": str(max_diff),
                        "sample_transaction_ids": sample_ids,
                        "threshold_eth": str(RULE_DISCREPANCY_THRESHOLD_ETH),
                    },
                )

            # 2. System balance check (global)
            system_report = await check_system_balance(session)
            report.system_balance = system_report
            report.system_balanced = system_report.balanced

            if not system_report.balanced:
                await fire_alert(
                    AlertType.SYSTEM_IMBALANCE,
                    f"SYSTEM IMBALANCE: debits={system_report.total_debits} "
                    f"credits={system_report.total_credits} diff={system_report.difference}",
                    {
                        "total_debits": str(system_report.total_debits),
                        "total_credits": str(system_report.total_credits),
                        "difference": str(system_report.difference),
                    },
                )

            # 3. Stale transactions check
            stale = await check_stale_transactions(session)
            report.stale_transactions = len(stale)
            report.stale_txs = [
                {"id": str(t.id), "updated_at": t.updated_at.isoformat() if t.updated_at else None}
                for t in stale
            ]

            if has_metrics:
                STALE_TRANSACTIONS_GAUGE.set(len(stale))

            if stale:
                await fire_alert(
                    AlertType.STALE_TRANSACTIONS,
                    f"{len(stale)} transaction(s) stale in PROCESSING "
                    f"(> {STALE_THRESHOLD_MINUTES} min)",
                    {
                        "stale_count": len(stale),
                        "threshold_minutes": STALE_THRESHOLD_MINUTES,
                        "sample_transaction_ids": [str(t.id) for t in stale[:5]],
                    },
                )

            # 4. On-chain reconciliation (opzionale)
            settings = get_settings()
            if settings.alchemy_api_key:
                try:
                    from sqlalchemy import select
                    from app.models.ledger_models import Account

                    stmt = select(Account).where(
                        Account.is_active == True,  # noqa: E712
                        Account.address.isnot(None),
                    )
                    result = await session.execute(stmt)
                    accounts = result.scalars().all()

                    onchain_discrepancies: list[dict] = []

                    for account in accounts:
                        try:
                            recon = await reconcile_onchain(
                                session,
                                account.id,
                                chain_id=8453,  # Base mainnet default
                                currency=account.currency,
                            )
                            report.onchain_results.append(recon)
                            if has_metrics and not recon.within_threshold:
                                ONCHAIN_DISCREPANCY.inc()
                            if not recon.within_threshold:
                                onchain_discrepancies.append({
                                    "account_id": str(recon.account_id),
                                    "chain_id": recon.chain_id,
                                    "address": recon.address,
                                    "ledger_balance": recon.ledger_balance,
                                    "onchain_balance_eth": recon.onchain_balance_eth,
                                    "discrepancy": recon.discrepancy,
                                    "critical": (
                                        abs(recon.discrepancy) >= RULE_DISCREPANCY_THRESHOLD_ETH
                                    ),
                                })
                        except Exception as e:
                            logger.warning(
                                "On-chain reconciliation failed for account %s: %s",
                                account.id, e,
                            )

                    # Aggregated alert: one outbound notification for all
                    # discrepant accounts instead of one per account (avoids
                    # rate-limit bans and blocking I/O inside the loop).
                    if onchain_discrepancies:
                        any_critical = any(d["critical"] for d in onchain_discrepancies)
                        await fire_alert(
                            AlertType.ONCHAIN_DISCREPANCY_CRITICAL if any_critical
                            else AlertType.ONCHAIN_DISCREPANCY,
                            f"On-chain balance mismatch — "
                            f"{len(onchain_discrepancies)} account(s)\n"
                            f"{_format_onchain_discrepancies(onchain_discrepancies)}",
                            {
                                "discrepancy_count": len(onchain_discrepancies),
                                "critical": any_critical,
                                "threshold_wei": ONCHAIN_DISCREPANCY_THRESHOLD_WEI,
                                "accounts": [
                                    {
                                        "account_id": d["account_id"],
                                        "chain_id": d["chain_id"],
                                        "address": d["address"],
                                        "ledger_balance": str(d["ledger_balance"]),
                                        "onchain_balance_eth": str(d["onchain_balance_eth"]),
                                        "discrepancy": str(d["discrepancy"]),
                                    }
                                    for d in onchain_discrepancies[:5]
                                ],
                            },
                        )
                except Exception as e:
                    logger.warning("On-chain reconciliation skipped: %s", e)

            # 5. Treasury reconciliation with circuit breaker enforcement
            try:
                enforce_results = await reconcile_and_enforce(session)
                if enforce_results:
                    alert_count = sum(1 for r in enforce_results if r.get("alert"))
                    if alert_count:
                        logger.warning(
                            "Treasury reconciliation: %d/%d chains with mismatch",
                            alert_count, len(enforce_results),
                        )
                        mismatched = [r for r in enforce_results if r.get("alert")]
                        await fire_alert(
                            AlertType.TREASURY_MISMATCH,
                            f"Treasury reconciliation: {alert_count}/{len(enforce_results)} "
                            f"chain(s) with mismatch",
                            {
                                "mismatch_count": alert_count,
                                "chains": [
                                    {
                                        "chain_id": r["chain_id"],
                                        "treasury_address": r["treasury_address"],
                                        "on_chain_balance": str(r["on_chain_balance"]),
                                        "ledger_balance": str(r["ledger_balance"]),
                                        "diff": str(r["diff"]),
                                        "diff_pct": str(r["diff_pct"]),
                                    }
                                    for r in mismatched[:5]
                                ],
                            },
                        )
            except Exception as e:
                logger.error("Treasury reconcile_and_enforce failed: %s", e)

            # 6. Daily snapshot (once per day, idempotent)
            try:
                await save_daily_snapshot(session)
            except Exception as e:
                logger.error("Daily snapshot failed: %s", e)

            await session.commit()

        except Exception as e:
            logger.error("Reconciliation job failed: %s", e, exc_info=True)
            await session.rollback()
            raise

    duration = time.monotonic() - start_time
    if has_metrics:
        RECONCILIATION_DURATION.observe(duration)

    _last_report = report

    logger.info(
        "Reconciliation completed in %.2fs: ledger_balanced=%s system_balanced=%s stale=%d",
        duration,
        report.ledger_balanced,
        report.system_balanced,
        report.stale_transactions,
        extra={
            "duration_seconds": round(duration, 3),
            "ledger_balanced": report.ledger_balanced,
            "system_balanced": report.system_balanced,
            "stale_transactions": report.stale_transactions,
            "discrepancies_found": len(report.discrepancies),
        },
    )

    return report


async def _reconciliation_loop() -> None:
    """Loop infinito che esegue la riconciliazione ogni RECONCILIATION_INTERVAL_SECONDS."""
    # Attendi 60s al boot prima della prima esecuzione
    await asyncio.sleep(60)

    while True:
        try:
            await run_reconciliation()
        except Exception as e:
            logger.error("Reconciliation loop error: %s", e, exc_info=True)

        await asyncio.sleep(RECONCILIATION_INTERVAL_SECONDS)


def start_reconciliation_job() -> asyncio.Task:
    """Avvia il job di riconciliazione come task asyncio in background.

    Chiamato dal lifespan di FastAPI.
    """
    global _job_task
    _job_task = asyncio.create_task(_reconciliation_loop(), name="reconciliation_job")
    logger.info("Reconciliation job scheduled (interval=%ds)", RECONCILIATION_INTERVAL_SECONDS)
    return _job_task


async def stop_reconciliation_job() -> None:
    """Ferma il job di riconciliazione."""
    global _job_task
    if _job_task and not _job_task.done():
        _job_task.cancel()
        try:
            await _job_task
        except asyncio.CancelledError:
            pass
        _job_task = None
        logger.info("Reconciliation job stopped")
