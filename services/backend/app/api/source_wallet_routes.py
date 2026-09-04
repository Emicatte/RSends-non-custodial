"""Session (dashboard) surface for AutoSplit source wallets.

Lives under `/api/v1/user/org/`, so it is JWT-exempt from the API-key
middleware through the existing `/api/v1/user/` `EXEMPT_PATHS` entry — the auth
perimeter is untouched. Every route resolves its org from the JWT
(`require_org_approved`), never from a client parameter, and every query is
scoped `(org_id, environment)` IN the SQL so a cross-tenant or cross-env miss
is a 404 rather than a 403 that confirms the row exists.

Registration is SIWE challenge/verify, mirroring `/api/v1/user/wallets`. The
proof is what makes the GLOBAL uniqueness index safe: once a source wallet has
executed, its address is public on chain, so without ownership proof anyone
could register it first and lock the real owner out with a 409 and no
in-product remedy. Requiring a signature costs the merchant nothing they do not
already have — they must hold that key to sign `setPolicy` and `approve` — and
it makes both squatting and typos structurally impossible.

Writes are `admin`: this is money-routing configuration, the same class as the
org settlement wallet. Reads (including the live on-chain panel, which shows
only public chain data) are `viewer`.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from eth_utils import to_checksum_address
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.require_org_approved import require_org_approved
from app.db.session import get_db
from app.models.source_wallet_models import SourceWallet
from app.models.source_wallet_schemas import (
    SourceWalletChallengeRequest,
    SourceWalletChallengeResponse,
    SourceWalletListResponse,
    SourceWalletResponse,
    SourceWalletVerifyRequest,
)
from app.services.auth_audit import record_auth_event
from app.services.siwe_service import (
    SIWEError,
    SIWEUnavailable,
    create_challenge,
    verify_challenge,
)
from app.services.source_wallet_service import (
    auto_split_address_for,
    read_onchain_state,
    resolve_registration_context,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user/org/source-wallets", tags=["source-wallets"])

#: Bounds how much keeper gas one org can commit us to. Counts ACTIVE rows
#: only, so pausing a wallet frees a slot. Mirrors MAX_WALLETS_PER_ORG.
MAX_SOURCE_WALLETS_PER_ORG = 10

#: The partial unique index (model `__table_args__` + migration 0024) and the
#: columns it covers — Postgres reports the name, SQLite reports the columns.
IDX_ACTIVE = ("uq_source_wallets_active", ("chain_id", "address", "token_symbol"))


def _constraint_name(exc: IntegrityError) -> Optional[str]:
    """The offending constraint's name, or None when the driver doesn't say.

    asyncpg carries `constraint_name` on its own exception, which SQLAlchemy
    re-raises as the wrapper's `__cause__` — reading the psycopg2-shaped
    `exc.orig.diag` instead is what once turned two 409 handlers into 500s in
    production while SQLite-backed CI stayed green.
    """
    orig = getattr(exc, "orig", None)
    for candidate in (orig, getattr(orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return str(name)
    diag = getattr(orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else None


def _violated(exc: IntegrityError, index) -> bool:
    """True when `exc` is a violation of `index`, on either dialect.

    An unrecognised shape returns False so the error re-raises as a 500 — ugly
    but honest, and never a confidently wrong 409 blaming the wrong constraint.
    """
    name, columns = index
    constraint = _constraint_name(exc)
    if constraint:
        return constraint == name

    message = str(getattr(exc, "orig", exc))
    if "UNIQUE constraint failed" in message:
        reported = {
            part.strip().split(".")[-1] for part in message.split(":", 1)[1].split(",")
        }
        return reported == set(columns)

    orig = getattr(exc, "orig", None)
    log.warning(
        "IntegrityError shape not recognised; not mapped to a 409 "
        "(orig=%s, cause=%s, index=%s)",
        type(orig).__name__,
        type(getattr(orig, "__cause__", None)).__name__,
        name,
    )
    return False


def _sanitize_label(raw: Optional[str]) -> str:
    return "" if raw is None else raw.strip()[:64]


def _siwe_error_to_http(e: SIWEError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": e.code, "detail": e.detail})


async def _count_active_for_org(db: AsyncSession, org_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(SourceWallet)
        .where(
            SourceWallet.org_id == org_id,
            SourceWallet.disabled_at.is_(None),
        )
    )
    return int(result.scalar() or 0)


async def _active_holder(
    db: AsyncSession, *, chain_id: int, address_lc: str, token_symbol: str
) -> Optional[SourceWallet]:
    """The ACTIVE registration of this (chain, wallet, token), in ANY org.

    Global on purpose — see the module docstring. The index is the real
    backstop against a concurrent double-register; this read is what turns the
    common case into a clean 409 instead of a rolled-back transaction.
    """
    result = await db.execute(
        select(SourceWallet).where(
            SourceWallet.chain_id == chain_id,
            SourceWallet.address == address_lc,
            SourceWallet.token_symbol == token_symbol,
            SourceWallet.disabled_at.is_(None),
        )
    )
    return result.scalars().first()


async def _owned_row(
    db: AsyncSession, *, source_wallet_id: str, org_id: str
) -> Optional[SourceWallet]:
    """Tenant scope IN the query: a foreign or missing id is indistinguishable."""
    result = await db.execute(
        select(SourceWallet).where(
            SourceWallet.id == source_wallet_id,
            SourceWallet.org_id == org_id,
        )
    )
    return result.scalars().first()


@router.get("", response_model=SourceWalletListResponse)
async def list_source_wallets(
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    environment: str = Query("test", pattern="^(test|live)$"),
    db: AsyncSession = Depends(get_db),
) -> SourceWalletListResponse:
    _user_id, org_id, _role = ctx

    result = await db.execute(
        select(SourceWallet)
        .where(
            SourceWallet.org_id == org_id,
            SourceWallet.environment == environment,
        )
        .order_by(SourceWallet.created_at.asc())
    )
    rows = result.scalars().all()
    active = sum(1 for r in rows if r.disabled_at is None)

    return SourceWalletListResponse(
        source_wallets=[SourceWalletResponse.model_validate(r) for r in rows],
        max_allowed=MAX_SOURCE_WALLETS_PER_ORG,
        remaining_slots=max(0, MAX_SOURCE_WALLETS_PER_ORG - active),
    )


@router.post("/challenge", response_model=SourceWalletChallengeResponse)
async def post_challenge(
    payload: SourceWalletChallengeRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("admin")),
    db: AsyncSession = Depends(get_db),
) -> SourceWalletChallengeResponse:
    """Issue the SIWE challenge, but only for a registration that could
    actually succeed — the gates run here too so a merchant is not asked to
    sign for a chain or token we will reject a moment later."""
    user_id, org_id, _role = ctx

    context = resolve_registration_context(payload.chain, payload.token_symbol)
    address_lc = payload.address  # schema lowercases

    if await _count_active_for_org(db, org_id) >= MAX_SOURCE_WALLETS_PER_ORG:
        raise HTTPException(409, {"code": "max_source_wallets_reached"})

    holder = await _active_holder(
        db,
        chain_id=context["chain_id"],
        address_lc=address_lc,
        token_symbol=payload.token_symbol,
    )
    if holder is not None:
        raise HTTPException(409, {"code": "source_wallet_taken"})

    # The nonce is keyed by the user proving key ownership, even though the row
    # is org-owned — same rule as wallet linking.
    try:
        message, nonce, expires_at = await create_challenge(
            user_id=user_id,
            address=address_lc,
            chain_id=context["chain_id"],
        )
    except SIWEUnavailable:
        raise HTTPException(status_code=503, detail={"code": "siwe_unavailable"})
    except SIWEError as e:
        raise _siwe_error_to_http(e)

    return SourceWalletChallengeResponse(
        siwe_message=message, nonce=nonce, expires_at=expires_at
    )


@router.post(
    "/verify",
    response_model=SourceWalletResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_verify(
    payload: SourceWalletVerifyRequest,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("admin")),
    db: AsyncSession = Depends(get_db),
) -> SourceWalletResponse:
    """Verify the signature and create the registration.

    Gate order is fixed and load-bearing (see source_wallet_service): chain,
    then AutoSplit availability, then token. Everything the row is stamped with
    — chain id, environment, the token's on-chain address — is derived here,
    never taken from the request.
    """
    user_id, org_id, _role = ctx

    context = resolve_registration_context(payload.chain, payload.token_symbol)
    address_lc = payload.address  # schema lowercases

    if await _count_active_for_org(db, org_id) >= MAX_SOURCE_WALLETS_PER_ORG:
        raise HTTPException(409, {"code": "max_source_wallets_reached"})

    holder = await _active_holder(
        db,
        chain_id=context["chain_id"],
        address_lc=address_lc,
        token_symbol=payload.token_symbol,
    )
    if holder is not None:
        raise HTTPException(409, {"code": "source_wallet_taken"})

    try:
        verified_message = await verify_challenge(
            user_id=user_id,
            nonce=payload.nonce,
            address=address_lc,
            chain_id=context["chain_id"],
            signature=payload.signature,
        )
    except SIWEUnavailable:
        raise HTTPException(status_code=503, detail={"code": "siwe_unavailable"})
    except SIWEError as e:
        await record_auth_event(
            event_type="source_wallet_register_failed",
            user_id=user_id,
            details={
                "code": e.code,
                "detail": e.detail,
                "address_prefix": address_lc[:10],
                "chain_id": context["chain_id"],
                "org_id": str(org_id),
            },
        )
        raise _siwe_error_to_http(e)

    row = SourceWallet(
        id=str(uuid.uuid4()),
        org_id=org_id,
        created_by_user_id=user_id,
        chain_id=context["chain_id"],
        environment=context["environment"],
        address=address_lc,
        display_address=to_checksum_address(address_lc),
        token_symbol=payload.token_symbol,
        label=_sanitize_label(payload.label),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if not _violated(exc, IDX_ACTIVE):
            raise
        raise HTTPException(409, {"code": "source_wallet_taken"})

    await db.commit()
    await db.refresh(row)

    await record_auth_event(
        event_type="source_wallet_registered",
        user_id=user_id,
        details={
            "source_wallet_id": str(row.id),
            "address": row.address,
            "chain_id": row.chain_id,
            "token_symbol": row.token_symbol,
            "message_len": len(verified_message),
            "org_id": str(org_id),
        },
    )

    return SourceWalletResponse.model_validate(row)


@router.post("/{source_wallet_id}/disable", response_model=SourceWalletResponse)
async def post_disable(
    source_wallet_id: str,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("admin")),
    db: AsyncSession = Depends(get_db),
) -> SourceWalletResponse:
    """Pause the keeper for this registration. Idempotent.

    This is the PRODUCT-level brake and it is not a security boundary: the
    trustless one is `approve(autoSplit, 0)` from the merchant's own wallet,
    which no server can undo. Disabling frees the address for re-registration
    (the unique index is partial on `disabled_at IS NULL`), and re-enabling is
    a fresh row so every pause stays in the audit trail.
    """
    user_id, org_id, _role = ctx

    row = await _owned_row(db, source_wallet_id=source_wallet_id, org_id=org_id)
    if row is None:
        raise HTTPException(404, {"code": "source_wallet_not_found"})

    if row.disabled_at is None:
        row.disabled_at = datetime.now(timezone.utc)
        row.disabled_reason = "disabled_by_admin"
        await db.commit()
        await db.refresh(row)

        await record_auth_event(
            event_type="source_wallet_disabled",
            user_id=user_id,
            details={
                "source_wallet_id": str(row.id),
                "address": row.address,
                "chain_id": row.chain_id,
                "org_id": str(org_id),
            },
        )

    return SourceWalletResponse.model_validate(row)


@router.get("/{source_wallet_id}/onchain")
async def get_onchain(
    source_wallet_id: str,
    ctx: Tuple[str, str, str] = Depends(require_org_approved("viewer")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live policy + allowance + balance for this registration.

    Read on demand and never persisted: the policy belongs to the merchant's
    key, who can rewrite it on chain without telling us, so a stored copy would
    be silently stale. Tenant scope resolves first, so a foreign id 404s before
    any RPC work is done on its behalf.
    """
    _user_id, org_id, _role = ctx

    row = await _owned_row(db, source_wallet_id=source_wallet_id, org_id=org_id)
    if row is None:
        raise HTTPException(404, {"code": "source_wallet_not_found"})

    auto_split = auto_split_address_for_chain_id(row.chain_id)
    if auto_split is None:
        raise HTTPException(
            422,
            {
                "error": "AUTO_SPLIT_UNAVAILABLE",
                "message": "Auto Split is not available on this chain.",
            },
        )

    from app.services.router_registry import token_for
    from app.services.router_registry import _CHAIN_NAME_BY_ID

    chain = _CHAIN_NAME_BY_ID.get(row.chain_id)
    token = token_for(chain, row.token_symbol) if chain else None
    if token is None:
        # The registry stopped offering this token since registration — say so
        # rather than guessing an address.
        raise HTTPException(
            422,
            {
                "error": "UNSUPPORTED_TOKEN",
                "message": (
                    f"Token {row.token_symbol} is no longer enabled on this chain."
                ),
            },
        )

    state = await read_onchain_state(
        chain=chain,
        chain_id=row.chain_id,
        auto_split=auto_split,
        token_address=token[0],
        wallet=row.address,
    )
    return {"source_wallet_id": str(row.id), **state}


def auto_split_address_for_chain_id(chain_id: int) -> Optional[str]:
    """Chain-id flavour of the availability gate, for rows that already carry
    an id rather than a registry name."""
    from app.services.router_registry import _CHAIN_NAME_BY_ID

    chain = _CHAIN_NAME_BY_ID.get(chain_id)
    return auto_split_address_for(chain) if chain else None
