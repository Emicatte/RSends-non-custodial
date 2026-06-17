"""
RSends Backend — Signing Audit Service.

Immutable append-only log for every oracle signature request.
Records are NEVER deleted — used for forensics, compliance audits,
and anomaly detection.

Usage from the Next.js oracle endpoint (via internal API):
    POST /api/internal/signing-audit
    {
        "signer_address": "0x...",
        "chain_id": 8453,
        "sender": "0x...",
        "recipient": "0x...",
        "token_in": "0x...",
        "amount_in_wei": "1000000000000000000",
        "nonce": "0xabc...",
        "deadline": 1713200000,
        "approved": true,
        "denial_reason": null,
        "risk_score": 5,
        "risk_level": "LOW",
        "ip_address": "1.2.3.4",
        "user_agent": "Mozilla/5.0 ...",
        "correlation_id": "uuid-here"
    }
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.db.session import async_session
from app.models.signing_models import SigningAuditLog

logger = logging.getLogger(__name__)


async def record_signing_event(
    *,
    signer_address: str,
    chain_id: int,
    sender: str,
    recipient: str,
    token_in: str,
    amount_in_wei: str,
    nonce: str,
    deadline: int,
    approved: bool,
    denial_reason: Optional[str] = None,
    risk_score: Optional[int] = None,
    risk_level: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Optional[int]:
    """Record an oracle signing event to the immutable audit log.

    Returns the audit log entry ID, or None if recording failed.
    Failures are logged but never raised — audit must not block signing.
    """
    try:
        entry = SigningAuditLog(
            created_at=datetime.now(timezone.utc),
            correlation_id=correlation_id,
            ip_address=ip_address,
            user_agent=user_agent,
            signer_address=signer_address.lower(),
            chain_id=chain_id,
            sender=sender.lower(),
            recipient=recipient.lower(),
            token_in=token_in.lower(),
            amount_in_wei=str(amount_in_wei),
            nonce=nonce,
            deadline=deadline,
            approved=approved,
            denial_reason=denial_reason,
            risk_score=risk_score,
            risk_level=risk_level,
        )

        async with async_session() as db:
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
            logger.info(
                "Signing audit recorded: id=%d chain=%d sender=%s approved=%s",
                entry.id, chain_id, sender[:10], approved,
                extra={"service": "signing_audit", "chain_id": chain_id},
            )
            return entry.id

    except Exception as e:
        logger.error(
            "Failed to record signing audit: %s", e,
            extra={"service": "signing_audit"},
        )
        return None
