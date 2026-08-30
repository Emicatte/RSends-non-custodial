"""Central chain classification + org chain-access guard.

Single source of truth for testnet chain ids (app.security.auth re-exports
from here for its wallet-debug bypass). Classification is fail-closed: any
chain id NOT in TESTNET_CHAIN_IDS is treated as mainnet.

Two tables, not one, because there are two kinds of chain. EVM chains classify
by id (`TESTNET_CHAIN_IDS`). Watch-only chains have no id in that namespace and
classify by name (`WATCH_ONLY_TESTNET_CHAINS`) — merging them would put a TRON
chain id in an EVM table, which the boot guard reads.

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
from typing import Optional

TESTNET_CHAIN_IDS = frozenset({84532, 11155111, 421614, 5, 80002})

# Watch-only (non-EVM) testnets, keyed by CHAIN NAME.
#
# `TESTNET_CHAIN_IDS` is an EVM table and cannot answer for these: a TRON chain
# id lives in a different namespace, and putting one in that frozenset would
# make `verify_chain_identity_for_boot` send `eth_chainId` to a TRON node and
# SystemExit the backend (see the HARD GUARDRAIL in tron_poller). Nor can the
# id be omitted and inferred — `is_testnet_chain(None)` is fail-closed to
# mainnet, correctly, which is how mainnet TRON classifies live.
#
# So testnet-ness for these chains is carried by the one identifier they do
# have. Must stay in sync with `intent_service._TESTNET_CHAINS`; pinned by
# test_tron_nile.py::test_the_two_testnet_tables_cannot_drift_apart.
WATCH_ONLY_TESTNET_CHAINS = frozenset({"tron_nile"})

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


def is_testnet_chain(chain_id: Optional[int]) -> bool:
    """Unknown ids classify as mainnet — deny by default.

    `None` is a legitimate input, not a caller bug: a watch-only chain has no
    EVM chain id and is mainnet, so it must classify as mainnet here.
    """
    return chain_id in TESTNET_CHAIN_IDS


def is_watch_only_testnet(chain_name: Optional[str]) -> bool:
    """Testnet-ness for a chain that has no id in the EVM namespace.

    The name is the only identifier such a chain has here, so it is what gets
    classified. Fail-closed on the same terms as `is_testnet_chain`: an unknown
    or absent name is mainnet, so forgetting to pass one can only ever make a
    caller stricter.
    """
    return (chain_name or "").lower() in WATCH_ONLY_TESTNET_CHAINS


def check_org_chain_access(
    onboarding_status: str,
    activation_status: str,
    chain_id: Optional[int],
    chain_name: Optional[str] = None,
) -> None:
    """Raise ChainAccessError unless the org may transact on this chain.

    `chain_name` is optional and defaults to None so every pre-existing caller
    keeps its exact behaviour: without it the chain is classified by id alone,
    which is fail-closed to mainnet. Callers that can supply the name — the two
    intent-creation paths — must, or a watch-only testnet is gated on business
    verification it has no business requiring.
    """
    if onboarding_status != "company_submitted":
        raise ChainAccessError(
            "company_profile_required",
            "complete company profile submission first",
        )
    is_testnet = is_testnet_chain(chain_id) or is_watch_only_testnet(chain_name)
    if not is_testnet and activation_status != "active":
        raise ChainAccessError(
            "mainnet_activation_required",
            "business verification required for mainnet chains",
        )
