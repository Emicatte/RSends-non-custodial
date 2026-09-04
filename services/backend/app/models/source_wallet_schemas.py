"""Pydantic schemas for /api/v1/user/org/source-wallets (SIWE, EVM-only).

Two properties of these models are load-bearing rather than stylistic.

`extra="forbid"`. The client names a token by (chain, symbol) and NEVER by
contract address: `token_address` — or any other unknown key — is rejected at
parse, before a single validator body runs. RSendsAutoSplit accepts any ERC-20
and cannot defend itself (a fee-on-transfer or rebasing token breaks its
empty-to-zero invariant), so its header delegates enforcement to the backend and
the UI explicitly. This is the API half of that obligation: the token address is
resolved server-side from `token_registry.json` and can never be steered from
outside. Note this deliberately diverges from the integrator-facing API, which
must TOLERATE unknown keys — safe here because this is a first-party session
surface, outside the frozen integration contract.

The verify request omits the SIWE message, exactly like the wallet-linking
schemas: the server stores the canonical message in Redis at challenge time and
re-uses that copy for signature recovery, so a client can only submit
{nonce, signature} plus the context it claims. It also omits `chain_id` — that
is derived server-side from `chain`, so the SIWE binding cannot be pointed at a
different network than the registration.
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_evm_address(value: str) -> str:
    """Reject-never-coerce EVM address, zero address refused.

    A zero source wallet is not merely useless: the keeper would be pointed at
    an address nobody can hold a key to, and the registration would occupy the
    global uniqueness slot forever. Same rule, same reasoning as the org
    settlement wallet.

    Returned lowercase — matching is case-insensitive on chain, and the
    lowercase form is what the uniqueness index sees. The EIP-55 checksum for
    display is derived from it server-side.
    """
    value = value.strip()
    if not _EVM_ADDR_RE.match(value):
        raise ValueError("address must be a valid EVM address")
    if int(value, 16) == 0:
        raise ValueError("address cannot be the zero address")
    return value.lower()


class SourceWalletChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str = Field(min_length=1, max_length=32)
    token_symbol: str = Field(min_length=1, max_length=16)
    address: str

    _norm_address = field_validator("address")(_validate_evm_address)


class SourceWalletChallengeResponse(BaseModel):
    siwe_message: str
    nonce: str
    expires_at: datetime


class SourceWalletVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str = Field(min_length=1, max_length=32)
    token_symbol: str = Field(min_length=1, max_length=16)
    address: str
    nonce: str = Field(min_length=8, max_length=64)
    signature: str = Field(pattern=r"^0x[a-fA-F0-9]+$", min_length=10, max_length=200)
    label: Optional[str] = Field(default=None, max_length=64)

    _norm_address = field_validator("address")(_validate_evm_address)


class SourceWalletResponse(BaseModel):
    """Explicit allowlist — never the ORM object, so a future column cannot
    leak into the session surface by default."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    chain_id: int
    environment: str
    address: str
    display_address: str
    token_symbol: str
    label: str
    disabled_at: Optional[datetime] = None
    created_at: datetime


class SourceWalletListResponse(BaseModel):
    source_wallets: List[SourceWalletResponse]
    max_allowed: int
    remaining_slots: int
