"""Central chain classification + org chain-access guard.

Single source of truth for testnet chain ids (app.security.auth re-exports
from here for its wallet-debug bypass). Classification is fail-closed: any
chain id NOT in TESTNET_CHAIN_IDS is treated as mainnet.

Access rule (staged onboarding):
- testnet chains require the org to be onboarded
  (onboarding_status == 'company_submitted');
- mainnet chains additionally require the org's business verification to be
  complete (activation_status == 'active'). No code path sets 'active' today
  (the external verification provider integration is a future task), so
  mainnet is uniformly denied — enforced and unit-tested here at the guard
  level since no mainnet chain is configured anywhere yet.
"""

# Testnet chain ids (Base Sepolia, Ethereum Sepolia, Arbitrum Sepolia,
# Goerli, Polygon Amoy). Moved verbatim from app/security/auth.py so there
# is exactly one definition.
TESTNET_CHAIN_IDS = frozenset({84532, 11155111, 421614, 5, 80002})

# Canonical chain-name -> chain-id map covering every name the payment API
# accepts (intent_service._TESTNET_CHAINS ∪ _MAINNET_CHAINS) — keep the two in
# sync so no accepted chain name bypasses the guard.
CHAIN_ID_BY_NAME: dict[str, int] = {
    "base": 8453,
    "base_sepolia": 84532,
    "sepolia": 11155111,
    "ethereum": 1,
    "eth": 1,
}


class ChainAccessError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def is_testnet_chain(chain_id: int) -> bool:
    """Unknown ids classify as mainnet — deny by default."""
    return chain_id in TESTNET_CHAIN_IDS


def check_org_chain_access(
    onboarding_status: str, activation_status: str, chain_id: int
) -> None:
    """Raise ChainAccessError unless the org may transact on this chain."""
    if onboarding_status != "company_submitted":
        raise ChainAccessError(
            "company_profile_required",
            "complete company profile submission first",
        )
    if not is_testnet_chain(chain_id) and activation_status != "active":
        raise ChainAccessError(
            "mainnet_activation_required",
            "business verification required for mainnet chains",
        )
