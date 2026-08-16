"""
API Key Management Routes

POST /api/v1/keys/generate     — Generate new API key (returns plaintext ONCE)
GET  /api/v1/keys              — List all keys for owner (prefix only)
GET  /api/v1/keys/{id}/usage   — Get usage stats for a key
POST /api/v1/keys/{id}/revoke  — Revoke a key (soft delete)
DELETE /api/v1/keys/{id}       — Delete a key permanently
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.approval_policy import approval_denial
from app.db.session import get_db
from app.models.api_key_models import ApiKey
from app.models.org_models import Organization
from app.security.api_keys import generate_api_key
from app.security.auth import require_wallet_auth
from app.services.owner_identity import resolve_org_for_wallet

api_key_router = APIRouter(prefix="/api/v1/keys", tags=["api-keys"])


class GenerateKeyRequest(BaseModel):
    owner_address: str
    label: str = "Default"
    scope: str = "write"
    # Defaults to the POWERLESS environment. A caller who omits the field gets a
    # sandbox key; minting a live one has to be asked for explicitly, and is
    # gated below. The previous default was "live".
    environment: str = "test"

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, v: str) -> str:
        if v not in ("read", "write", "admin"):
            raise ValueError("scope must be 'read', 'write', or 'admin'")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ("test", "live"):
            raise ValueError("environment must be 'test' or 'live'")
        return v


class GenerateKeyResponse(BaseModel):
    id: int
    key: str
    prefix: str
    label: str
    scope: str
    environment: str
    created_at: str


class ApiKeyListItem(BaseModel):
    id: int
    prefix: str
    label: str
    scope: str
    environment: str
    is_active: bool
    rate_limit_rpm: int
    total_requests: int
    total_intents_created: int
    total_volume_usd: str
    created_at: str
    last_used_at: Optional[str] = None


class RevokeRequest(BaseModel):
    owner_address: str


@api_key_router.post("/generate", response_model=GenerateKeyResponse)
@require_wallet_auth
async def generate_key(
    request: Request,
    req: GenerateKeyRequest,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Generate a new API key. Returns plaintext ONCE — store it safely.

    Auth: wallet signature obbligatoria (EIP-191). L'owner della key è il
    wallet del firmatario verificato — il campo `owner_address` del body è
    IGNORATO (previene il mint anonimo di key per indirizzi arbitrari).
    """
    owner = wallet_address.lower()

    # L'admin scope non è self-provisionabile: una key admin va creata
    # out-of-band (gate ADMIN_PATHS), non da chi possiede solo un wallet.
    if req.scope == "admin":
        raise HTTPException(403, "admin scope cannot be self-provisioned")

    # api_keys.org_id is NOT NULL since 0014: the signer's wallet must map to
    # exactly one org (422 fail-closed otherwise — never a NULL-org key).
    org_id = await resolve_org_for_wallet(db, owner)

    # APPROVAL GATE. This route is exempt from the API-key middleware and its
    # only auth is a wallet signature, so without this a wallet that resolves to
    # one org could mint a LIVE key for an org nobody ever approved. Same policy
    # object as the merchant API and session surfaces — `declined` blocks in both
    # environments, the sandbox carve-out applies only to "test", and anything
    # that is not an explicit approval fails closed on "live".
    approval_status = (
        await db.execute(
            select(Organization.approval_status).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()
    denial = approval_denial(approval_status, environment=req.environment)
    if denial is not None:
        raise denial

    count_q = select(ApiKey).where(
        ApiKey.owner_address == owner,
        ApiKey.is_active == True,  # noqa: E712
        ApiKey.environment == req.environment,
    )
    result = await db.execute(count_q)
    if len(result.scalars().all()) >= 5:
        raise HTTPException(400, f"Maximum 5 active {req.environment} API keys per account")

    plaintext_key, key_fields = generate_api_key(environment=req.environment)

    api_key = ApiKey(
        owner_address=owner,
        org_id=org_id,
        **key_fields,
        label=req.label,
        scope=req.scope,
        environment=req.environment,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return GenerateKeyResponse(
        id=api_key.id,
        key=plaintext_key,
        prefix=key_fields["display_prefix"],
        label=api_key.label,
        scope=req.scope,
        environment=req.environment,
        created_at=api_key.created_at.isoformat(),
    )


@api_key_router.get("/", response_model=list[ApiKeyListItem])
@require_wallet_auth
async def list_keys(
    request: Request,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """List all API keys for the authenticated wallet. Never returns the full key.

    Auth: wallet signature obbligatoria. L'owner è il firmatario verificato
    (niente lettura cross-owner via query param).
    """
    owner = wallet_address.lower()
    q = (
        select(ApiKey)
        .where(ApiKey.owner_address == owner)
        .order_by(ApiKey.created_at.desc())
    )
    result = await db.execute(q)
    keys = result.scalars().all()
    return [
        ApiKeyListItem(
            id=k.id,
            prefix=k.display_prefix or k.key_prefix,
            label=k.label,
            scope=k.scope or "write",
            environment=k.environment or "live",
            is_active=k.is_active,
            rate_limit_rpm=k.rate_limit_rpm or 100,
            total_requests=k.total_requests or 0,
            total_intents_created=k.total_intents_created or 0,
            total_volume_usd=k.total_volume_usd or "0",
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        )
        for k in keys
    ]


@api_key_router.get("/{key_id}/usage")
@require_wallet_auth
async def get_key_usage(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Get usage stats for a specific API key (owned by the authenticated wallet)."""
    q = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.owner_address == wallet_address.lower(),
    )
    result = await db.execute(q)
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key not found")

    return {
        "id": key.id,
        "label": key.label,
        "scope": key.scope or "write",
        "environment": key.environment or "live",
        "rate_limit_rpm": key.rate_limit_rpm or 100,
        "usage": {
            "total_requests": key.total_requests or 0,
            "total_intents_created": key.total_intents_created or 0,
            "total_volume_usd": key.total_volume_usd or "0",
        },
        "limits": {
            "monthly_intent_limit": key.monthly_intent_limit or 0,
            "monthly_volume_limit_usd": key.monthly_volume_limit_usd or "0",
        },
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


@api_key_router.post("/{key_id}/revoke")
@require_wallet_auth
async def revoke_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Revoke an API key (soft delete — keeps record). Owner = authenticated wallet."""
    q = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.owner_address == wallet_address.lower(),
    )
    result = await db.execute(q)
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key not found")

    key.is_active = False
    key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "revoked", "id": key_id}


@api_key_router.delete("/{key_id}")
@require_wallet_auth
async def delete_key(
    request: Request,
    key_id: int,
    db: AsyncSession = Depends(get_db),
    wallet_address: str = "",
):
    """Permanently delete an API key (owned by the authenticated wallet)."""
    q = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.owner_address == wallet_address.lower(),
    )
    result = await db.execute(q)
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key not found")

    await db.delete(key)
    await db.commit()
    return {"status": "deleted", "id": key_id}
