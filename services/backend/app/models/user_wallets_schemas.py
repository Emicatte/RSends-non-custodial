"""Pydantic schemas for /api/v1/user/wallets (SIWE EVM v1).

WalletVerifyRequest deliberately omits the SIWE message — the server stores
the canonical message in Redis at challenge time and re-uses that stored
copy for signature recovery. Clients can only submit {nonce, signature}
plus the (address, chain_id) context they are claiming; the server cross-
checks both against the Redis payload.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ChainFamily = Literal["evm"]


class WalletChallengeRequest(BaseModel):
    chain_family: ChainFamily = "evm"
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    chain_id: int = Field(ge=1)


class WalletChallengeResponse(BaseModel):
    siwe_message: str
    nonce: str
    expires_at: datetime


class WalletVerifyRequest(BaseModel):
    chain_family: ChainFamily = "evm"
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    chain_id: int = Field(ge=1)
    nonce: str = Field(min_length=8, max_length=64)
    signature: str = Field(pattern=r"^0x[a-fA-F0-9]+$", min_length=10, max_length=200)
    label: Optional[str] = Field(default=None, max_length=64)


class WalletPatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=64)
    is_primary: Optional[bool] = None


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chain_family: str
    address: str
    display_address: str
    chain_id: Optional[int]
    verified_chain_id: int
    label: str
    is_primary: bool
    verified_at: datetime
    last_activity_at: Optional[datetime]
    created_at: datetime
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: Optional[str] = None
    created_by_email: Optional[str] = None


class WalletListResponse(BaseModel):
    wallets: List[WalletResponse]
    max_allowed: int
    remaining_slots: int
