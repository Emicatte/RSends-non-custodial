"""
RSends Backend — Multi-Wallet Split API Routes

POST /api/v1/splits/contracts                        → create SplitContract
GET  /api/v1/splits/contracts?client_id=&active_only → list contracts
GET  /api/v1/splits/contracts/{id}                   → contract detail
POST /api/v1/splits/contracts/{id}/deactivate        → soft-deactivate
POST /api/v1/splits/simulate                         → preview split math
GET  /api/v1/splits/contracts/{id}/executions        → audit trail

Note:
  - Percentuali SEMPRE in basis points (interi). Sum == 10000 obbligatorio.
  - Pydantic v2 (@field_validator) per coerenza col resto del codebase.
  - Tutta la matematica di conversione importo umano → unità minime usa
    Decimal, non float, per non perdere precisione.
"""
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.split_models import (
    SplitContract,
    SplitRecipient,
    SplitExecution,
)
from app.security.auth import require_wallet_auth
from app.services.split_engine import (
    compute_split,
    format_split_plan,
    validate_recipients,
)

logger = logging.getLogger("split_routes")

split_router = APIRouter(prefix="/api/v1/splits", tags=["splits"])

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
MAX_SPLIT_RECIPIENTS = 20
MIN_SPLIT_RECIPIENTS = 2


def _validate_eth_address(v: str) -> str:
    if not v or not ETH_ADDR_RE.match(v):
        raise ValueError(f"Invalid EVM address: {v}")
    return v.lower()


# ═══════════════════════════════════════════════════════════
#  Pydantic schemas (v2)
# ═══════════════════════════════════════════════════════════

class RecipientInput(BaseModel):
    wallet_address: str = Field(..., min_length=42, max_length=42)
    label: str = ""
    role: str = "recipient"                            # "primary" | "commission" | "fee" | "recipient"
    share_bps: int = Field(..., ge=1, le=10000)        # 9500 = 95.00%
    position: int = Field(0, ge=0)

    @field_validator("wallet_address")
    @classmethod
    def _v_addr(cls, v: str) -> str:
        return _validate_eth_address(v)


class CreateSplitContractRequest(BaseModel):
    client_id: str = Field(..., min_length=1, max_length=128)
    client_name: str = ""
    contract_ref: str = ""
    master_wallet: str = Field(..., min_length=42, max_length=42)
    chain_id: int = 8453
    recipients: list[RecipientInput]
    rsend_fee_bps: int = Field(50, ge=0, le=10000)
    allowed_tokens: list[str] = []

    @field_validator("master_wallet")
    @classmethod
    def _v_master(cls, v: str) -> str:
        return _validate_eth_address(v)

    @field_validator("recipients")
    @classmethod
    def _v_recipients(cls, recipients: list) -> list:
        if len(recipients) < MIN_SPLIT_RECIPIENTS:
            raise ValueError(f"At least {MIN_SPLIT_RECIPIENTS} recipients required")
        if len(recipients) > MAX_SPLIT_RECIPIENTS:
            raise ValueError(f"Maximum {MAX_SPLIT_RECIPIENTS} recipients")

        total = sum(r.share_bps for r in recipients)
        if total != 10000:
            raise ValueError(
                f"Recipients share_bps must sum to exactly 10000 (100.00%), got {total}"
            )

        addrs = [r.wallet_address.lower() for r in recipients]
        if len(addrs) != len(set(addrs)):
            raise ValueError("Duplicate wallet addresses not allowed")

        return recipients


