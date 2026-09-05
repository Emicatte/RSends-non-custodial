"""Pydantic schemas for /api/v1/user/org/source-wallets (SIWE).

Addresses are validated and normalised in the family the CHAIN declares
(`chain_address_format`), never in the family the string appears to be: EVM
folds to lowercase, base58check is kept byte-identical. That dispatch is what
keeps the uniqueness index honest — 0024 dropped
`ck_source_wallets_address_lower` because SQL cannot verify a base58 checksum,
so these validators are now the ONLY thing standing between two spellings of
one wallet and two rows in the table. See `tests/test_source_wallets.py`, the
"case normalisation" section.

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

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def _validate_tron_address(value: str) -> str:
    """Reject-never-coerce base58check address, zero address refused.

    Deliberately NOT the EVM validator with a wider regex, and deliberately
    NOT followed by `.lower()`. base58 excludes `0 O I l`, so folding a
    T-address does not merely change it — it produces a string that cannot be
    decoded and whose checksum no longer verifies. Stripped, and otherwise
    byte-identical. Same rule and same wording as
    `org_schemas._validate_settlement_wallet_tron`.

    `is_tron_address` is THE base58check decoder in this codebase: it verifies
    the full double-SHA256 checksum rather than the shape, so a single mistyped
    character is caught. That matters here for the same reason it matters for a
    payout address — the keeper would be pointed at a wallet nobody holds.

    The TRON zero address has a VALID checksum, so `is_tron_address` accepts it
    and only this explicit comparison rejects it.
    """
    from app.security.input_validator import TRON_ZERO_ADDRESS, is_tron_address

    value = value.strip()
    if not is_tron_address(value):
        raise ValueError("address must be a valid TRON address")
    if value == TRON_ZERO_ADDRESS:
        raise ValueError("address cannot be the zero address")
    return value


def _normalize_address_for_chain(chain: str, address: str) -> str:
    """Validate + normalise `address` in the family `chain` declares.

    Dispatch is on the CHAIN, never on the string's shape. The registry already
    declares each chain's address family (`addressFormat`, read by
    `chain_address_format`) precisely so nothing downstream has to guess, and
    guessing is how an address ends up normalised by the wrong family's rule.

    A mismatch is refused rather than migrated to the other family: a wallet the
    keeper will move funds out of is not something to guess about. The error
    mirrors the payment path's `RECIPIENT_CHAIN_MISMATCH`
    (`intent_service.py`), which answers the same question for intent
    recipients.

    This is a MODEL validator, not a field validator, because the rule needs
    both fields and a per-field validator cannot see `chain`. It still rejects
    at parse, so the surface keeps its `extra="forbid"` posture: nothing
    unvalidated reaches a handler.
    """
    from app.services.router_registry import chain_address_format

    fmt = chain_address_format(chain)
    if fmt == "base58check":
        return _validate_tron_address(address)
    if fmt == "evm":
        return _validate_evm_address(address)
    # An unknown family means the registry grew one and this dispatch did not.
    # Fail closed: an unnormalised address reaching the uniqueness index is how
    # the same wallet gets registered twice.
    raise ValueError(f"chain {chain} declares an unsupported address format {fmt!r}")


def display_address_for_chain(chain: str, address: str) -> str:
    """The form of `address` to SHOW, given its chain's address family.

    EVM gets its EIP-55 checksum back — `address` is stored folded for the
    uniqueness index, so without this the merchant would be shown a lowercase
    string they cannot eyeball against their wallet. base58check is ALREADY
    the displayable form and is returned untouched: `to_checksum_address`
    would raise on it, and folding it would destroy it.

    Deliberately NOT `input_validator.display_payment_address`, despite the
    name. That one delegates to `normalize_payment_address`, so it LOWERCASES
    an EVM address — correct for the settlement surfaces it serves, which have
    no checksummed twin to preserve, but here it would silently collapse
    `display_address` onto `address` and quietly remove the twin this table
    keeps on purpose. Same address-family question, different answer; the two
    are not interchangeable.
    """
    from app.services.router_registry import chain_address_format

    if chain_address_format(chain) == "evm":
        from eth_utils import to_checksum_address

        return to_checksum_address(address)
    return address


class SourceWalletChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain: str = Field(min_length=1, max_length=32)
    token_symbol: str = Field(min_length=1, max_length=16)
    address: str

    @model_validator(mode="after")
    def _norm_address(self):
        self.address = _normalize_address_for_chain(self.chain, self.address)
        return self


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

    @model_validator(mode="after")
    def _norm_address(self):
        self.address = _normalize_address_for_chain(self.chain, self.address)
        return self


class SourceWalletResponse(BaseModel):
    """Explicit allowlist — never the ORM object, so a future column cannot
    leak into the session surface by default."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    # The registry chain NAME, not an EVM chain id — a watch-only chain has no
    # id to report, and inventing one is what makes a reader believe it is EVM.
    chain: str
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


class KeeperSourceWallet(BaseModel):
    """One unit of keeper work: everything the keeper cannot derive on its own.

    A separate model from `SourceWalletResponse` on purpose — different reader,
    different trust boundary, different fields. Three notes:

    • `org_id` IS present here and deliberately absent from the session model.
      This read is cross-tenant, so the org is the only way a log line can name
      whose wallet stalled.
    • `token_address`, `token_decimals` and `auto_split` are NOT columns. They
      are re-resolved from the registry and config at each use site, so the row
      never carries them; resolving them here is what keeps the keeper from
      needing the registry, the config, and therefore the backend.
    • No `disabled_at`: a disabled wallet is omitted from the list entirely,
      not shipped with a flag for the keeper to remember to check.
    """

    id: str
    org_id: str
    #: Registry chain NAME (`base_sepolia`), never an EVM id — see
    #: SourceWalletResponse.chain.
    chain: str
    #: The EVM id, resolved. Present because the keeper picks an RPC by it and
    #: must put it in the transaction; a watch-only chain has none, and such a
    #: wallet is omitted rather than sent with a null.
    chain_id: int
    address: str
    token_symbol: str
    token_address: str
    token_decimals: int
    auto_split: str


class KeeperSourceWalletList(BaseModel):
    wallets: List[KeeperSourceWallet]
