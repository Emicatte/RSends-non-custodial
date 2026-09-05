"""The only module in the repository that signs a fund-moving transaction.

Everything about the key's authority is decided by two facts, and neither is in
this file's control:

  • `executeSplit(merchant, token)` takes no destination and no amount. It
    distributes `min(balance, allowance)` according to the policy the MERCHANT
    published with their own key. A compromised keeper key can therefore trigger
    a merchant's own policy, or waste gas — it cannot choose a recipient, an
    amount, or a token that is not already registered.
  • `abi.py` declares no state-changing method but `executeSplit`, so there is
    no second thing this account could be made to send without an ABI change
    that `tests/test_abi.py` would fail.

`services/backend/tests/test_no_custodial_surface.py` pins both, and pins that
`Account.from_key` appears in exactly one keeper module — this one.

Shape follows `services/backend/scripts/sepolia_smoke.py`, the only
build/sign/send/wait already in the repo. Note what it does that matters:
`wait_for_transaction_receipt` with an explicit timeout, and an explicit
`status` check. A returned transaction hash is not success.
"""

import logging

from eth_account import Account
from web3 import Web3

from keeper.abi import AUTO_SPLIT_ABI

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, w3: Web3, private_key: str, *, receipt_timeout: int = 180):
        self._w3 = w3
        # The one key-loading site in the keeper.
        self._account = Account.from_key(private_key)
        self._receipt_timeout = receipt_timeout

    @property
    def address(self) -> str:
        """The gas account's address. Safe to log — and the ONLY thing about
        this account that ever is."""
        return self._account.address

    def execute_split(self, wallet):
        """Send one `executeSplit` and wait for its receipt.

        Returns the receipt (whose `status` the caller MUST check — a mined
        revert is a receipt too). Raises on anything that stops us getting one.
        """
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(wallet.auto_split), abi=AUTO_SPLIT_ABI
        )
        fn = contract.functions.executeSplit(
            Web3.to_checksum_address(wallet.address),
            Web3.to_checksum_address(wallet.token_address),
        )

        tx = fn.build_transaction(
            {
                "from": self._account.address,
                "nonce": self._w3.eth.get_transaction_count(self._account.address),
                "chainId": wallet.chain_id,
            }
        )
        signed = self._account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)

        log.info(
            "keeper: sent executeSplit wallet=%s org=%s tx=%s",
            wallet.id,
            wallet.org_id,
            tx_hash.hex(),
        )
        return self._w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=self._receipt_timeout
        )
