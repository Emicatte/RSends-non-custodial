"""Session-minted rsend_ merchant API keys (Option B, 2026-07-15).

One login, one place to get a working key: the /app session (JWT, org RBAC)
mints the SAME `rsend_` keys the wallet-signed `/api/v1/keys/generate` route
mints — same `generate_api_key` primitive, same `api_keys` table, same tenant
identity. The org's `owner_address` comes from `resolve_owner_address`
(SIWE-linked primary wallet, else the unclaimed settlement wallet), i.e. the
exact address the wallet flow proves by signature, so session-minted keys land
in the same merchant scope as everything else.

Security posture (per the 2026-07-15 product decision):
- Minting requires the org **admin** role (stricter than rsusr_'s operator).
- Scope is pinned to `write` (admin scope is never self-provisionable).
- Approval: since 2026-08-08 a SUBMITTED COMPANY PROFILE is the gate for a
  sandbox key — `require_org_approved` lets `pending_approval` through for the
  test environment, so nobody waits on an operator to evaluate the API. The
  mint handler re-asserts real approval for any NON-test environment (see the
  guard in `create_merchant_key`), so lifting the `ENVIRONMENT` pin below can
  never hand out a live key to an unapproved org. Policy: deps/approval_policy.
- Environment is pinned to `test` — /app is hard-locked to test (mainnet
  routers undeployed); handing out `rsend_live_` keys that cannot transact
  would be a footgun. Lift when mainnet ships.
- The 409s of the resolver propagate untouched: `no_primary_wallet` (org has
  neither a linked wallet nor a settlement wallet — the UI shows a "set your
  settlement wallet first" card) and `settlement_wallet_conflict` (contested
  identity stays loud).
- Minted rows carry `org_id` (migration 0011) so the resolver's conflict
  check can exclude the org's own keys (self-conflict trap).

Error shape: HTTPException(detail={"code": ...}) like sibling user_* routes.
Rate limits: dedicated ENDPOINT_LIMITS entries (per-IP), most-specific-first.
The wallet-signed `/api/v1/keys/*` routes are untouched (retirement is a
separate pass — Option C).
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.api.deps.approval_policy import SANDBOX_ENVIRONMENT, approval_denial
from app.api.deps.require_org_approved import require_org_approved
from app.db.session import get_db
from app.models.api_key_models import ApiKey
from app.models.org_models import Organization
from app.security.api_keys import generate_api_key
from app.services.auth_audit import record_auth_event
from app.services.owner_identity import resolve_owner_address

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/user/org/merchant-keys", tags=["user-org-merchant-keys"]
)

# Same cap as the wallet-signed generate route: 5 active keys per
# (owner_address, environment).
MAX_ACTIVE_KEYS = 5
# /app is hard-locked to the test environment; see module docstring.
ENVIRONMENT = "test"


class MerchantKeyCreateRequest(BaseModel):
    label: str = Field(default="Default", min_length=1, max_length=100)


class MerchantKeyItem(BaseModel):
    id: int
    prefix: str
    label: str
    scope: str
    environment: str
    is_active: bool
    session_minted: bool  # False = historical wallet-signed mint
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class MerchantKeyListResponse(BaseModel):
    keys: list[MerchantKeyItem]
    max_allowed: int
    remaining_slots: int
    owner_address: str


class MerchantKeyCreateResponse(BaseModel):
    id: int
    key: str  # full plaintext — returned ONCE, never retrievable again
    prefix: str
    label: str
    scope: str
    environment: str
    created_at: str


def _to_item(k: ApiKey) -> MerchantKeyItem:
    return MerchantKeyItem(
        id=k.id,
        prefix=k.display_prefix or k.key_prefix,
        label=k.label,
        scope=k.scope or "write",
        environment=k.environment or "live",
        is_active=bool(k.is_active),
        session_minted=k.org_id is not None,
        created_at=k.created_at.isoformat(),
        last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
        revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
    )


def _tenant_filter(org_id: str):
    """org_id is the key tenant since 0014 (every row carries it, NOT NULL).
    No owner_address arm: a key minted by another org must stay invisible
    even when the resolved owner address coincides."""
    return ApiKey.org_id == org_id


async def _count_active(db: AsyncSession, org_id: str) -> int:
    return (
        await db.execute(
            select(func.count(ApiKey.id)).where(
                _tenant_filter(org_id),
                ApiKey.is_active.is_(True),
                ApiKey.environment == ENVIRONMENT,
            )
        )
    ).scalar() or 0


@router.get("", response_model=MerchantKeyListResponse)
async def list_merchant_keys(
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    db: AsyncSession = Depends(get_db),
):
    """Never returns key material — prefix only. 409 `no_primary_wallet` /
    `settlement_wallet_conflict` propagate from the resolver (the UI turns
    the former into the "set your settlement wallet first" card)."""
    _user_id, org_id, _role = ctx
    owner = await resolve_owner_address(db, org_id)

    rows = (
        (
            await db.execute(
                select(ApiKey)
                .where(_tenant_filter(org_id))
                .order_by(desc(ApiKey.created_at))
            )
        )
        .scalars()
        .all()
    )
    active = await _count_active(db, org_id)
    return MerchantKeyListResponse(
        keys=[_to_item(k) for k in rows],
        max_allowed=MAX_ACTIVE_KEYS,
        remaining_slots=max(0, MAX_ACTIVE_KEYS - active),
        owner_address=owner,
    )


@router.post("", response_model=MerchantKeyCreateResponse, status_code=201)
async def create_merchant_key(
    payload: MerchantKeyCreateRequest,
    request: Request,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("admin")),
    db: AsyncSession = Depends(get_db),
):
    user_id, org_id, _role = ctx

    # ENVIRONMENT is pinned to "test" below, so `require_org_approved`'s sandbox
    # rule (KYB submitted, approval not required) is the right gate today. The
    # DAY THAT PIN IS LIFTED this guard becomes load-bearing: minting a key for
    # any other environment demands a genuinely approved org, because that key
    # moves real money. Unreachable now, deliberately — a silent hole otherwise.
    if ENVIRONMENT != SANDBOX_ENVIRONMENT:
        approval = (
            await db.execute(
                select(Organization.approval_status).where(Organization.id == org_id)
            )
        ).scalar_one_or_none()
        denial = approval_denial(approval, environment=ENVIRONMENT)
        if denial is not None:
            raise denial

    owner = await resolve_owner_address(db, org_id)

    if await _count_active(db, org_id) >= MAX_ACTIVE_KEYS:
        raise HTTPException(
            status_code=409,
            detail={"code": "max_keys_reached", "max": MAX_ACTIVE_KEYS},
        )

    plaintext_key, key_fields = generate_api_key(environment=ENVIRONMENT)
    # `environment` comes from key_fields, NOT from a second variable: it is the
    # same decision that produced the prefix inside plaintext_key, so the row and
    # the key string cannot disagree.
    api_key = ApiKey(
        owner_address=owner,
        org_id=org_id,
        **key_fields,
        label=payload.label,
        scope="write",
    )
    db.add(api_key)
    # Commit BEFORE the audit call: record_auth_event opens its OWN session
    # and never raises, so ordering doesn't change durability — but on the
    # shared-connection SQLite test engine an audit-side rollback would sweep
    # rows still pending in this session.
    await db.commit()
    await db.refresh(api_key)

    await record_auth_event(
        event_type="api_key_created",
        user_id=user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={
            "key_type": "rsend",
            "key_id": str(api_key.id),
            "org_id": str(org_id),
            "owner_address": owner,
            "label": api_key.label,
            "environment": ENVIRONMENT,
        },
    )

    return MerchantKeyCreateResponse(
        id=api_key.id,
        key=plaintext_key,
        prefix=key_fields["display_prefix"],
        label=api_key.label,
        scope="write",
        environment=ENVIRONMENT,
        created_at=api_key.created_at.isoformat(),
    )


@router.post("/{key_id}/revoke", response_model=MerchantKeyItem)
async def revoke_merchant_key(
    key_id: int,
    request: Request,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Soft-revoke, idempotent. Tenant scope IN the query → 404 on miss or
    cross-tenant (never 403 — don't leak existence). Scoped purely by org_id,
    so no owner-identity resolution (and none of its 409s) is needed."""
    user_id, org_id, _role = ctx

    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                _tenant_filter(org_id),
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    if key.is_active:
        key.is_active = False
        key.revoked_at = datetime.now(timezone.utc)
        await db.commit()  # before the audit call — see create_merchant_key
        await db.refresh(key)

        await record_auth_event(
            event_type="api_key_revoked",
            user_id=user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            details={
                "key_type": "rsend",
                "key_id": str(key.id),
                "org_id": str(org_id),
                "label": key.label,
            },
        )

    return _to_item(key)
