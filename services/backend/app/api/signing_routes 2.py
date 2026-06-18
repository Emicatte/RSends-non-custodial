"""
RSends Backend — Internal Signing Guard API.

Called by the Next.js oracle endpoint before and after signing.
These endpoints are internal-only (not exposed to public).

Endpoints:
  POST /api/internal/signing/check
    → Rate limit + nonce uniqueness + parameter validation
    → Returns { allowed: true } or { allowed: false, reason: "..." }

  POST /api/internal/signing/audit
    → Record a signing event to the immutable audit log
"""

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)

signing_router = APIRouter(prefix="/api/internal/signing", tags=["signing"])


# ── Internal-secret gate (H3) ─────────────────────────────────────
# /api/internal/* is exempt from API-key auth and reachable via the public
# Next.js catch-all proxy. Require a shared secret (sent by the Next oracle as
# X-Internal-Secret) so only the server-side oracle can reach these endpoints
# — closing audit-log poisoning even on the directly-exposed backend.
async def require_internal_secret(request: Request) -> None:
    settings = get_settings()
    secret = settings.internal_proxy_secret
    if not secret:
        # Not configured: allowed only in dev/debug; in prod it is required
        # (validate_settings fails startup) and we fail-closed as a backstop.
        if settings.debug:
            return
        raise HTTPException(status_code=503, detail="internal endpoint not configured")
    provided = request.headers.get("X-Internal-Secret", "")
    if not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=403, detail="forbidden")

# ── Supported chains ──────────────────────────────────────
SUPPORTED_CHAINS = {1, 10, 56, 137, 8453, 42161, 43114, 84532, 728126428}

# ── Amount bounds (in wei) ────────────────────────────────
# $0.01 in ETH at ~$2200/ETH ≈ 4.5e12 wei — use conservative minimum
MIN_AMOUNT_WEI = 1_000_000_000_000       # 1e12 (< $0.01)
# $100,000 in ETH ≈ 45.45 ETH ≈ 4.545e19 wei — generous upper bound
MAX_AMOUNT_WEI = 100_000_000_000_000_000_000_000  # 1e23 (~$200K max safety)

# ── Max deadline offset ───────────────────────────────────
MAX_DEADLINE_SECONDS = 600  # 10 minutes from now

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# ═══════════════════════════════════════════════════════════════
#  Request / Response schemas
# ═══════════════════════════════════════════════════════════════

class SigningCheckRequest(BaseModel):
    """Pre-signing validation request."""
    wallet: str = Field(..., description="Sender wallet address")
    recipient: str = Field(..., description="Recipient address")
    token_in: str = Field(default=ZERO_ADDRESS)
    amount_in_wei: str = Field(..., description="Amount in wei (string)")
    nonce: str = Field(..., description="bytes32 hex nonce")
    deadline: int = Field(..., description="Unix timestamp deadline")
    chain_id: int = Field(..., description="Target chain ID")
    ip_address: Optional[str] = None
    contract_address: Optional[str] = Field(
        default=None, description="FeeRouter contract address for this chain"
    )


class SigningCheckResponse(BaseModel):
    allowed: bool
    reason: Optional[str] = None
    details: Optional[str] = None


class SigningAuditRequest(BaseModel):
    """Post-signing audit record."""
    signer_address: str
    chain_id: int
    sender: str
    recipient: str
    token_in: str = ZERO_ADDRESS
    amount_in_wei: str
    nonce: str
    deadline: int
    approved: bool
    denial_reason: Optional[str] = None
    risk_score: Optional[int] = None
    risk_level: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None


async def _record_signing_denied(body: "SigningCheckRequest", *, reason: str) -> None:
    """Record AML-denied signing attempt to the audit log (best-effort)."""
    try:
        from app.services.signing_audit import record_signing_event

        await record_signing_event(
            signer_address="",
            chain_id=body.chain_id,
            sender=body.wallet,
            recipient=body.recipient,
            token_in=body.token_in,
            amount_in_wei=body.amount_in_wei,
            nonce=body.nonce,
            deadline=body.deadline,
            approved=False,
            denial_reason=reason,
            risk_level="blocked",
        )
    except Exception as e:
        logger.warning("Failed to record signing denial audit: %s", e)


# ═══════════════════════════════════════════════════════════════
#  POST /api/internal/signing/check
# ═══════════════════════════════════════════════════════════════

