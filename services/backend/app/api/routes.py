"""
RPagos Backend Core — API Routes v1.

Endpoint principali:
  POST /api/v1/tx/callback     → Riceve i dati dal frontend
  GET  /api/v1/tx/{fiscal_ref} → Recupera una transazione
  GET  /api/v1/anomalies       → Lancia l'analizzatore di anomalie
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.db_models import TransactionLog, ComplianceSnapshot, TxStatus
from app.models.schemas import (
    TransactionCallbackPayload,
    CallbackResponse,
    AnomalyReportResponse,
)
from app.services.hmac_service import verify_signature
from app.services.anomaly_service import analyze_transactions
from app.services.audit_service import log_event

import logging

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["transactions"])


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/tx/callback
#  Riceve esattamente il payload che TransactionStatus.tsx genera
# ═══════════════════════════════════════════════════════════════

@router.post("/tx/callback", response_model=CallbackResponse)
async def receive_transaction(
    payload: TransactionCallbackPayload,
    db: AsyncSession = Depends(get_db),
) -> CallbackResponse:
    """
    Callback endpoint per ricevere le transazioni dal frontend.

    Workflow:
      1. Valida la firma HMAC (x_signature)
      2. Controlla duplicati (tx_hash e fiscal_ref)
      3. Salva la transazione su DB
      4. Se presente, salva il compliance record
      5. Restituisce conferma
    """

    # ── 1. Validazione HMAC ──────────────────────────────────
    sig_valid = verify_signature(
        x_signature=payload.x_signature,
        fiscal_ref=payload.fiscal_ref,
        tx_hash=payload.tx_hash,
        amount=str(payload.gross_amount),
        currency=payload.currency,
        timestamp=payload.timestamp.isoformat(),
    )
    if not sig_valid:
        await log_event(
            db,
            "AUTH_FAILURE",
            "transaction_callback",
            payload.tx_hash,
            actor_type="external",
            changes={"fiscal_ref": payload.fiscal_ref, "reason": "INVALID_SIGNATURE"},
        )
        raise HTTPException(
            status_code=401,
            detail={
                "error": "INVALID_SIGNATURE",
                "message": "La firma x_signature non corrisponde al payload. "
                           "Verifica che il secret HMAC sia corretto.",
            },
        )

    # ── 2. Check duplicati ───────────────────────────────────
    existing = await db.execute(
        select(TransactionLog).where(TransactionLog.tx_hash == payload.tx_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DUPLICATE_TX",
                "message": f"Transazione con tx_hash {payload.tx_hash} già registrata.",
            },
        )

    # ── 3. Salvataggio TransactionLog ────────────────────────
    tx = TransactionLog(
        fiscal_ref=payload.fiscal_ref,
        payment_ref=payload.payment_ref,
        tx_hash=payload.tx_hash,
        gross_amount=payload.gross_amount,
        net_amount=payload.net_amount,
        fee_amount=payload.fee_amount,
        currency=payload.currency,
        eur_value=payload.eur_value,
        network=payload.network,
        status=TxStatus(payload.status),
        recipient=payload.recipient,
        x_signature=payload.x_signature,
        signature_valid=sig_valid,
        tx_timestamp=payload.timestamp,
    )
    db.add(tx)
    await db.flush()  # Otteniamo l'ID senza committare

    # ── 3b. Audit trail ─────────────────────────────────────
    await log_event(
        db,
        "TX_CREATED",
        "transaction_log",
        str(tx.id),
        actor_type="external",
        changes={
            "tx_hash": payload.tx_hash,
            "gross_amount": str(payload.gross_amount),
            "fee_amount": str(payload.fee_amount),
            "currency": payload.currency,
            "network": payload.network,
        },
    )

    # ── 4. Salvataggio ComplianceSnapshot (se presente) ──────
    compliance_logged = False

    if payload.compliance_record:
        cr = payload.compliance_record
        snapshot = ComplianceSnapshot(
            transaction_id=tx.id,
            compliance_id=cr.compliance_id,
            block_timestamp=cr.block_timestamp,
            fiat_rate=cr.fiat_rate,
            asset=cr.asset,
            fiat_gross=cr.fiat_gross,
            ip_jurisdiction=cr.ip_jurisdiction,
            mica_applicable=cr.mica_applicable,
            network=cr.network,
            fiscal_ref=cr.fiscal_ref,
        )
        db.add(snapshot)
        compliance_logged = True

    # ── 5. Commit TX to DB ────────────────────────────────────
    await db.commit()

    # NON-CUSTODIAL: deposit-address transaction matching has been removed.
    # Payment matching now happens on-chain in payment_indexer, which watches
    # RSendsRouter.PaymentMade events and marks the matching PaymentIntent paid.
    # This legacy /tx/callback endpoint is kept only for compliance logging of
    # externally-reported transactions.

    return CallbackResponse(
        status="success",
        message=f"TX {payload.tx_hash[:16]}… loggata per compliance",
        transaction_id=tx.id,
        compliance_logged=compliance_logged,
    )


# ═══════════════════════════════════════════════════════════════
#  GET /api/v1/tx/recent — Ultime TX per wallet
#  MUST be registered BEFORE /tx/{fiscal_ref} so FastAPI matches
#  the literal "/tx/recent" before the path parameter "{fiscal_ref}"
# ═══════════════════════════════════════════════════════════════

@router.get("/tx/recent")
async def get_recent_transactions(
    wallet: Optional[str] = Query(None, description="Indirizzo wallet"),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Recupera le ultime N transazioni, opzionalmente filtrate per wallet."""
    query = select(TransactionLog).order_by(TransactionLog.tx_timestamp.desc())
    if wallet:
        wallet_lower = wallet.lower()
        query = query.where(TransactionLog.recipient == wallet_lower)
    query = query.limit(limit)
    result = await db.execute(query)
    txs = result.scalars().all()

    return {
        "records": [
            {
                "tx_hash": tx.tx_hash,
                "gross_amount": tx.gross_amount,
                "net_amount": tx.net_amount,
                "fee_amount": tx.fee_amount,
                "currency": tx.currency,
                "eur_value": tx.eur_value,
                "status": tx.status.value,
                "network": tx.network,
                "recipient": tx.recipient,
                "tx_timestamp": tx.tx_timestamp.isoformat() if tx.tx_timestamp else None,
            }
            for tx in txs
        ]
    }


