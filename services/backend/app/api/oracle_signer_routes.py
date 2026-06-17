"""
RSends Backend — Internal oracle digest signer (M1).

Signs a 32-byte EIP-712 digest with the DEDICATED oracle signer (KMS in prod —
the key never leaves the HSM, and never has to live in the Next.js web tier).
The Next oracle computes the EIP-712 digest (viem hashTypedData) and delegates
signing here instead of holding ORACLE_PRIVATE_KEY in-process.

Internal-only:
  - Gated by X-Internal-Secret (reuses the H3 dependency) — only the server-side
    oracle can reach it.
  - Exempt from API-key auth; the Next catch-all proxy already denylists
    `api/internal/*`, so it is unreachable from the browser.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.signing_routes import require_internal_secret

logger = logging.getLogger(__name__)

oracle_signer_router = APIRouter(prefix="/api/internal/oracle", tags=["oracle-signer"])


class SignDigestRequest(BaseModel):
    digest: str = Field(..., description="0x-prefixed 32-byte EIP-712 digest")


class SignDigestResponse(BaseModel):
    # Primary (signatures[0]) — single-signer V4 back-compat.
    signature: str       # 0x{r}{s}{v}, v ∈ {27,28}
    signer_address: str  # Ethereum address of the primary oracle signer
    # Full set, ASCENDING by signer address — the order V5/V6 threshold verify
    # requires for `bytes[] oracleSignatures`.
    signatures: list[str]
    signer_addresses: list[str]


def _assemble(v: int, r: int, s: int) -> str:
    if v < 27:
        v += 27
    return "0x" + r.to_bytes(32, "big").hex() + s.to_bytes(32, "big").hex() + bytes([v]).hex()


@oracle_signer_router.post("/sign-digest", response_model=SignDigestResponse)
async def sign_digest(
    body: SignDigestRequest,
    _internal: None = Depends(require_internal_secret),
) -> SignDigestResponse:
    """Sign a 32-byte EIP-712 digest with the dedicated oracle signer set.

    Signs with every configured oracle signer and returns the signatures sorted
    ascending by signer address (V5/V6 multisig). For a single signer the set
    has one element and ``signature`` == ``signatures[0]`` (V4).
    """
    raw_hex = body.digest[2:] if body.digest.startswith("0x") else body.digest
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError:
        raise HTTPException(status_code=422, detail="digest must be hex")
    if len(raw) != 32:
        raise HTTPException(status_code=422, detail="digest must be 32 bytes")

    from app.services.key_manager import SignerError, get_oracle_signers

    try:
        signers = get_oracle_signers()
        pairs: list[tuple[str, str]] = []  # (address, signature)
        for signer in signers:
            v, r, s = await signer.sign_hash(raw)
            address = await signer.get_address()
            pairs.append((address, _assemble(v, r, s)))
    except SignerError as e:
        logger.error("oracle sign-digest: signer not available: %s", e)
        raise HTTPException(status_code=503, detail="oracle signer unavailable")

    # V5/V6 verify expects ascending signer order.
    pairs.sort(key=lambda p: int(p[0], 16))
    signer_addresses = [a for a, _ in pairs]
    signatures = [sig for _, sig in pairs]

    return SignDigestResponse(
        signature=signatures[0],
        signer_address=signer_addresses[0],
        signatures=signatures,
        signer_addresses=signer_addresses,
    )