@signing_router.post("/check", response_model=SigningCheckResponse)
async def signing_check(
    body: SigningCheckRequest,
    request: Request,
    _internal: None = Depends(require_internal_secret),
):
    """Pre-signing validation: rate limit + nonce + parameter bounds.

    Called by the Next.js oracle BEFORE signing.
    Fail-closed on Redis failure.
    """
    import time

    # ── 1. Chain validation ───────────────────────────────
    if body.chain_id not in SUPPORTED_CHAINS:
        return SigningCheckResponse(
            allowed=False,
            reason=f"unsupported_chain ({body.chain_id})",
        )

    # ── 2. Recipient validation ──────────────────────────
    recipient_lower = body.recipient.lower()

    if recipient_lower == ZERO_ADDRESS:
        return SigningCheckResponse(
            allowed=False,
            reason="recipient_is_zero_address",
        )

    # Don't sign if recipient is the FeeRouter itself (funds stuck)
    if body.contract_address and recipient_lower == body.contract_address.lower():
        return SigningCheckResponse(
            allowed=False,
            reason="recipient_is_fee_router_contract",
        )

    # ── 3. Amount bounds ─────────────────────────────────
    try:
        amount = int(body.amount_in_wei)
    except (ValueError, TypeError):
        return SigningCheckResponse(
            allowed=False,
            reason=f"invalid_amount ({body.amount_in_wei})",
        )

    if amount < MIN_AMOUNT_WEI:
        return SigningCheckResponse(
            allowed=False,
            reason=f"amount_too_small ({amount} < {MIN_AMOUNT_WEI})",
        )

    if amount > MAX_AMOUNT_WEI:
        return SigningCheckResponse(
            allowed=False,
            reason=f"amount_too_large ({amount} > {MAX_AMOUNT_WEI})",
        )

    # ── 4. Deadline bounds ───────────────────────────────
    now = int(time.time())

    if body.deadline <= now:
        return SigningCheckResponse(
            allowed=False,
            reason=f"deadline_in_past ({body.deadline} <= {now})",
        )

    if body.deadline > now + MAX_DEADLINE_SECONDS:
        return SigningCheckResponse(
            allowed=False,
            reason=f"deadline_too_far ({body.deadline - now}s > {MAX_DEADLINE_SECONDS}s)",
        )

    # ── 5. AML screening (fail-closed) ─────────────────────
    from app.services.aml_service import is_blacklisted, full_aml_check
    from app.services.aml_exceptions import AMLBlockedError
    from app.tokens.registry import get_token
    from app.services.price_service import get_eur_value
    from decimal import Decimal

    try:
        blocked, block_reason = await is_blacklisted(body.recipient)
        if blocked:
            logger.warning(
                "Signing rejected: recipient blacklisted. addr=%s reason=%s",
                body.recipient, block_reason,
            )
            await _record_signing_denied(body, reason="aml_recipient_blocked")
            return SigningCheckResponse(
                allowed=False,
                reason="aml_recipient_blocked",
                details=block_reason,
            )

        blocked_sender, sender_reason = await is_blacklisted(body.wallet)
        if blocked_sender:
            logger.warning(
                "Signing rejected: sender blacklisted. addr=%s reason=%s",
                body.wallet, sender_reason,
            )
            await _record_signing_denied(body, reason="aml_sender_blocked")
            return SigningCheckResponse(
                allowed=False,
                reason="aml_sender_blocked",
                details=sender_reason,
            )

        # ── C2: derive the EUR value from the SIGNED amount (amount_in_wei),
        # NOT from any client-supplied fiat field. token_in == ZERO ⇒ native.
        _is_native = (body.token_in or ZERO_ADDRESS).lower() == ZERO_ADDRESS
        tok = get_token(body.chain_id, None if _is_native else body.token_in)
        if tok is None:
            # Unknown token ⇒ cannot value the transfer ⇒ fail-closed.
            await _record_signing_denied(body, reason="aml_amount_unavailable")
            return SigningCheckResponse(
                allowed=False,
                reason="aml_amount_unavailable",
                details="Unknown token — cannot value transfer for AML",
            )
        human = float(Decimal(amount) / (Decimal(10) ** tok.decimals))
        amount_eur = await get_eur_value(tok.coingecko_id, human)
        if amount_eur is None:
            # Price oracle unavailable ⇒ cannot value ⇒ fail-closed.
            await _record_signing_denied(body, reason="aml_amount_unavailable")
            return SigningCheckResponse(
                allowed=False,
                reason="aml_amount_unavailable",
                details="Price unavailable — cannot value transfer for AML",
            )

        aml_result = await full_aml_check(
            sender=body.wallet,
            recipient=body.recipient,
            amount_eur=amount_eur,
            chain_id=body.chain_id,
            tx_hash=None,
            token_symbol=tok.symbol,
        )

        # ── C2 hybrid AML gate ─────────────────────────────────
        # Block on: sanctions/screening (not approved); DAC8 KYC (requires_kyc,
        # monthly >€15k); or AML data unavailable (risk 'high' with NO threshold
        # alert ⇒ counters down ⇒ fail-closed). Sub-DAC8 thresholds
        # (daily/velocity/structuring) are ALERT-ONLY — already persisted by
        # monitor_transaction for SAR review — and do NOT block signing.
        block_reason = None
        if not aml_result.approved:
            block_reason = "aml_high_risk"            # sanctions / screening
        elif aml_result.requires_kyc:
            block_reason = "aml_kyc_required"         # DAC8 monthly >€15k
        elif aml_result.risk_level == "high" and not aml_result.alerts:
            block_reason = "aml_data_unavailable"     # AML counters down (fail-closed)

        if block_reason:
            logger.warning(
                "Signing rejected: %s. sender=%s recipient=%s alerts=%s",
                block_reason, body.wallet, body.recipient, aml_result.alerts,
            )
            await _record_signing_denied(body, reason=block_reason)
            return SigningCheckResponse(
                allowed=False,
                reason=block_reason,
                details=(
                    f"Alerts: {','.join(aml_result.alerts)}"
                    if aml_result.alerts else block_reason
                ),
            )

    except AMLBlockedError as e:
        await _record_signing_denied(body, reason="aml_blocked")
        return SigningCheckResponse(
            allowed=False,
            reason="aml_blocked",
            details=str(e),
        )
    except Exception as e:
        logger.error(
            "Signing rejected: AML screening failed (fail-closed). sender=%s err=%s",
            body.wallet, e,
        )
        await _record_signing_denied(body, reason="aml_screening_error")
        return SigningCheckResponse(
            allowed=False,
            reason="aml_screening_error",
            details="AML screening unavailable — retry later",
        )

    # ── 6. Rate limiting (Redis) ─────────────────────────
    from app.services.signing_rate_limit import check_signing_rate_limit

    from app.security.trusted_proxy import get_real_client_ip

    ip = body.ip_address or get_real_client_ip(request)

    allowed, reason = await check_signing_rate_limit(body.wallet, ip)
    if not allowed:
        return SigningCheckResponse(allowed=False, reason=reason)

    # ── 7. Nonce uniqueness (Redis) ──────────────────────
    from app.services.signing_rate_limit import check_nonce_uniqueness

    unique, nonce_reason = await check_nonce_uniqueness(body.nonce)
    if not unique:
        return SigningCheckResponse(allowed=False, reason=nonce_reason)

    return SigningCheckResponse(allowed=True)


# ═══════════════════════════════════════════════════════════════
#  POST /api/internal/signing/audit
# ═══════════════════════════════════════════════════════════════

@signing_router.post("/audit")
async def signing_audit(
    body: SigningAuditRequest,
    _internal: None = Depends(require_internal_secret),
):
    """Record a signing event to the immutable audit log.

    Called by the Next.js oracle AFTER signing decision (approved or denied).
    Non-blocking: audit failures don't affect the signing response.
    """
    from app.services.signing_audit import record_signing_event

    entry_id = await record_signing_event(
        signer_address=body.signer_address,
        chain_id=body.chain_id,
        sender=body.sender,
        recipient=body.recipient,
        token_in=body.token_in,
        amount_in_wei=body.amount_in_wei,
        nonce=body.nonce,
        deadline=body.deadline,
        approved=body.approved,
        denial_reason=body.denial_reason,
        risk_score=body.risk_score,
        risk_level=body.risk_level,
        ip_address=body.ip_address,
        user_agent=body.user_agent,
        correlation_id=body.correlation_id,
    )

    return {"recorded": entry_id is not None, "audit_id": entry_id}
