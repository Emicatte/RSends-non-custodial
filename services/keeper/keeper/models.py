"""One unit of keeper work, exactly as the internal endpoint ships it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Wallet:
    """A source wallet the keeper should preflight.

    Mirrors `KeeperSourceWallet` in the backend
    (`app/models/source_wallet_schemas.py`). Four of these fields are NOT
    columns — `chain_id`, `token_address`, `token_decimals` and `auto_split` are
    resolved server-side from the registry and config, because the row
    deliberately never carries them. Receiving them resolved is what keeps the
    keeper from needing the registry, the config, and therefore the backend.

    Frozen: a work item is an observation of server state at one moment, not a
    scratchpad. Anything mutable belongs in Redis.
    """

    id: str
    org_id: str
    #: Registry chain NAME (`base_sepolia`), never an EVM id.
    chain: str
    chain_id: int
    address: str
    token_symbol: str
    token_address: str
    token_decimals: int
    auto_split: str
