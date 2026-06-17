"""User-scoped address book CRUD + bulk-import.

All endpoints require a valid access token (Bearer) issued by
/api/v1/auth/google. Every query is filtered by the authenticated user's id
so a user cannot see or mutate another user's contacts. Upserts are
idempotent via UNIQUE(user_id, address) with a pre-check + flush pattern
that works on both Postgres and SQLite.

On POST to an existing (user_id, address) row, we UPDATE the mutable fields
(label, last_used_at, tx_count, extra_metadata) rather than returning the row
unchanged — matches the client's recordSuccessfulTx semantics (re-record on
every successful tx bumps tx_count and refreshes lastUsed/label).
"""

import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth_service import AuthError, verify_access_token
from app.models.user_contacts_models import UserContact
from app.models.user_contacts_schemas import (
    BulkImportContactError,
    BulkImportContactsRequest,
    BulkImportContactsResponse,
    ContactCreate,
    ContactResponse,
    ContactUpdate,
)

router = APIRouter(prefix="/api/v1/user/contacts", tags=["user-contacts"])


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


def _normalize_address(address: str) -> str:
    """EVM addresses (0x + 40 hex) are case-insensitive → lower.
    Tron (T...) / Solana (base58) are case-sensitive → strip only.
    """
    s = address.strip()
    if s.startswith("0x") and len(s) == 42:
        return s.lower()
    return s


async def _upsert_contact(
    db: AsyncSession, user_id: str, payload: ContactCreate
) -> tuple[UserContact, bool]:
    """Insert or update on (user_id, address) collision.

    Returns (row, was_created). was_created=False means row existed and was
    updated. Pre-check + flush + catch pattern — dialect-agnostic.
    """
    addr = _normalize_address(payload.address)

    existing_q = select(UserContact).where(
        UserContact.user_id == user_id,
        UserContact.address == addr,
    )
    existing = (await db.execute(existing_q)).scalar_one_or_none()

    if existing is not None:
        if payload.label:
            existing.label = payload.label
        if payload.last_used_at is not None:
            existing.last_used_at = payload.last_used_at
        if payload.tx_count > 0:
            existing.tx_count = payload.tx_count
        if payload.extra_metadata:
            existing.extra_metadata = payload.extra_metadata
        existing.updated_at = datetime.now(timezone.utc)
        return existing, False

    row = UserContact(
        id=str(uuid.uuid4()),
        user_id=user_id,
        address=addr,
        label=payload.label,
        last_used_at=payload.last_used_at,
        tx_count=payload.tx_count,
        extra_metadata=payload.extra_metadata or {},
    )
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


@router.get("", response_model=List[ContactResponse])
async def list_contacts(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> List[ContactResponse]:
    result = await db.execute(
        select(UserContact)
        .where(UserContact.user_id == user_id)
        .order_by(
            desc(UserContact.last_used_at).nulls_last(),
            UserContact.label.asc(),
        )
    )
    return [ContactResponse.model_validate(r) for r in result.scalars()]


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_or_upsert_contact(
    payload: ContactCreate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    row, _ = await _upsert_contact(db, user_id, payload)
    await db.commit()
    await db.refresh(row)
    return ContactResponse.model_validate(row)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: str,
    payload: ContactUpdate,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    result = await db.execute(
        select(UserContact).where(
            UserContact.id == contact_id,
            UserContact.user_id == user_id,
        )
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    update_data = payload.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(contact, k, v)
    contact.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(contact)
    return ContactResponse.model_validate(contact)


@router.post("/bulk-import", response_model=BulkImportContactsResponse)
async def bulk_import(
    payload: BulkImportContactsRequest,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> BulkImportContactsResponse:
    imported = 0
    skipped = 0
    errors: List[BulkImportContactError] = []

    for contact_data in payload.contacts:
        try:
            _, was_created = await _upsert_contact(db, user_id, contact_data)
            if was_created:
                imported += 1
            else:
                skipped += 1
        except Exception as e:  # pragma: no cover - best-effort bulk
            errors.append(
                BulkImportContactError(
                    address=contact_data.address, error=str(e)[:200]
                )
            )

    await db.commit()
    return BulkImportContactsResponse(
        imported=imported, skipped=skipped, errors=errors
    )


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: str,
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        delete(UserContact).where(
            UserContact.id == contact_id,
            UserContact.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_all_contacts(
    user_id: str = Depends(require_user_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await db.execute(
        delete(UserContact).where(UserContact.user_id == user_id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
