"""
RSends Backend — Distribution List API Routes (CC-07)

POST   /api/v1/distributions                    → Create distribution list
GET    /api/v1/distributions                    → List user's distribution lists
GET    /api/v1/distributions/{id}               → Detail with recipients
PUT    /api/v1/distributions/{id}               → Update (audit log, warn if active rule)
DELETE /api/v1/distributions/{id}               → Soft delete (409 if active rules)
POST   /api/v1/distributions/{id}/import-csv    → Parse and validate CSV
GET    /api/v1/distributions/{id}/export-csv    → Export CSV
"""

import csv
import io
import logging
import re
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.request_context import get_request_id
from app.models.command_models import DistributionList, DistributionRecipient
from app.models.forwarding_models import AuditLog, ForwardingRule
from app.security.auth import require_wallet_auth

logger = logging.getLogger("distribution_routes")

distribution_router = APIRouter(prefix="/api/v1", tags=["distributions"])

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_RECIPIENTS = 500


# ═══════════════════════════════════════════════════════════
#  Pydantic schemas
# ═══════════════════════════════════════════════════════════

def _validate_eth_address(v: str) -> str:
    if not ETH_ADDR_RE.match(v):
        raise ValueError("Must be a valid Ethereum address (0x + 40 hex chars)")
    return v.lower()


class RecipientSchema(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)
    percent_bps: int = Field(..., ge=1, le=10000)
    label: Optional[str] = Field(None, max_length=100)

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        return _validate_eth_address(v)


class CreateDistributionPayload(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    chain_id: int = Field(8453)
    recipients: list[RecipientSchema] = Field(..., min_length=1)

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[RecipientSchema]) -> list[RecipientSchema]:
        if len(v) > MAX_RECIPIENTS:
            raise ValueError(f"Maximum {MAX_RECIPIENTS} recipients per list")

        addresses = [r.address.lower() for r in v]
        if len(addresses) != len(set(addresses)):
            raise ValueError("Duplicate recipient addresses are not allowed")

        total_bps = sum(r.percent_bps for r in v)
        if total_bps != 10000:
            raise ValueError(
                f"Recipient percentages must sum to 10000 bps (100%), got {total_bps}"
            )

        return v


