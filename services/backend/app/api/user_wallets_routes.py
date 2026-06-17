"""User-linked EVM wallets: SIWE challenge/verify + CRUD.

Scope (v1): EVM only. Clients prove ownership via EIP-4361. The server stores
the canonical SIWE message in Redis at challenge time and re-uses that stored
copy for signature recovery at verify time — clients cannot tamper with the
message hashed for recovery.

Prompt 11 — wallets are now ORG-scoped: every wallet belongs to the user's
active org and is visible to every member. RBAC:
    list / challenge / verify (link) / patch label → operator+
    set primary / unlink                           → admin only
    (Verify/challenge require "operator" so viewers cannot initiate a link.)

Key invariants
- Hard cap: MAX_WALLETS_PER_ORG active rows per (org, chain_family). Checked
  at /challenge (fail-fast UX) AND /verify (race defence).
- Uniqueness: partial unique on (org_id, chain_family, address) WHERE
  unlinked_at IS NULL — same address can be relinked after unlink, with a
  fresh row, preserving the audit trail. Also means the same address CAN be
  linked across different orgs (e.g. a user's personal org and a team org).
- Primary: exactly one per (org, chain_family) when any active row exists.
  First link in an org is auto-primary. Primary flip is "UPDATE others -> false;
  set self -> true" with the partial unique index as the backstop.
- Demote protection: refusing is_primary=false on the sole primary. Caller
  must promote another wallet first.
- Audit: every lifecycle event — link / promote / unlink / link_failed — is
  recorded via record_auth_event WITH `org_id` in details. Failures log
  address prefix, not full address, to avoid leaking in logs.
- Error shape: HTTPException(detail={"code": "..."}).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from eth_utils import is_address, to_checksum_address
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_role import require_org_role
from app.db.session import get_db
from app.models.auth_models import User
from app.models.user_wallets_models import UserWallet
from app.models.user_wallets_schemas import (
    WalletChallengeRequest,
    WalletChallengeResponse,
    WalletListResponse,
    WalletPatchRequest,
    WalletResponse,
    WalletVerifyRequest,
)
from app.services.auth_audit import record_auth_event
from app.services.siwe_service import (
    MAX_WALLETS_PER_ORG,
    SIWEError,
    SIWEUnavailable,
    create_challenge,
    verify_challenge,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user/wallets", tags=["user-wallets"])


async def _count_active_wallets_for_org(
    db: AsyncSession, org_id: str, chain_family: str = "evm"
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(UserWallet)
        .where(
            UserWallet.org_id == org_id,
            UserWallet.chain_family == chain_family,
            UserWallet.unlinked_at.is_(None),
        )
    )
    return int(result.scalar() or 0)


async def _active_by_address_for_org(
    db: AsyncSession, org_id: str, chain_family: str, address_lc: str
) -> Optional[UserWallet]:
    result = await db.execute(
        select(UserWallet).where(
            UserWallet.org_id == org_id,
            UserWallet.chain_family == chain_family,
            UserWallet.address == address_lc,
            UserWallet.unlinked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _sanitize_label(raw: Optional[str]) -> str:
    if raw is None:
        return ""
    return raw.strip()[:64]


def _siwe_error_to_http(e: SIWEError) -> HTTPException:
    """Map SIWE error codes to HTTP semantics. All return 4xx with code."""
    status_code = 400
    detail: dict = {"code": e.code}
    if e.detail:
        detail["detail"] = e.detail
    return HTTPException(status_code=status_code, detail=detail)


def _hydrate_wallet(wallet: UserWallet, created_by_email: Optional[str]) -> WalletResponse:
    resp = WalletResponse.model_validate(wallet)
    resp.created_by_email = created_by_email
    return resp


@router.get("", response_model=WalletListResponse)
async def list_wallets(
    ctx: Tuple[str, str, str] = Depends(require_org_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> WalletListResponse:
    _user_id, org_id, _role = ctx
    result = await db.execute(
        select(UserWallet, User.email)
        .select_from(UserWallet)
        .outerjoin(User, User.id == UserWallet.created_by_user_id)
        .where(
            UserWallet.org_id == org_id,
            UserWallet.unlinked_at.is_(None),
        )
        .order_by(desc(UserWallet.is_primary), asc(UserWallet.created_at))
    )
    rows = list(result.all())
    wallets = [_hydrate_wallet(r[0], r[1]) for r in rows]
    active_count = len(wallets)
    return WalletListResponse(
        wallets=wallets,
        max_allowed=MAX_WALLETS_PER_ORG,
        remaining_slots=max(0, MAX_WALLETS_PER_ORG - active_count),
    )


@router.post("/challenge", response_model=WalletChallengeResponse)
async def post_challenge(
    payload: WalletChallengeRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
) -> WalletChallengeResponse:
    user_id, org_id, _role = ctx
    if payload.chain_family != "evm":
        raise HTTPException(
            status_code=400, detail={"code": "chain_family_unsupported_v1"}
        )
    if not is_address(payload.address):
        raise HTTPException(status_code=400, detail={"code": "invalid_address"})

    addr_lc = payload.address.lower()

    active_count = await _count_active_wallets_for_org(db, org_id, "evm")
    if active_count >= MAX_WALLETS_PER_ORG:
        raise HTTPException(
            status_code=409, detail={"code": "max_wallets_reached"}
        )

    dup = await _active_by_address_for_org(db, org_id, "evm", addr_lc)
    if dup is not None:
        raise HTTPException(
            status_code=409, detail={"code": "wallet_already_linked"}
        )

    # SIWE nonce is keyed by (user_id, nonce) — the user creating the link is
    # still the identity proving wallet ownership, even though the row is org-
    # owned. So we pass `user_id` here (NOT `org_id`).
    try:
        message, nonce, expires_at = await create_challenge(
            user_id=user_id,
            address=payload.address,
            chain_id=payload.chain_id,
        )
    except SIWEUnavailable:
        raise HTTPException(status_code=503, detail={"code": "siwe_unavailable"})
    except SIWEError as e:
        raise _siwe_error_to_http(e)

    return WalletChallengeResponse(
        siwe_message=message,
        nonce=nonce,
        expires_at=expires_at,
    )


@router.post(
    "/verify",
    response_model=WalletResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_verify(
    payload: WalletVerifyRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
) -> WalletResponse:
    user_id, org_id, _role = ctx
    if payload.chain_family != "evm":
        raise HTTPException(
            status_code=400, detail={"code": "chain_family_unsupported_v1"}
        )
    if not is_address(payload.address):
        raise HTTPException(status_code=400, detail={"code": "invalid_address"})

    addr_lc = payload.address.lower()

    active_count = await _count_active_wallets_for_org(db, org_id, "evm")
    if active_count >= MAX_WALLETS_PER_ORG:
        raise HTTPException(
            status_code=409, detail={"code": "max_wallets_reached"}
        )

    try:
        verified_message = await verify_challenge(
            user_id=user_id,
            nonce=payload.nonce,
            address=payload.address,
            chain_id=payload.chain_id,
            signature=payload.signature,
        )
    except SIWEUnavailable:
        raise HTTPException(status_code=503, detail={"code": "siwe_unavailable"})
    except SIWEError as e:
        await record_auth_event(
            event_type="wallet_link_failed",
            user_id=user_id,
            details={
                "code": e.code,
                "detail": e.detail,
                "address_prefix": addr_lc[:10],
                "chain_id": payload.chain_id,
                "org_id": str(org_id),
            },
        )
        raise _siwe_error_to_http(e)

    is_first = active_count == 0

    wallet = UserWallet(
        id=str(uuid.uuid4()),
        user_id=user_id,
        org_id=org_id,
        created_by_user_id=user_id,
        chain_family="evm",
        address=addr_lc,
        display_address=to_checksum_address(payload.address),
        chain_id=payload.chain_id,
        verified_chain_id=payload.chain_id,
        label=_sanitize_label(payload.label),
        is_primary=is_first,
        verified_via="siwe",
        extra_metadata={},
    )
    db.add(wallet)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "wallet_already_linked"}
        )

    await db.commit()
    await db.refresh(wallet)

    # Audit (best-effort; opens its own session, won't roll back the insert).
    await record_auth_event(
        event_type="wallet_linked",
        user_id=user_id,
        details={
            "wallet_id": str(wallet.id),
            "address": wallet.address,
            "chain_id": payload.chain_id,
            "is_primary": bool(wallet.is_primary),
            "message_len": len(verified_message),
            "org_id": str(org_id),
        },
    )

    # Creator email isn't needed in the response for the user who just linked
    # (they're the creator) — leave it None; the list endpoint resolves it for
    # subsequent views.
    return WalletResponse.model_validate(wallet)


async def _promote_primary(
    db: AsyncSession, wallet: UserWallet
) -> None:
    """Clear any other active primary in the same (org, chain_family), then
    mark `wallet` primary. Partial unique index is the backstop on races.
    """
    await db.execute(
        UserWallet.__table__.update()
        .where(
            and_(
                UserWallet.org_id == wallet.org_id,
                UserWallet.chain_family == wallet.chain_family,
                UserWallet.id != wallet.id,
                UserWallet.is_primary.is_(True),
                UserWallet.unlinked_at.is_(None),
            )
        )
        .values(is_primary=False, updated_at=datetime.now(timezone.utc))
    )
    wallet.is_primary = True
    wallet.updated_at = datetime.now(timezone.utc)


@router.patch("/{wallet_id}", response_model=WalletResponse)
async def patch_wallet(
    wallet_id: str,
    payload: WalletPatchRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_role("operator")),
    db: AsyncSession = Depends(get_db),
) -> WalletResponse:
    user_id, org_id, role = ctx

    # Setting is_primary is an admin-only action even though patching label is
    # operator — mixed payloads require admin when is_primary is touched.
    if payload.is_primary is not None and role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "insufficient_role", "required": "admin"},
        )

    result = await db.execute(
        select(UserWallet, User.email)
        .select_from(UserWallet)
        .outerjoin(User, User.id == UserWallet.created_by_user_id)
        .where(
            UserWallet.id == wallet_id,
            UserWallet.org_id == org_id,
            UserWallet.unlinked_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    wallet, created_by_email = row

    audit_promoted = False

    if payload.label is not None:
        wallet.label = _sanitize_label(payload.label)

    if payload.is_primary is not None:
        if payload.is_primary is False and wallet.is_primary is True:
            raise HTTPException(
                status_code=400, detail={"code": "cannot_demote_primary"}
            )
        if payload.is_primary is True and wallet.is_primary is False:
            try:
                await _promote_primary(db, wallet)
            except IntegrityError:
                await db.rollback()
                # refetch and retry once
                result = await db.execute(
                    select(UserWallet).where(
                        UserWallet.id == wallet_id,
                        UserWallet.org_id == org_id,
                        UserWallet.unlinked_at.is_(None),
                    )
                )
                wallet = result.scalar_one_or_none()
                if wallet is None:
                    raise HTTPException(
                        status_code=404, detail={"code": "not_found"}
                    )
                try:
                    await _promote_primary(db, wallet)
                except IntegrityError:
                    await db.rollback()
                    raise HTTPException(
                        status_code=409, detail={"code": "primary_race"}
                    )
            audit_promoted = True

    wallet.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(wallet)

    if audit_promoted:
        await record_auth_event(
            event_type="wallet_promoted_primary",
            user_id=user_id,
            details={
                "wallet_id": str(wallet.id),
                "address": wallet.address,
                "chain_family": wallet.chain_family,
                "org_id": str(org_id),
            },
        )

    return _hydrate_wallet(wallet, created_by_email)


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_wallet(
    wallet_id: str,
    ctx: Tuple[str, str, str] = Depends(require_org_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_id, org_id, _role = ctx
    result = await db.execute(
        select(UserWallet).where(
            UserWallet.id == wallet_id,
            UserWallet.org_id == org_id,
            UserWallet.unlinked_at.is_(None),
        )
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=404, detail={"code": "not_found"})

    now = datetime.now(timezone.utc)
    was_primary = bool(wallet.is_primary)
    successor_id: Optional[str] = None

    if was_primary:
        succ_result = await db.execute(
            select(UserWallet)
            .where(
                UserWallet.org_id == org_id,
                UserWallet.chain_family == wallet.chain_family,
                UserWallet.id != wallet.id,
                UserWallet.unlinked_at.is_(None),
            )
            .order_by(asc(UserWallet.created_at))
            .limit(1)
        )
        successor = succ_result.scalar_one_or_none()
        # Clear the outgoing primary first so the partial unique index stays
        # satisfied when the successor is flipped on.
        wallet.is_primary = False
        wallet.unlinked_at = now
        wallet.unlinked_reason = "user_requested"
        wallet.updated_at = now
        await db.flush()

        if successor is not None:
            successor.is_primary = True
            successor.updated_at = now
            successor_id = str(successor.id)
    else:
        wallet.unlinked_at = now
        wallet.unlinked_reason = "user_requested"
        wallet.updated_at = now

    await db.commit()

    await record_auth_event(
        event_type="wallet_unlinked",
        user_id=user_id,
        details={
            "wallet_id": str(wallet.id),
            "address": wallet.address,
            "chain_family": wallet.chain_family,
            "was_primary": was_primary,
            "successor_wallet_id": successor_id,
            "org_id": str(org_id),
        },
    )

    if was_primary and successor_id is not None:
        await record_auth_event(
            event_type="wallet_promoted_primary",
            user_id=user_id,
            details={
                "wallet_id": successor_id,
                "chain_family": wallet.chain_family,
                "reason": "primary_unlinked",
                "org_id": str(org_id),
            },
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
