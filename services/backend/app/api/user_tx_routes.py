"""User-scoped transaction history CRUD + bulk-import.

All endpoints require a valid access token (Bearer) issued by
/api/v1/auth/google. Every query is filtered by the authenticated user's id
so a user cannot see or mutate another user's transactions. Inserts are
idempotent via UNIQUE(user_id, chain_id, tx_hash) on the Postgres path
(ON CONFLICT DO NOTHING) and via a manual pre-check on SQLite.
"""

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthError, verify_access_token
from app.models.user_tx_models import UserTransaction
from app.models.user_tx_schemas import (
    BulkImportError,
    BulkImportRequest,
    BulkImportResponse,
    PaginatedTransactions,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)

router = APIRouter(
    prefix="/api/v1/user/transactions", tags=["user-transactions"]
)

PAGE_SIZE = 50


async def require_user_id(request: Request) -> str:
    """Extract authenticated user_id from Bearer access token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "no_token"})
    token = auth[7:]
    try:
        claims = await verify_access_token(token)
    except AuthError as e:
        code = 503 if e.code == "auth_unavailable" else 401
        raise HTTPException(status_code=code, detail={"code": e.code})
    return claims["sub"]


def _encode_cursor(submitted_at: datetime, tx_id: str) -> str:
    payload = {"t": submitted_at.isoformat(), "id": str(tx_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["t"]), str(payload["id"])
    except Exception:
        raise HTTPException(status_code=400, detail={"code": "invalid_cursor"})


@router.get("", response_model=PaginatedTransactions)
async def list_transactions(
    user_id: str = Depends(require_user_id),
    chain_id: Optional[int] = Query(None),
    tx_type: Optional[str] = Query(None),
    tx_status: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedTransactions:
    conditions = [UserTransaction.user_id == user_id]
    if chain_id is not None:
        conditions.append(UserTransaction.chain_id == chain_id)
    if tx_type:
        conditions.append(UserTransaction.tx_type == tx_type)
    if tx_status:
        conditions.append(UserTransaction.tx_status == tx_status)

    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        conditions.append(
            or_(
                UserTransaction.submitted_at < cursor_time,
                and_(
                    UserTransaction.submitted_at == cursor_time,
                    UserTransaction.id < cursor_id,
                ),
            )
        )

    result = await db.execute(
        select(UserTransaction)
        .where(and_(*conditions))
        .order_by(
            desc(UserTransaction.submitted_at),
            desc(UserTransaction.id),
        )
        .limit(PAGE_SIZE + 1)
    )
    rows = list(result.scalars())

    has_more = len(rows) > PAGE_SIZE
    items = rows[:PAGE_SIZE]
    next_cursor = (
        _encode_cursor(items[-1].submitted_at, items[-1].id)
        if has_more and items
        else None
    )

    return PaginatedTransactions(
        items=[TransactionResponse.model_validate(r) for r in items],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def _insert_idempotent(
    db: AsyncSession, user_id: str, payload: TransactionCreate
) -> tuple[UserTransaction, bool]:
    """Insert or fetch existing on (user_id, chain_id, tx_hash) collision.

    Returns (row, was_created). Works on both Postgres and SQLite by doing a
    pre-check — we accept the race-vs-idempotency tradeoff: the UNIQUE index
    is the source of truth; on conflict we catch IntegrityError and fetch.
    """
    existing_q = select(UserTransaction).where(
        UserTransaction.user_id == user_id,
        UserTransaction.chain_id == payload.chain_id,
        UserTransaction.tx_hash == payload.tx_hash,
    )
    existing = (await db.execute(existing_q)).scalar_one_or_none()
    if existing is not None:
        return existing, False

    data = payload.model_dump(exclude_none=True)
    submitted_at = data.pop("submitted_at", None)
    row = UserTransaction(
        id=str(uuid.uuid4()),
        user_id=user_id,
        **data,
    )
    if submitted_at is not None:
        row.submitted_at = submitted_at
    db.add(row)
    try:
        await db.flush()
    except Exception:
        await db.rollback()
        existing = (await db.execute(existing_q)).scalar_one_or_none()
        if existing is not None:
            return existing, False
        raise
    return row, True


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: TransactionCreate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    row, _ = await _insert_idempotent(db, user_id, payload)
    await db.commit()
    await db.refresh(row)
    return TransactionResponse.model_validate(row)


@router.patch("/{tx_id}", response_model=TransactionResponse)
async def update_transaction(
    tx_id: str,
    payload: TransactionUpdate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    result = await db.execute(
        select(UserTransaction).where(
            UserTransaction.id == tx_id,
            UserTransaction.user_id == user_id,
        )
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    update_data = payload.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(tx, k, v)
    tx.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(tx)
    return TransactionResponse.model_validate(tx)


@router.post("/bulk-import", response_model=BulkImportResponse)
async def bulk_import(
    payload: BulkImportRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> BulkImportResponse:
    imported = 0
    skipped = 0
    errors: List[BulkImportError] = []

    for tx_data in payload.transactions:
        try:
            _, was_created = await _insert_idempotent(db, user_id, tx_data)
            if was_created:
                imported += 1
            else:
                skipped += 1
        except Exception as e:  # pragma: no cover - best-effort bulk
            errors.append(
                BulkImportError(tx_hash=tx_data.tx_hash, error=str(e)[:200])
            )

    await db.commit()
    return BulkImportResponse(imported=imported, skipped=skipped, errors=errors)


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    tx_id: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        delete(UserTransaction).where(
            UserTransaction.id == tx_id,
            UserTransaction.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_transactions(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await db.execute(
        delete(UserTransaction).where(UserTransaction.user_id == user_id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