class UpdateDistributionPayload(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    recipients: Optional[list[RecipientSchema]] = None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(
        cls, v: Optional[list[RecipientSchema]],
    ) -> Optional[list[RecipientSchema]]:
        if v is None:
            return v

        if len(v) == 0:
            raise ValueError("Recipients list cannot be empty")

        if len(v) > MAX_RECIPIENTS:
            raise ValueError(f"Maximum {MAX_RECIPIENTS} recipients per list")

        addresses = [r.address.lower() for r in v]
        if len(addresses) != len(set(addresses)):
            raise ValueError("Duplicate recipient addresses are not allowed")

        total_bps = sum(r.percent_bps for r in v)
        if total_bps != 10000:
            raise ValueError(
                f"Recipient percentages must sum to 10000 bps (100%), got {total_bps}"
            )

        return v


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

def _serialize_recipient(r: DistributionRecipient) -> dict:
    return {
        "id": str(r.id),
        "address": r.address,
        "percent_bps": r.percent_bps,
        "label": r.label,
        "is_active": r.is_active,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _serialize_distribution(dl: DistributionList, include_recipients: bool = True) -> dict:
    data = {
        "id": str(dl.id),
        "owner_address": dl.owner_address,
        "label": dl.label,
        "is_active": dl.is_active,
        "chain_id": dl.chain_id,
        "created_at": dl.created_at.isoformat() if dl.created_at else None,
        "updated_at": dl.updated_at.isoformat() if dl.updated_at else None,
    }
    if include_recipients:
        data["recipients"] = [
            _serialize_recipient(r) for r in (dl.recipients or [])
            if r.is_active
        ]
        data["recipient_count"] = len(data["recipients"])
    return data


async def _get_distribution_or_404(
    db: AsyncSession, dist_id: uuid.UUID,
) -> DistributionList:
    result = await db.execute(
        select(DistributionList).where(DistributionList.id == dist_id)
    )
    dl = result.scalar_one_or_none()
    if not dl:
        raise HTTPException(status_code=404, detail="Distribution list not found")
    return dl


async def _verify_dist_owner(dl: DistributionList, wallet_address: str) -> None:
    if dl.owner_address != wallet_address.lower():
        raise HTTPException(
            status_code=403, detail="Not the owner of this distribution list"
        )


async def _count_active_rules_using(db: AsyncSession, dist_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(ForwardingRule).where(
            ForwardingRule.distribution_list_id == dist_id,
            ForwardingRule.is_active == True,  # noqa: E712
        )
    )
    return result.scalar() or 0


def _response(data: dict) -> dict:
    """Inject request_id into response."""
    rid = get_request_id()
    if rid:
        data["request_id"] = str(rid)
    return data


# ═══════════════════════════════════════════════════════════
#  1. POST /distributions — Create distribution list
# ═══════════════════════════════════════════════════════════

@distribution_router.post("/distributions")
@require_wallet_auth
async def create_distribution(
    request: Request,
    payload: CreateDistributionPayload,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    owner = wallet_address.lower()

    dl = DistributionList(
        owner_address=owner,
        label=payload.label,
        chain_id=payload.chain_id,
    )
    db.add(dl)
    await db.flush()

    for r in payload.recipients:
        recipient = DistributionRecipient(
            list_id=dl.id,
            address=r.address,
            percent_bps=r.percent_bps,
            label=r.label,
        )
        db.add(recipient)

    await db.commit()
    await db.refresh(dl)

    logger.info(
        "[dist] Created list %s with %d recipients (owner=%s)",
        dl.id, len(payload.recipients), owner[:10],
    )

    return _response({
        "status": "created",
        "distribution": _serialize_distribution(dl),
    })


# ═══════════════════════════════════════════════════════════
#  2. GET /distributions — List user's distribution lists
# ═══════════════════════════════════════════════════════════

@distribution_router.get("/distributions")
@require_wallet_auth
async def list_distributions(
    request: Request,
    chain_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    owner = wallet_address.lower()
    q = select(DistributionList).where(
        DistributionList.owner_address == owner,
        DistributionList.is_active == True,  # noqa: E712
    )
    if chain_id is not None:
        q = q.where(DistributionList.chain_id == chain_id)

    q = q.order_by(DistributionList.created_at.desc())
    result = await db.execute(q)
    lists = result.scalars().all()

    items = []
    for dl in lists:
        item = _serialize_distribution(dl, include_recipients=False)
        item["recipient_count"] = len([
            r for r in (dl.recipients or []) if r.is_active
        ])
        # Count rules using this list
        item["active_rules_count"] = await _count_active_rules_using(db, dl.id)
        items.append(item)

    return _response({"distributions": items, "total": len(items)})


# ═══════════════════════════════════════════════════════════
#  3. GET /distributions/{id} — Detail with recipients
# ═══════════════════════════════════════════════════════════

@distribution_router.get("/distributions/{dist_id}")
async def get_distribution(
    dist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    dl = await _get_distribution_or_404(db, dist_id)
    data = _serialize_distribution(dl)

    # Include rules that use this list
    result = await db.execute(
        select(ForwardingRule).where(
            ForwardingRule.distribution_list_id == dist_id,
            ForwardingRule.is_active == True,  # noqa: E712
        )
    )
    rules = result.scalars().all()
    data["used_by_rules"] = [
        {"id": r.id, "label": r.label, "source_wallet": r.source_wallet, "is_paused": r.is_paused}
        for r in rules
    ]

    return _response({"distribution": data})


# ═══════════════════════════════════════════════════════════
#  4. PUT /distributions/{id} — Update
# ═══════════════════════════════════════════════════════════

@distribution_router.put("/distributions/{dist_id}")
@require_wallet_auth
async def update_distribution(
    request: Request,
    dist_id: uuid.UUID,
    payload: UpdateDistributionPayload,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    dl = await _get_distribution_or_404(db, dist_id)
    await _verify_dist_owner(dl, wallet_address)

    old_label = dl.label
    warnings = []

    # Check if used by active rules
    active_rule_count = await _count_active_rules_using(db, dist_id)
    if active_rule_count > 0:
        warnings.append(
            f"This distribution list is used by {active_rule_count} active rule(s). "
            "Changes will affect future sweeps."
        )

    # Update label
    if payload.label is not None:
        dl.label = payload.label

    # Replace recipients
    if payload.recipients is not None:
        # Deactivate old recipients
        for r in dl.recipients:
            r.is_active = False

        # Add new recipients
        for r_schema in payload.recipients:
            new_r = DistributionRecipient(
                list_id=dl.id,
                address=r_schema.address,
                percent_bps=r_schema.percent_bps,
                label=r_schema.label,
            )
            db.add(new_r)

    await db.flush()

    # Audit log (use forwarding AuditLog for distribution changes)
    try:
        from app.services.audit_service import log_event
        await log_event(
            db,
            event_type="ADMIN_ACTION",
            entity_type="distribution_list",
            entity_id=str(dist_id),
            actor_type="user",
            actor_id=wallet_address.lower(),
            changes={
                "old_label": old_label,
                "new_label": dl.label,
                "recipients_replaced": payload.recipients is not None,
            },
        )
    except Exception as exc:
        logger.warning("[dist] Audit log failed: %s", exc)

    await db.commit()
    await db.refresh(dl)

    logger.info("[dist] Updated list %s (owner=%s)", dist_id, wallet_address[:10])

    resp = {
        "status": "updated",
        "distribution": _serialize_distribution(dl),
    }
    if warnings:
        resp["warnings"] = warnings

    return _response(resp)


# ═══════════════════════════════════════════════════════════
#  5. DELETE /distributions/{id} — Soft delete
# ═══════════════════════════════════════════════════════════

@distribution_router.delete("/distributions/{dist_id}")
@require_wallet_auth
async def delete_distribution(
    request: Request,
    dist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    dl = await _get_distribution_or_404(db, dist_id)
    await _verify_dist_owner(dl, wallet_address)

    # Block if used by active rules
    active_rule_count = await _count_active_rules_using(db, dist_id)
    if active_rule_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "DISTRIBUTION_IN_USE",
                "message": (
                    f"Cannot delete: distribution list is used by "
                    f"{active_rule_count} active rule(s). "
                    "Remove or reassign rules first."
                ),
                "active_rules_count": active_rule_count,
            },
        )

    dl.is_active = False
    await db.commit()

    logger.info("[dist] Soft-deleted list %s (owner=%s)", dist_id, wallet_address[:10])

    return _response({
        "status": "deleted",
        "distribution_id": str(dist_id),
    })


# ═══════════════════════════════════════════════════════════
#  6. POST /distributions/{id}/import-csv — Import CSV
# ═══════════════════════════════════════════════════════════

@distribution_router.post("/distributions/{dist_id}/import-csv")
@require_wallet_auth
async def import_csv(
    request: Request,
    dist_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    dl = await _get_distribution_or_404(db, dist_id)
    await _verify_dist_owner(dl, wallet_address)

    # Read and parse CSV
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))

    required_cols = {"address", "percent_bps"}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=422,
            detail=f"CSV must have columns: {', '.join(sorted(required_cols))} (and optional: label)",
        )

    recipients: list[dict] = []
    errors: list[str] = []
    seen_addrs: set[str] = set()

    for row_num, row in enumerate(reader, start=2):
        addr = (row.get("address") or "").strip()
        bps_str = (row.get("percent_bps") or "").strip()
        label = (row.get("label") or "").strip() or None

        if not addr:
            errors.append(f"Row {row_num}: missing address")
            continue
        if not ETH_ADDR_RE.match(addr):
            errors.append(f"Row {row_num}: invalid address '{addr}'")
            continue

        addr = addr.lower()
        if addr in seen_addrs:
            errors.append(f"Row {row_num}: duplicate address '{addr}'")
            continue
        seen_addrs.add(addr)

        try:
            bps = int(bps_str)
            if bps < 1 or bps > 10000:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append(f"Row {row_num}: percent_bps must be integer 1-10000, got '{bps_str}'")
            continue

        recipients.append({"address": addr, "percent_bps": bps, "label": label})

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"error": "CSV_VALIDATION_FAILED", "errors": errors[:50]},
        )

    if len(recipients) == 0:
        raise HTTPException(status_code=422, detail="CSV contains no valid recipients")

    if len(recipients) > MAX_RECIPIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {MAX_RECIPIENTS} recipients, CSV has {len(recipients)}",
        )

    total_bps = sum(r["percent_bps"] for r in recipients)
    if total_bps != 10000:
        raise HTTPException(
            status_code=422,
            detail=f"Recipient percentages must sum to 10000 bps (100%), got {total_bps}",
        )

    # Deactivate old recipients
    for r in dl.recipients:
        r.is_active = False

    # Add new recipients
    for r in recipients:
        new_r = DistributionRecipient(
            list_id=dl.id,
            address=r["address"],
            percent_bps=r["percent_bps"],
            label=r["label"],
        )
        db.add(new_r)

    await db.commit()
    await db.refresh(dl)

    logger.info(
        "[dist] Imported %d recipients from CSV into list %s",
        len(recipients), dist_id,
    )

    return _response({
        "status": "imported",
        "recipient_count": len(recipients),
        "distribution": _serialize_distribution(dl),
    })


# ═══════════════════════════════════════════════════════════
#  7. GET /distributions/{id}/export-csv — Export CSV
# ═══════════════════════════════════════════════════════════

@distribution_router.get("/distributions/{dist_id}/export-csv")
async def export_csv(
    dist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    dl = await _get_distribution_or_404(db, dist_id)

    active_recipients = [r for r in (dl.recipients or []) if r.is_active]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["address", "percent_bps", "label"])
    writer.writeheader()
    for r in active_recipients:
        writer.writerow({
            "address": r.address,
            "percent_bps": r.percent_bps,
            "label": r.label or "",
        })

    content = output.getvalue()
    filename = f"distribution_{str(dist_id)[:8]}.csv"

    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
