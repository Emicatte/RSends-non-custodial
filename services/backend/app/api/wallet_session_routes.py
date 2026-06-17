"""
Wallet-auth session bootstrap (H4).

POST /api/v1/auth/wallet-session
  Exchange a ONE-TIME EIP-191 signature for a short-lived HMAC session secret.
  The wallet signs `RSends:session:{nonce}:{timestamp}` once (one popup); the
  client then authenticates each subsequent request with a single-use HMAC
  (see app/security/auth.py session-HMAC path).
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["wallet-session"])


class WalletSessionRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=128)


class WalletSessionResponse(BaseModel):
    session_id: str
    session_secret: str
    expires_in: int


@router.post("/wallet-session", response_model=WalletSessionResponse)
async def create_session(body: WalletSessionRequest, request: Request):
    """Verify a one-time wallet signature and mint an HMAC session secret."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    from app.security.auth import _ETH_ADDR_RE, _check_timestamp_freshness
    from app.services.signing_rate_limit import check_nonce_uniqueness
    from app.services.wallet_session import SESSION_TTL, create_wallet_session

    address = request.headers.get("X-Wallet-Address", "").strip()
    signature = request.headers.get("X-Wallet-Signature", "").strip()
    timestamp = request.headers.get("X-Timestamp", "").strip()

    if not address or not _ETH_ADDR_RE.match(address):
        raise HTTPException(status_code=401, detail="invalid wallet address")
    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="missing signature/timestamp")
    if not _check_timestamp_freshness(timestamp):
        raise HTTPException(status_code=401, detail="timestamp expired")

    # Single-use bootstrap nonce (prevents replaying the session signature).
    unique, reason = await check_nonce_uniqueness(f"wsess:{body.nonce}")
    if not unique:
        raise HTTPException(status_code=401, detail=f"nonce: {reason}")

    message_text = f"RSends:session:{body.nonce}:{timestamp}"
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message_text), signature=signature
        )
    except Exception:
        raise HTTPException(status_code=401, detail="signature recovery failed")
    if recovered.lower() != address.lower():
        raise HTTPException(status_code=401, detail="signature mismatch")

    try:
        session_id, session_secret = await create_wallet_session(address)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="session store unavailable")

    return WalletSessionResponse(
        session_id=session_id,
        session_secret=session_secret,
        expires_in=SESSION_TTL,
    )
