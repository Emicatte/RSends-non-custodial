"""Chain identity for DISPLAY surfaces — assembled from existing sources.

The dashboard used to answer "which chain is this settlement on?" with a display
label and nothing else: a four-entry dict mapping chain id → "Base" / "Base
Sepolia" / "Ethereum" / "Arbitrum", falling back to `chain:{id}`. One string was
serving as both the lookup key and the user-facing text, and that is how the
frontend ended up keying its badge map on LABELS while `explorer.ts` keyed on
snake NAMES — two vocabularies over the same row, with nothing able to notice
they disagreed. TRON, whose label was `chain:3448148188`, matched neither, and a
whitelist coercion turned it into "Base".

So display surfaces get a `chain_key`: snake, machine-stable, the vocabulary
`explorer.ts` and `createChains.ts` already speak.

WHY THIS IS ASSEMBLED AND NOT TYPED OUT
---------------------------------------
A fourth hand-maintained chain table is how the first three drifted. Every value
here already exists somewhere that owns it:

  * `router_registry.CHAIN_IDS`         — coverage. Every chain name the payment
                                          API accepts, including "arbitrum",
                                          which `_CHAIN_NAME_BY_ID` omits.
  * `router_registry._CHAIN_NAME_BY_ID` — the authority on the canonical name
                                          when a chain id has several. It is
                                          what resolves the "eth"/"ethereum"
                                          alias, and it wins wherever it speaks.
  * `tron_poller.TRON_NETWORKS`         — the canonical (chain_id, chain_name)
                                          pairs for the TRON networks. They are
                                          deliberately absent from every EVM
                                          table and must stay that way.

This module READS all three and writes to none of them.

WHY NOT JUST ADD 42161 TO `_CHAIN_NAME_BY_ID`
---------------------------------------------
Because that dict is on the money path, and the one-line "fix" is a money-path
change wearing a display change's clothes. Adding it would flip
`_canonical_chain("arbitrum")` from None to "arbitrum", which flips
`chain_is_supported("arbitrum")` to True, which lets "arbitrum" past the
`UNSUPPORTED_CHAIN` gate in `intent_service.create_intent` — and "arbitrum" is
in neither `_TESTNET_CHAINS` nor `_MAINNET_CHAINS`, so per the warning at
`intent_service.py:351-353` it would then pass BOTH environment branches
silently and become creatable on test AND live keys, against a chain with no
tokens in `token_registry.json` and no deployed router.

Arbitrum has a display key here and no settlement path there. Both are true at
once, deliberately. Pinned by
`test_chain_display_identity.py::test_building_the_display_map_does_not_make_arbitrum_creatable`.

NO DEFAULT CHAIN
----------------
`chain_key_for` never guesses. A chain id the assembly does not know returns
`chain:{id}` — the raw reference, which is honest and which the frontend renders
verbatim in a neutral badge with no explorer link. Falling back to a SUPPORTED
chain is the original defect; there is no branch here that can do it.
"""

from __future__ import annotations

from app.services.router_registry import CHAIN_IDS, _CHAIN_NAME_BY_ID
from app.services.tron_poller import TRON_NETWORKS


def build_chain_key_by_id() -> dict[int, str]:
    """Assemble chain id → canonical snake chain name.

    Order matters and each step is doing separate work:

    1. Invert `CHAIN_IDS` for COVERAGE. It is many-to-one ("eth" and "ethereum"
       both → 1), so the inversion alone is not well-defined; names are sorted
       so that whatever it produces for an unresolved collision is at least the
       same on every run and every interpreter, rather than dict-order luck.
    2. Overlay `_CHAIN_NAME_BY_ID` for AUTHORITY. Where it has an opinion it
       wins, which is what actually resolves "eth" → "ethereum" rather than
       leaving it to step 1's alphabetical tie-break.
    3. Union `TRON_NETWORKS`, which is where TRON's two (chain_id, chain_name)
       pairs are defined and the only place they should be read from.

    Returns a fresh dict; the module-level `CHAIN_KEY_BY_ID` is the shared one.
    """
    assembled: dict[int, str] = {}

    for name in sorted(CHAIN_IDS):
        assembled.setdefault(CHAIN_IDS[name], name)

    assembled.update(_CHAIN_NAME_BY_ID)

    for network in TRON_NETWORKS:
        assembled[network.chain_id] = network.chain_name

    return assembled


CHAIN_KEY_BY_ID: dict[int, str] = build_chain_key_by_id()


def chain_key_for(chain_id: int) -> str:
    """The machine-stable chain key for `chain_id`.

    An unknown id returns `chain:{id}` — the honest raw reference. There is
    deliberately no default: answering "base" for a chain we could not identify
    is the defect this module was written to remove.

    Takes `int`, not `Optional[int]`. The caller's column
    (`PaymentSettlement.chain_id`) is `nullable=False`, so the `None` arm of the
    function this replaces was unreachable — and what it did in that arm was
    `return "Base"`, a default chain that only survived because nothing could
    reach it.
    """
    return CHAIN_KEY_BY_ID.get(int(chain_id), f"chain:{int(chain_id)}")


# There is deliberately NO display-label map here.
#
# One lived in this module briefly, holding `RecentTransaction.chain` steady
# while the frontend moved onto `chain_key`. It is gone with its last reader:
# a backend-side label would be a second source of truth for text the client
# already derives from the key, free to drift from the client's own labels with
# nothing able to notice — which is the exact shape of the bug this module was
# written to remove, one layer up.
