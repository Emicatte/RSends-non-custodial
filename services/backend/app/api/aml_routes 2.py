"""
RSends Backend — AML Admin & Check Routes.

Admin endpoints (require authentication):
  GET  /admin/aml/alerts          — list alerts (filterable by status)
  POST /admin/aml/alerts/{id}/review — review an alert
  POST /admin/aml/sanctions/update — upload sanctions list (JSON)
  GET  /admin/aml/stats           — 24h statistics

Public check endpoint (called by oracle):
  POST /api/v1/aml/check          — full AML check (screening + monitoring)
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update

from app.api.audit_routes import require_admin  # admin-token (X-Admin-Token) gate
from app.db.session import async_session
from app.models.aml_models import (
    AMLAlert,
    AMLConfig,
    SanctionEntry,
    AlertStatus,
    RiskLevel,
)

logger = logging.getLogger(__name__)

aml_router = APIRouter(tags=["aml"])


# ═══════════════════════════════════════════════════════════════
#  Schemas
# ═══════════════════════════════════════════════════════════════

class AMLCheckRequest(BaseModel):
    sender: str
    recipient: str
    amount_eur: float = Field(..., description="Transaction amount in EUR")
    chain_id: int = 0
    tx_hash: Optional[str] = None
    token_symbol: str = "ETH"


class AMLCheckResponse(BaseModel):
    approved: bool
    risk_level: str
    alerts: list[str]
    details: str
    requires_kyc: bool
    requires_manual_review: bool
    blocked: bool


class ReviewRequest(BaseModel):
    reviewed_by: str
    status: str = Field(
        ..., description="New status: reviewed, escalated, dismissed"
    )
    notes: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
#  POST /api/v1/aml/check — Full AML check (called by oracle)
# ═══════════════════════════════════════════════════════════════

@aml_router.post("/api/v1/aml/check", response_model=AMLCheckResponse)
async def aml_check(body: AMLCheckRequest):
    """Full AML check: address screening + transaction monitoring.

    Called by the Next.js oracle BEFORE signing.
    """
    from app.services.aml_service import full_aml_check

    result = await full_aml_check(
        sender=body.sender,
        recipient=body.recipient,
        amount_eur=body.amount_eur,
        chain_id=body.chain_id,
        tx_hash=body.tx_hash,
        token_symbol=body.token_symbol,
    )

    return AMLCheckResponse(
        approved=result.approved,
        risk_level=result.risk_level,
        alerts=result.alerts,
        details=result.details,
        requires_kyc=result.requires_kyc,
        requires_manual_review=result.requires_manual_review,
        blocked=result.blocked,
    )


# ═══════════════════════════════════════════════════════════════
#  GET /admin/aml/alerts — List alerts
# ═══════════════════════════════════════════════════════════════

@aml_router.get("/admin/aml/alerts")
async def list_alerts(
    status: Optional[str] = Query(None, description="Filter by status: pending, reviewed, escalated, dismissed"),
    sender: Optional[str] = Query(None, description="Filter by sender address"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: str = Depends(require_admin),
):
    """List AML alerts with optional filters."""
    async with async_session() as db:
        q = select(AMLAlert).order_by(AMLAlert.created_at.desc())

        if status:
            try:
                q = q.where(AMLAlert.status == AlertStatus(status))
            except ValueError:
                raise HTTPException(400, f"Invalid status: {status}")

        if sender:
            q = q.where(AMLAlert.sender == sender.lower())

        q = q.offset(offset).limit(limit)
        result = await db.execute(q)
        alerts = result.scalars().all()

        # Count total for pagination
        count_q = select(func.count()).select_from(AMLAlert)
        if status:
            count_q = count_q.where(AMLAlert.status == AlertStatus(status))
        if sender:
            count_q = count_q.where(AMLAlert.sender == sender.lower())
        total = (await db.execute(count_q)).scalar_one()

    return {
        "total": total,
        "alerts": [
            {
                "id": a.id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "sender": a.sender,
                "recipient": a.recipient,
                "chain_id": a.chain_id,
                "amount_eur": a.amount_eur,
                "token_symbol": a.token_symbol,
                "tx_hash": a.tx_hash,
                "alert_type": a.alert_type.value if a.alert_type else None,
                "risk_level": a.risk_level.value if a.risk_level else None,
                "details": a.details,
                "status": a.status.value if a.status else None,
                "reviewed_by": a.reviewed_by,
                "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
                "review_notes": a.review_notes,
                "requires_kyc": a.requires_kyc,
                "sar_filed": a.sar_filed,
            }
            for a in alerts
        ],
    }


# ═══════════════════════════════════════════════════════════════
#  POST /admin/aml/alerts/{id}/review — Review an alert
# ═══════════════════════════════════════════════════════════════

@aml_router.post("/admin/aml/alerts/{alert_id}/review")
async def review_alert(
    alert_id: int, body: ReviewRequest, _admin: str = Depends(require_admin)
):
    """Mark an AML alert as reviewed/escalated/dismissed."""
    try:
        new_status = AlertStatus(body.status)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {body.status}")

    async with async_session() as db:
        result = await db.execute(
            select(AMLAlert).where(AMLAlert.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        if not alert:
            raise HTTPException(404, f"Alert {alert_id} not found")

        alert.status = new_status
        alert.reviewed_by = body.reviewed_by
        alert.reviewed_at = datetime.now(timezone.utc)
        alert.review_notes = body.notes
        await db.commit()

    logger.info(
        "AML alert #%d reviewed: %s by %s",
        alert_id, new_status.value, body.reviewed_by,
    )
    return {"status": "ok", "alert_id": alert_id, "new_status": new_status.value}


# ═══════════════════════════════════════════════════════════════
#  POST /admin/aml/sanctions/update — Upload sanctions list
# ═══════════════════════════════════════════════════════════════

@aml_router.post("/admin/aml/sanctions/update")
async def update_sanctions(
    body: Optional[dict] = None, _admin: str = Depends(require_admin)
):
    """Update sanctions list from JSON payload or built-in OFAC file.

    If no body is provided, loads from data/sanctions/ofac_sdn.json.
    """
    from app.services.aml_service import load_sanctions_from_json

    if body and "addresses" in body:
        data = body
    else:
        # Load built-in OFAC file
        ofac_path = Path(__file__).parent.parent.parent / "data" / "sanctions" / "ofac_sdn.json"
        if not ofac_path.exists():
            raise HTTPException(404, "OFAC sanctions file not found")
        data = json.loads(ofac_path.read_text())

    added = await load_sanctions_from_json(data)

    return {
        "status": "ok",
        "source": data.get("source", "unknown"),
        "entries_added": added,
        "total_in_file": len(data.get("addresses", [])),
    }


# ═══════════════════════════════════════════════════════════════
#  GET /admin/aml/stats — 24h statistics
# ═══════════════════════════════════════════════════════════════

@aml_router.get("/admin/aml/stats")
async def aml_stats(_admin: str = Depends(require_admin)):
    """AML statistics for the last 24 hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    async with async_session() as db:
        # Total alerts 24h
        total_24h = (await db.execute(
            select(func.count()).select_from(AMLAlert).where(
                AMLAlert.created_at >= since,
            )
        )).scalar_one()

        # Pending alerts
        pending = (await db.execute(
            select(func.count()).select_from(AMLAlert).where(
                AMLAlert.status == AlertStatus.pending,
            )
        )).scalar_one()

        # Blocked transactions 24h
        blocked_24h = (await db.execute(
            select(func.count()).select_from(AMLAlert).where(
                AMLAlert.created_at >= since,
                AMLAlert.risk_level == RiskLevel.blocked,
            )
        )).scalar_one()

        # Alerts by type 24h
        type_counts = (await db.execute(
            select(AMLAlert.alert_type, func.count()).where(
                AMLAlert.created_at >= since,
            ).group_by(AMLAlert.alert_type)
        )).all()

        # Top wallets by alert count 24h
        top_wallets = (await db.execute(
            select(
                AMLAlert.sender,
                func.count().label("alert_count"),
                func.sum(AMLAlert.amount_eur).label("total_eur"),
            ).where(
                AMLAlert.created_at >= since,
            ).group_by(AMLAlert.sender)
            .order_by(func.count().desc())
            .limit(10)
        )).all()

        # Active sanctions count
        sanctions_count = (await db.execute(
            select(func.count()).select_from(SanctionEntry).where(
                SanctionEntry.is_active == True,  # noqa: E712
            )
        )).scalar_one()

    return {
        "period": "24h",
        "total_alerts": total_24h,
        "pending_alerts": pending,
        "blocked_transactions": blocked_24h,
        "active_sanctions": sanctions_count,
        "alerts_by_type": {
            row[0].value if row[0] else "unknown": row[1]
            for row in type_counts
        },
        "top_wallets": [
            {
                "sender": row[0],
                "alert_count": row[1],
                "total_eur": round(row[2] or 0, 2),
            }
            for row in top_wallets
        ],
    }