class SimulateSplitRequest(BaseModel):
    amount: str                 # importo umano, es: "100.00"
    token: str = "USDC"
    decimals: int = Field(6, ge=0, le=36)
    recipients: list[RecipientInput]
    rsend_fee_bps: int = Field(50, ge=0, le=10000)

    @field_validator("recipients")
    @classmethod
    def _v_recipients(cls, recipients: list) -> list:
        if len(recipients) < MIN_SPLIT_RECIPIENTS:
            raise ValueError(f"At least {MIN_SPLIT_RECIPIENTS} recipients required")
        if len(recipients) > MAX_SPLIT_RECIPIENTS:
            raise ValueError(f"Maximum {MAX_SPLIT_RECIPIENTS} recipients")

        total = sum(r.share_bps for r in recipients)
        if total != 10000:
            raise ValueError(
                f"Recipients share_bps must sum to exactly 10000 (100.00%), got {total}"
            )

        addrs = [r.wallet_address.lower() for r in recipients]
        if len(addrs) != len(set(addrs)):
            raise ValueError("Duplicate wallet addresses not allowed")

        return recipients


# ═══════════════════════════════════════════════════════════
#  Serializers
# ═══════════════════════════════════════════════════════════

def _serialize_recipient(r: SplitRecipient) -> dict:
    return {
        "id": r.id,
        "wallet_address": r.wallet_address,
        "label": r.label or "",
        "role": r.role or "recipient",
        "share_bps": r.share_bps,
        "share_percent": f"{r.share_bps / 100:.2f}%",
        "position": r.position,
        "is_active": bool(r.is_active),
    }


def _serialize_contract(c: SplitContract, include_recipients: bool = True) -> dict:
    data = {
        "id": c.id,
        "client_id": c.client_id,
        "client_name": c.client_name or "",
        "contract_ref": c.contract_ref or "",
        "version": c.version,
        "master_wallet": c.master_wallet,
        "chain_id": c.chain_id,
        "chain_family": c.chain_family or "evm",
        "allowed_tokens": _parse_allowed_tokens(c.allowed_tokens),
        "rsend_fee_bps": c.rsend_fee_bps,
        "is_active": bool(c.is_active),
        "is_locked": bool(c.is_locked),
        "superseded_by": c.superseded_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "locked_at": c.locked_at.isoformat() if c.locked_at else None,
        "deactivated_at": c.deactivated_at.isoformat() if c.deactivated_at else None,
    }
    if include_recipients:
        sorted_recipients = sorted(c.recipients or [], key=lambda r: r.position)
        data["recipients"] = [_serialize_recipient(r) for r in sorted_recipients]
        data["recipient_count"] = len(data["recipients"])
        data["total_bps"] = sum(r.share_bps for r in sorted_recipients)
    return data


def _serialize_execution(e: SplitExecution) -> dict:
    detail = None
    if e.distribution_detail:
        try:
            detail = json.loads(e.distribution_detail)
        except Exception:
            detail = None
    return {
        "id": e.id,
        "contract_id": e.contract_id,
        "source_tx_hash": e.source_tx_hash,
        "input_amount": e.input_amount,
        "input_token": e.input_token,
        "input_decimals": e.input_decimals,
        "status": e.status,
        "total_distributed": e.total_distributed,
        "rsend_fee": e.rsend_fee,
        "remainder": e.remainder,
        "distribution_detail": detail,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    }


def _parse_allowed_tokens(raw: Optional[str]) -> list:
    if not raw:
        return []
    # Supporta sia JSON che CSV per tolleranza
    raw = raw.strip()
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
    return [t.strip() for t in raw.split(",") if t.strip()]


# ═══════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════

def _human_to_raw(amount_str: str, decimals: int) -> int:
    """Converte un importo umano ('100.00') in unità minime (int),
    usando Decimal per non introdurre float drift.
    Solleva ValueError se il risultato non è rappresentabile in int."""
    if decimals < 0:
        raise ValueError("decimals must be >= 0")
    try:
        amt = Decimal(str(amount_str))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid amount: {amount_str!r}")
    if amt <= 0:
        raise ValueError(f"Amount must be > 0, got {amount_str}")
    factor = Decimal(10) ** decimals
    raw = (amt * factor).to_integral_value(rounding="ROUND_DOWN")
    return int(raw)


async def _next_version(db: AsyncSession, client_id: str) -> int:
    result = await db.execute(
        select(func.max(SplitContract.version)).where(
            SplitContract.client_id == client_id
        )
    )
    current = result.scalar()
    return int(current or 0) + 1