# ═══════════════════════════════════════════════════════════════
#  GET /api/v1/tx/{fiscal_ref}
# ═══════════════════════════════════════════════════════════════

@router.get("/tx/{fiscal_ref}")
async def get_transaction(
    fiscal_ref: str,
    db: AsyncSession = Depends(get_db),
):
    """Recupera una transazione per fiscal_ref."""
    result = await db.execute(
        select(TransactionLog).where(TransactionLog.fiscal_ref == fiscal_ref)
    )
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transazione non trovata")

    return {
        "fiscal_ref": tx.fiscal_ref,
        "tx_hash": tx.tx_hash,
        "gross_amount": tx.gross_amount,
        "net_amount": tx.net_amount,
        "fee_amount": tx.fee_amount,
        "currency": tx.currency,
        "eur_value": tx.eur_value,
        "network": tx.network,
        "status": tx.status.value,
        "recipient": tx.recipient,
        "signature_valid": tx.signature_valid,
        "tx_timestamp": tx.tx_timestamp.isoformat(),
        "received_at": tx.received_at.isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
#  GET /api/v1/anomalies
# ═══════════════════════════════════════════════════════════════

@router.get("/anomalies", response_model=AnomalyReportResponse)
async def run_anomaly_analysis(
    window_hours: int = Query(default=24, ge=1, le=720, description="Finestra in ore"),
    currency: Optional[str] = Query(default=None, description="Filtra per valuta"),
    db: AsyncSession = Depends(get_db),
) -> AnomalyReportResponse:
    """
    Lancia l'analizzatore di anomalie sulle transazioni recenti.

    Come un radioastronomo che cerca segnali nel rumore cosmico,
    questo endpoint analizza i pattern di transazione per trovare:
    - Picchi di volume (volume_spike)
    - Importi anomali (amount_outlier)
    - Burst di frequenza (frequency_burst)
    """
    report = await analyze_transactions(db, window_hours, currency)
    if report.anomalies_found > 0:
        await log_event(
            db,
            "ANOMALY_DETECTED",
            "anomaly_report",
            f"window_{window_hours}h",
            actor_type="system",
            changes={
                "anomalies_found": report.anomalies_found,
                "total_transactions": report.total_transactions,
                "window_hours": window_hours,
            },
        )
    return report