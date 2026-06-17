"""
RSends Backend — Audit Log API Routes.

GET /api/v1/audit/log — Cursor-based paginated audit log.
Accesso riservato ad admin (header X-Admin-Token).
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.models.ledger_models import LedgerAuditLog

audit_router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


# ── Response schemas ─────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: int
    event_type: str
    entity_type: str
    entity_id: str
    actor_type: Optional[str] = None
    actor_id: Optional[str] = None
    ip_address: Optional[str] = None
    changes: Optional[dict] = None
    request_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    next_cursor: Optional[int] = None
    has_more: bool


# ── Admin auth dependency ────────────────────────────────────

async def require_admin(
    x_admin_token: str = Header(..., description="Token admin per accesso audit log"),
) -> str:
    """Verifica il token admin. In produzione usa un sistema di auth più robusto."""
    settings = get_settings()
    expected = settings.hmac_secret  # riusa il secret HMAC come admin token
    if x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden: invalid admin token")
    return x_admin_token


# ── GET /api/v1/audit/log ────────────────────────────────────

@audit_router.get("/log", response_model=AuditLogPage)
async def get_audit_log(
    cursor: Optional[int] = Query(None, description="ID dell'ultimo record visto (cursor)"),
    limit: int = Query(50, ge=1, le=200, description="Numero massimo di record"),
    event_type: Optional[str] = Query(None, description="Filtra per event_type"),
    entity_type: Optional[str] = Query(None, description="Filtra per entity_type"),
    date_from: Optional[datetime] = Query(None, description="Data inizio (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Data fine (ISO 8601)"),
    db: AsyncSession = Depends(get_db),
    _admin: str = Depends(require_admin),
) -> AuditLogPage:
    """
    Restituisce i record di audit log con paginazione cursor-based.

    Il cursor è l'ID (BIGSERIAL) dell'ultimo record visto.
    Restituisce i record successivi in ordine crescente di ID.
    """
    query = select(LedgerAuditLog).order_by(LedgerAuditLog.id.asc())

    # Cursor-based: prendi i record dopo il cursor
    if cursor is not None:
        query = query.where(LedgerAuditLog.id > cursor)

    # Filtri opzionali
    if event_type:
        query = query.where(LedgerAuditLog.event_type == event_type)
    if entity_type:
        query = query.where(LedgerAuditLog.entity_type == entity_type)
    if date_from:
        query = query.where(LedgerAuditLog.created_at >= date_from)
    if date_to:
        query = query.where(LedgerAuditLog.created_at <= date_to)

    # Fetch limit + 1 per sapere se ci sono altri record
    query = query.limit(limit + 1)
    result = await db.execute(query)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]

    next_cursor = items[-1].id if items and has_more else None

    return AuditLogPage(
        items=[
            AuditLogEntry(
                id=row.id,
                event_type=row.event_type,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                actor_type=row.actor_type,
                actor_id=row.actor_id,
                ip_address=row.ip_address,
                changes=row.changes,
                request_id=str(row.request_id) if row.request_id else None,
                created_at=row.created_at,
            )
            for row in items
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


# ═══════════════════════════════════════════════════════════════
#  Kill Switch Admin Endpoints (Wave 8.4)
# ═══════════════════════════════════════════════════════════════


class KillSwitchToggle(BaseModel):
    active: bool


@audit_router.get("/kill-switch/status")
async def kill_switch_status(_admin: str = Depends(require_admin)):
    from app.services.kill_switch import get_status

    return await get_status()


@audit_router.post("/kill-switch/global")
async def toggle_global_kill_switch(
    body: KillSwitchToggle,
    _admin: str = Depends(require_admin),
):
    from app.services.kill_switch import set_global_stop

    await set_global_stop(body.active)
    return {"global_stopped": body.active}


@audit_router.post("/kill-switch/client/{client_id}")
async def toggle_client_kill_switch(
    client_id: str,
    body: KillSwitchToggle,
    _admin: str = Depends(require_admin),
):
    from app.services.kill_switch import set_client_stop

    await set_client_stop(client_id, body.active)
    return {"client_id": client_id, "stopped": body.active}


@audit_router.post("/kill-switch/clear-auto-stop")
async def clear_auto_stop_endpoint(_admin: str = Depends(require_admin)):
    from app.services.kill_switch import clear_auto_stop

    await clear_auto_stop()
    return {"auto_stop": None}