async def _get_contract_or_404(
    db: AsyncSession, contract_id: int, with_recipients: bool = True
) -> SplitContract:
    q = select(SplitContract).where(SplitContract.id == contract_id)
    if with_recipients:
        q = q.options(selectinload(SplitContract.recipients))
    result = await db.execute(q)
    contract = result.scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")
    return contract


async def _verify_split_owner(contract: SplitContract, wallet_address: str) -> None:
    """Verifica che `wallet_address` sia owner del contratto.

    Nullable owner_address (legacy row non backfillata) → 403, mai accettare
    ownership implicita. Forza il backfill prima di un'eventuale migration
    NOT NULL futura.
    """
    if contract.owner_address is None:
        raise HTTPException(
            status_code=403, detail="Contract has no owner; access denied"
        )
    if contract.owner_address != wallet_address.lower():
        raise HTTPException(
            status_code=403, detail="Not the owner of this split contract"
        )


# ═══════════════════════════════════════════════════════════
#  1. POST /contracts — create SplitContract
# ═══════════════════════════════════════════════════════════

@split_router.post("/contracts")
@require_wallet_auth
async def create_split_contract(
    request: Request,
    req: CreateSplitContractRequest,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Crea un nuovo SplitContract per un cliente.

    Il contratto è immutabile dopo creazione: per modificare,
    si crea una nuova versione con stesso `client_id`. La versione
    viene incrementata automaticamente.

    Auth: wallet signature obbligatoria. owner_address = wallet del firmatario.
    """
    owner = wallet_address.lower()

    # Validazione di fondo (stessa regola usata da compute_split)
    recipients_dicts = [r.model_dump() for r in req.recipients]
    valid, err = validate_recipients(recipients_dicts)
    if not valid:
        raise HTTPException(status_code=400, detail=err)

    try:
        next_version = await _next_version(db, req.client_id)

        contract = SplitContract(
            client_id=req.client_id,
            client_name=req.client_name or None,
            contract_ref=req.contract_ref or None,
            master_wallet=req.master_wallet.lower(),
            owner_address=owner,
            chain_id=req.chain_id,
            rsend_fee_bps=req.rsend_fee_bps,
            allowed_tokens=(
                json.dumps(req.allowed_tokens) if req.allowed_tokens else None
            ),
            version=next_version,
            is_active=True,
            is_locked=False,
        )

        for r in req.recipients:
            contract.recipients.append(
                SplitRecipient(
                    wallet_address=r.wallet_address,
                    label=r.label or None,
                    role=r.role or "recipient",
                    share_bps=r.share_bps,
                    position=r.position,
                    is_active=True,
                )
            )

        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        # Re-fetch con recipients per serializzare in modo pulito
        fresh = await _get_contract_or_404(db, contract.id, with_recipients=True)

        logger.info(
            "[split] Created contract id=%s client=%s v%d recipients=%d",
            fresh.id, req.client_id, next_version, len(req.recipients),
        )

        return {
            "status": "created",
            "contract": _serialize_contract(fresh),
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("[split] create_split_contract failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create contract: {e}")


# ═══════════════════════════════════════════════════════════
#  2. GET /contracts — list
# ═══════════════════════════════════════════════════════════

@split_router.get("/contracts")
@require_wallet_auth
async def list_contracts(
    request: Request,
    active_only: bool = Query(True, description="Only active contracts"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    """Lista SplitContract, opzionalmente filtrati per client_id / stato."""
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    try:
        q = select(SplitContract).options(
            selectinload(SplitContract.recipients)
        )
        q = q.where(SplitContract.owner_address == wallet_address.lower())
        if active_only:
            q = q.where(SplitContract.is_active == True)  # noqa: E712
        q = q.order_by(desc(SplitContract.created_at)).limit(limit)

        result = await db.execute(q)
        contracts = result.scalars().all()

        return {
            "contracts": [_serialize_contract(c) for c in contracts],
            "total": len(contracts),
        }
    except Exception as e:
        logger.exception("[split] list_contracts failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list contracts: {e}")


# ═══════════════════════════════════════════════════════════
#  3. GET /contracts/{id} — detail
# ═══════════════════════════════════════════════════════════

@split_router.get("/contracts/{contract_id}")
@require_wallet_auth
async def get_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    """Dettaglio di un SplitContract con tutti i recipient."""
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    try:
        contract = await _get_contract_or_404(db, contract_id, with_recipients=True)
        await _verify_split_owner(contract, wallet_address)
        return {"contract": _serialize_contract(contract)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[split] get_contract failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch contract: {e}")


# ═══════════════════════════════════════════════════════════
#  4. POST /contracts/{id}/deactivate — soft deactivate
# ═══════════════════════════════════════════════════════════

@split_router.post("/contracts/{contract_id}/deactivate")
@require_wallet_auth
async def deactivate_contract(
    request: Request,
    contract_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Disattiva un contratto.

    Soft-delete: il record resta per audit. I pagamenti in arrivo
    non verranno più splittati finché non viene creata una nuova versione.
    Operazione idempotente.

    Auth: wallet signature obbligatoria. Solo l'owner del contratto può disattivarlo.
    """
    try:
        contract = await _get_contract_or_404(db, contract_id, with_recipients=False)
        await _verify_split_owner(contract, wallet_address)

        if not contract.is_active:
            # Idempotente — nessuna modifica necessaria
            return {
                "status": "already_deactivated",
                "contract_id": contract_id,
                "deactivated_at": (
                    contract.deactivated_at.isoformat() if contract.deactivated_at else None
                ),
            }

        contract.is_active = False
        contract.deactivated_at = datetime.utcnow()
        await db.commit()

        logger.info("[split] Deactivated contract id=%s client=%s", contract_id, contract.client_id)

        return {
            "status": "deactivated",
            "contract_id": contract_id,
            "deactivated_at": contract.deactivated_at.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("[split] deactivate_contract failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to deactivate: {e}")


# ═══════════════════════════════════════════════════════════
#  5. POST /simulate — preview split senza eseguire
# ═══════════════════════════════════════════════════════════

@split_router.post("/simulate")
async def simulate_split(req: SimulateSplitRequest):
    """Simula uno split SENZA eseguirlo.

    Utile per preview del piano di distribuzione prima della firma
    del contratto. Matematica identica a quella dell'esecuzione reale.
    """
    try:
        amount_raw = _human_to_raw(req.amount, req.decimals)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    recipients_dicts = [r.model_dump() for r in req.recipients]

    try:
        plan = compute_split(
            input_amount=amount_raw,
            recipients=recipients_dicts,
            rsend_fee_bps=req.rsend_fee_bps,
            token=req.token,
            decimals=req.decimals,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("[split] simulate failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Simulation failed: {e}")

    return {
        "simulation": True,
        **format_split_plan(plan),
    }


# ═══════════════════════════════════════════════════════════
#  6. GET /contracts/{id}/executions — audit trail
# ═══════════════════════════════════════════════════════════

@split_router.get("/contracts/{contract_id}/executions")
@require_wallet_auth
async def list_executions(
    request: Request,
    contract_id: int,
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    wallet_address: Optional[str] = None,
):
    """Lista esecuzioni di un contratto (audit trail)."""
    if not wallet_address:
        raise HTTPException(
            status_code=500,
            detail="wallet_address not injected by @require_wallet_auth",
        )
    try:
        # 404 se il contratto non esiste
        contract = await _get_contract_or_404(db, contract_id, with_recipients=False)
        await _verify_split_owner(contract, wallet_address)

        result = await db.execute(
            select(SplitExecution)
            .where(SplitExecution.contract_id == contract_id)
            .order_by(desc(SplitExecution.started_at))
            .limit(limit)
        )
        executions = result.scalars().all()

        return {
            "contract_id": contract_id,
            "executions": [_serialize_execution(e) for e in executions],
            "total": len(executions),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[split] list_executions failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list executions: {e}")
