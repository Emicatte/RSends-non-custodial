"""
RSends Backend — RSendsRouter on-chain registry & calldata builder (non-custodial).

The create-intent endpoint no longer generates a custodial deposit address.
Instead it returns everything the payer's own wallet needs to call the
RSendsRouter contract directly:

  - the per-chain RSendsRouter address
  - the ERC20 token address (or 0x0 for native ETH)
  - the chainId
  - the on-chain invoiceId (bytes32) derived from the intent reference
  - the amount in base units
  - ready-to-send calldata for pay()/payNative()

Router addresses come from settings.rsends_router_addresses ({chain_id: addr}).

TOKEN POLICY / REGISTRY — SINGLE SOURCE OF TRUTH:
  The per-chain token policy (address, decimals, flat fee config, enabled) lives
  in `app/token_registry.json`. That same file is consumed by the Foundry config
  script (packages/contracts/script/SetFeeConfig.s.sol), so contract config and
  backend cannot drift. Do NOT hardcode token addresses here — edit the JSON.
  Override the path in tests via the TOKEN_REGISTRY_PATH env var.
"""

import asyncio
import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

ZERO_ADDRESS = "0x" + "0" * 40

# chain name (as used in the merchant API) → EVM chain id
CHAIN_IDS = {
    "base": 8453,
    "base_sepolia": 84532,
    "ethereum": 1,
    "eth": 1,
    "arbitrum": 42161,
    "optimism": 10,
    "polygon": 137,
    "sepolia": 11155111,
}

# chain id → canonical chain name (first match in CHAIN_IDS wins; "eth" aliases 1)
_CHAIN_NAME_BY_ID = {8453: "base", 84532: "base_sepolia", 1: "ethereum"}

# chain id → legacy "network" name (the vocabulary carried by the merchant
# webhook payloads and PaymentIntent.network). Single source of truth — the copy
# in webhook_service.CHAIN_NETWORK_MAP is for tx matching only.
_NETWORK_NAME_BY_ID = {
    8453: "BASE_MAINNET", 84532: "BASE_SEPOLIA",
    1: "ETH_MAINNET", 42161: "ARBITRUM_MAINNET",
}


class UnsupportedTokenError(ValueError):
    """Raised when a (chain, currency) pair is not in the registry or not enabled."""

    def __init__(self, chain: str, currency: str):
        self.chain = chain
        self.currency = currency
        super().__init__(f"token {currency!r} is not enabled on chain {chain!r}")


def _registry_path() -> Path:
    override = os.environ.get("TOKEN_REGISTRY_PATH")
    if override:
        return Path(override)
    # app/services/router_registry.py → parents[1] == app/
    return Path(__file__).resolve().parents[1] / "token_registry.json"


def _load_registry() -> tuple[dict, dict, dict]:
    """Load token_registry.json → (TOKEN_REGISTRY, FEE_POLICY, CHAIN_META).

    TOKEN_REGISTRY: { chain_name → { SYMBOL → (address, decimals) } }
    FEE_POLICY:     { chain_name → { SYMBOL → {flatFee, threshold, aboveFee, enabled, verified, native, address, decimals} } }
    CHAIN_META:     { chain_name → {addressFormat, settlement} }
    """
    raw = json.loads(_registry_path().read_text())
    tokens: dict = {}
    policy: dict = {}
    meta: dict = {}
    for chain_id_str, chain_obj in raw.items():
        # Keys are chain identifiers; "_"-prefixed keys are file metadata
        # ("_comment"). NOT an isdigit() test: a non-EVM chain has no EVM chain
        # id, and keying it by a synthetic number is exactly how a reader comes
        # to believe it is an EVM chain. Such a chain keys by its name instead.
        if chain_id_str.startswith("_"):
            continue
        name = (
            chain_obj.get("name")
            or (_CHAIN_NAME_BY_ID.get(int(chain_id_str)) if chain_id_str.isdigit() else None)
            or chain_id_str
        ).lower()
        tokens[name] = {}
        policy[name] = {}
        meta[name] = {
            # EVM is the default; a non-EVM chain declares its address family so
            # nothing downstream has to infer it from the string's shape.
            "addressFormat": chain_obj.get("addressFormat", "evm"),
            # "router" (payer pays a contract) vs "watch_only" (payer pays the
            # merchant directly and the indexer observes it).
            "settlement": chain_obj.get("settlement", "router"),
        }
        for sym, t in chain_obj.get("tokens", {}).items():
            sym = sym.upper()
            raw_addr = t["address"] or ZERO_ADDRESS
            # EVM addresses are case-insensitive → fold. Base58check addresses
            # are case-SENSITIVE → folding one destroys it.
            addr = raw_addr.lower() if raw_addr.startswith("0x") else raw_addr
            tokens[name][sym] = (addr, int(t["decimals"]))
            policy[name][sym] = {
                "address": addr,
                "decimals": int(t["decimals"]),
                "native": bool(t.get("native", False)),
                "permitType": t.get("permitType", "none"),
                "permitVersion": t.get("permitVersion"),
                "assetType": t.get("assetType"),
                "issuer": t.get("issuer"),
                "reason": t.get("reason"),
                # Fee keys are OPTIONAL (default 0): they configure the v1
                # RSendsRouter only — chains served by the fee-less
                # RSendsRouterV2 ignore them and may omit them entirely.
                "flatFee": int(t.get("flatFee", 0)),
                "threshold": int(t.get("threshold", 0)),
                "aboveFee": int(t.get("aboveFee", 0)),
                "enabled": bool(t["enabled"]),
                "verified": bool(t.get("verified", False)),
            }
    return tokens, policy, meta


# chain name → { SYMBOL: (address, decimals) }. address == ZERO_ADDRESS → native.
# chain name → { SYMBOL: {fee policy} }. Both built from app/token_registry.json.
# chain name → { addressFormat, settlement }.
TOKEN_REGISTRY, FEE_POLICY, CHAIN_META = _load_registry()


def _keccak(data: bytes) -> bytes:
    from eth_utils import keccak  # provided by eth-utils in requirements

    return keccak(data)


def chain_id_for(chain: str) -> Optional[int]:
    return CHAIN_IDS.get((chain or "").lower())


def primary_chain_id() -> int:
    """Chain id representing the system's current network, derived from the
    configured RSendsRouter maps (the same source the indexer builds watchers
    from — union of v1 and v2, v1 first for stability). First configured
    chain, else Base Sepolia (84532) — the testnet we run on — when
    unconfigured (local/dev/test)."""
    settings = get_settings()
    routers = getattr(settings, "rsends_router_addresses", {}) or {}
    routers_v2 = getattr(settings, "rsends_router_v2_addresses", {}) or {}
    for k in list(routers) + list(routers_v2):
        try:
            return int(k)
        except (TypeError, ValueError):
            continue
    return 84532


def chain_name_for_id(chain_id: int) -> str:
    """Canonical chain name for a chain id (84532 -> 'base_sepolia'); falls back
    to the stringified id for unknown chains."""
    return _CHAIN_NAME_BY_ID.get(chain_id, str(chain_id))


def network_name_for_chain_id(chain_id: int) -> Optional[str]:
    """Legacy 'network' name for a chain id (84532 -> 'BASE_SEPOLIA'), or None
    when the chain has no mapping (don't invent one)."""
    return _NETWORK_NAME_BY_ID.get(chain_id)


def router_address_for(chain: str) -> Optional[str]:
    """RSendsRouter address for the chain, from settings.rsends_router_addresses."""
    cid = chain_id_for(chain)
    if cid is None:
        return None
    routers = getattr(get_settings(), "rsends_router_addresses", {}) or {}
    return routers.get(str(cid)) or routers.get(cid)


def router_v2_address_for(chain: str) -> Optional[str]:
    """RSendsRouterV2 address for the chain (settings.rsends_router_v2_addresses).

    v2 is the fee-less, ownerless router: a chain in this map creates v2
    intents (v2 wins over v1 when both are configured; the indexer watches
    both, so in-flight v1 payments still settle).
    """
    cid = chain_id_for(chain)
    if cid is None:
        return None
    routers = getattr(get_settings(), "rsends_router_v2_addresses", {}) or {}
    return routers.get(str(cid)) or routers.get(cid)


def chain_has_settlement_router(chain: str) -> bool:
    """True iff the chain has a configured RSendsRouter (v1 or v2).

    The address resolvers return None both for "chain unknown" and for "chain
    known but not configured", and `build_onchain_payment` turns that None into
    a null `onchain` block on an otherwise-successful 201 — an intent nobody can
    pay and no indexer watches. Callers on the money path use this predicate to
    fail closed instead; the registry itself stays free of HTTP concerns.

    Deliberately NOT the same question as `chain_is_supported`, which only asks
    whether the chain canonicalizes into the token registry.
    """
    return (
        router_address_for(chain) is not None
        or router_v2_address_for(chain) is not None
    )


def is_watch_only_chain(chain: str) -> bool:
    """True iff the chain settles WITHOUT a router: the payer sends the token
    straight to the merchant's own address and the indexer observes it.

    Read from the registry's explicit `settlement` field, never inferred from a
    missing chain id or a missing router address. Inference would fail OPEN — an
    EVM chain accidentally absent from CHAIN_IDS would silently stop requiring a
    router, which is exactly the silent-failure mode `chain_has_settlement_router`
    exists to prevent.
    """
    name = _canonical_chain(chain)
    if name is None:
        return False
    return CHAIN_META.get(name, {}).get("settlement") == "watch_only"


def chain_address_format(chain: str) -> str:
    """Address family for a chain: "evm" (default) or e.g. "base58check"."""
    name = _canonical_chain(chain)
    if name is None:
        return "evm"
    return CHAIN_META.get(name, {}).get("addressFormat", "evm")


def split_router_address_for(chain: str) -> Optional[str]:
    """RSendsSplitRouter address for the chain (settings.split_router_addresses).

    None ⇒ splits are NOT enabled on this chain — intent creation fail-closes
    (422 SPLIT_UNAVAILABLE) and build_onchain_payment returns no instructions.
    """
    cid = chain_id_for(chain)
    if cid is None:
        return None
    routers = getattr(get_settings(), "split_router_addresses", {}) or {}
    return routers.get(str(cid)) or routers.get(cid)


def _canonical_chain(chain: str) -> Optional[str]:
    """Normalize a chain name to the registry key (resolves aliases like 'eth'→'ethereum')."""
    name = (chain or "").lower()
    if name in TOKEN_REGISTRY:
        return name
    cid = CHAIN_IDS.get(name)
    return _CHAIN_NAME_BY_ID.get(cid) if cid is not None else None


def token_for(chain: str, currency: str) -> Optional[tuple[str, int]]:
    """Return (token_address, decimals) for (chain, currency), or None."""
    name = _canonical_chain(chain)
    if name is None:
        return None
    return TOKEN_REGISTRY.get(name, {}).get((currency or "").upper())


def fee_policy_for(chain: str, currency: str) -> Optional[dict]:
    """Return the full fee-policy dict for (chain, currency), or None if absent."""
    name = _canonical_chain(chain)
    if name is None:
        return None
    return FEE_POLICY.get(name, {}).get((currency or "").upper())


def chain_is_supported(chain: str) -> bool:
    """True iff the chain canonicalizes into the token registry — i.e. the
    system has any settlement path for it at all (tokens, router, indexer)."""
    return _canonical_chain(chain) is not None


def token_is_enabled(chain: str, currency: str) -> bool:
    """True iff (chain, currency) is in the registry AND policy enabled is true."""
    pol = fee_policy_for(chain, currency)
    return bool(pol and pol["enabled"])


def assert_token_enabled(chain: str, currency: str) -> None:
    """Raise UnsupportedTokenError unless (chain, currency) is registered and enabled."""
    if not token_is_enabled(chain, currency):
        raise UnsupportedTokenError(chain, currency)


def chain_names_for_id(chain_id: int) -> list[str]:
    """All chain names (lowercase, aliases included) mapping to `chain_id` —
    the indexer's SQL scope for matching an event's chain against the
    merchant-provided PaymentIntent.chain string."""
    return [name for name, cid in CHAIN_IDS.items() if cid == chain_id]


def derive_invoice_id(reference_id: str, chain_id: int) -> str:
    """Deterministic bytes32 invoiceId: keccak256(f"{chain_id}:{reference_id}").

    The payer passes this to RSendsRouter; the indexer matches the emitted
    PaymentMade.invoiceId back to this intent via onchain_invoice_id (scoped
    by chain + environment). Folding the chain id makes the id unique per
    chain — the same reference paid on another chain derives a different id,
    so a cross-chain replay is an orphan even before the SQL scoping (F-3).
    Existing intents keep their STORED onchain_invoice_id (stamped at create;
    migration 0015 backfilled pre-fix-A NULL rows with the legacy
    keccak(reference_id) formula) — this derivation applies to new intents.
    """
    return "0x" + _keccak(f"{chain_id}:{reference_id}".encode("utf-8")).hex()


def to_base_units(amount: float, decimals: int) -> int:
    return int((Decimal(str(amount)) * (Decimal(10) ** decimals)).to_integral_value())


def _selector(signature: str) -> bytes:
    return _keccak(signature.encode("utf-8"))[:4]


def _enc_uint(value: int) -> str:
    return f"{value & ((1 << 256) - 1):064x}"


def _enc_addr(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def _enc_bytes32(hexstr: str) -> str:
    return hexstr.lower().replace("0x", "").rjust(64, "0")


def build_pay_calldata(
    invoice_id: str, merchant: str, token: str, amount_base_units: int, max_fee: int
) -> str:
    """calldata for pay(bytes32 invoiceId, address merchant, address token, uint256 amount, uint256 maxFee)."""
    sel = _selector("pay(bytes32,address,address,uint256,uint256)").hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_addr(token)
        + _enc_uint(amount_base_units)
        + _enc_uint(max_fee)
    )


def build_pay_native_calldata(
    invoice_id: str, merchant: str, amount_base_units: int, max_fee: int
) -> str:
    """calldata for payNative(bytes32 invoiceId, address merchant, uint256 amount, uint256 maxFee) — value = amount + fee."""
    sel = _selector("payNative(bytes32,address,uint256,uint256)").hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_uint(amount_base_units)
        + _enc_uint(max_fee)
    )


def build_pay_with_permit_calldata(
    invoice_id: str, merchant: str, token: str, amount_base_units: int, max_fee: int
) -> str:
    """TEMPLATE calldata for payWithPermit(...). The EIP-2612 permit fields
    (deadline, v, r, s) are signed by the payer's wallet and are ZEROED here —
    they MUST be filled in client-side after signing. The frontend builds the
    final tx via the contract ABI; this template is for completeness / non-wagmi
    clients. A zero deadline makes the inner permit revert → caught → falls back
    to a pre-existing approve()."""
    sel = _selector(
        "payWithPermit(bytes32,address,address,uint256,uint256,uint256,uint8,bytes32,bytes32)"
    ).hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_addr(token)
        + _enc_uint(amount_base_units)
        + _enc_uint(max_fee)
        + _enc_uint(0)  # deadline   — client fills
        + _enc_uint(0)  # v          — client fills
        + _enc_uint(0)  # r (bytes32)— client fills
        + _enc_uint(0)  # s (bytes32)— client fills
    )


def build_pay_calldata_v2(
    invoice_id: str, merchant: str, token: str, amount_base_units: int
) -> str:
    """calldata for RSendsRouterV2.pay(bytes32 invoiceId, address merchant, address token, uint256 amount) — no fee, no maxFee."""
    sel = _selector("pay(bytes32,address,address,uint256)").hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_addr(token)
        + _enc_uint(amount_base_units)
    )


def build_pay_native_calldata_v2(
    invoice_id: str, merchant: str, amount_base_units: int
) -> str:
    """calldata for RSendsRouterV2.payNative(bytes32 invoiceId, address merchant, uint256 amount) — value = exactly amount."""
    sel = _selector("payNative(bytes32,address,uint256)").hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_uint(amount_base_units)
    )


def build_pay_with_permit_calldata_v2(
    invoice_id: str, merchant: str, token: str, amount_base_units: int
) -> str:
    """TEMPLATE calldata for RSendsRouterV2.payWithPermit(...) — permit value is
    exactly `amount` (no fee term); deadline/v/r/s zeroed, client fills after
    signing (same convention as the v1 template)."""
    sel = _selector(
        "payWithPermit(bytes32,address,address,uint256,uint256,uint8,bytes32,bytes32)"
    ).hex()
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(merchant)
        + _enc_addr(token)
        + _enc_uint(amount_base_units)
        + _enc_uint(0)  # deadline   — client fills
        + _enc_uint(0)  # v          — client fills
        + _enc_uint(0)  # r (bytes32)— client fills
        + _enc_uint(0)  # s (bytes32)— client fills
    )


def loaded_split_recipients(intent) -> list:
    """The intent's split legs WITHOUT ever triggering an async lazy-load
    (which would raise MissingGreenlet outside a greenlet context).

    Query-loaded intents always have the relationship populated (lazy=selectin
    fires at query time); an UNLOADED relationship only occurs on manually
    constructed instances (tests/harnesses), which by construction have no
    legs — treat as empty rather than guessing with IO."""
    try:
        from sqlalchemy import inspect as _sa_inspect

        if "split_recipients" in _sa_inspect(intent).unloaded:
            return []
    except Exception:  # not an ORM instance (plain stub) — fall through
        pass
    return getattr(intent, "split_recipients", None) or []


def build_pay_split_calldata(
    invoice_id: str,
    token: str,
    total_base_units: int,
    recipients: list[str],
    shares_bps: list[int],
) -> str:
    """calldata for paySplit(bytes32 invoiceId, address token, uint256 totalAmount,
    address[] recipients, uint16[] sharesBps) — two dynamic tails after a 5-word head."""
    sel = _selector("paySplit(bytes32,address,uint256,address[],uint16[])").hex()
    n = len(recipients)
    offset_recipients = 5 * 32
    offset_shares = offset_recipients + 32 * (1 + n)
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_addr(token)
        + _enc_uint(total_base_units)
        + _enc_uint(offset_recipients)
        + _enc_uint(offset_shares)
        + _enc_uint(n)
        + "".join(_enc_addr(a) for a in recipients)
        + _enc_uint(n)
        + "".join(_enc_uint(b) for b in shares_bps)
    )


def build_pay_split_native_calldata(
    invoice_id: str,
    total_base_units: int,
    recipients: list[str],
    shares_bps: list[int],
) -> str:
    """calldata for paySplitNative(bytes32 invoiceId, uint256 totalAmount,
    address[] recipients, uint16[] sharesBps) — value must equal totalAmount."""
    sel = _selector("paySplitNative(bytes32,uint256,address[],uint16[])").hex()
    n = len(recipients)
    offset_recipients = 4 * 32
    offset_shares = offset_recipients + 32 * (1 + n)
    return (
        "0x"
        + sel
        + _enc_bytes32(invoice_id)
        + _enc_uint(total_base_units)
        + _enc_uint(offset_recipients)
        + _enc_uint(offset_shares)
        + _enc_uint(n)
        + "".join(_enc_addr(a) for a in recipients)
        + _enc_uint(n)
        + "".join(_enc_uint(b) for b in shares_bps)
    )


async def quote_fee_onchain(
    chain_id: int, router: str, token: str, amount_base_units: int
) -> Optional[int]:
    """Live RSendsRouter.quoteFee(token, amount) via eth_call — the single source
    of truth for the fee. Returns the fee in base units, or None if the call fails
    (router not deployed / RPC down) so callers can degrade gracefully."""
    from app.services.rpc_manager import get_rpc_manager

    sel = _selector("quoteFee(address,uint256)").hex()
    data = "0x" + sel + _enc_addr(token) + _enc_uint(amount_base_units)
    try:
        rpc = get_rpc_manager(chain_id)
        result = await rpc.call("eth_call", [{"to": router, "data": data}, "latest"])
        if not result or result == "0x":
            return None
        return int(result, 16)
    except Exception as exc:  # pragma: no cover — network/RPC failure path
        logger.warning(
            "quoteFee eth_call failed (chain=%s router=%s token=%s): %s",
            chain_id, router, token, exc,
        )
        return None


async def build_onchain_payment(intent) -> Optional[dict]:
    """Build the non-custodial on-chain payment instructions for an intent.

    Returns a dict (camelCase keys, matching the frontend Pay flow) or None if
    the chain/token/router isn't configured (caller renders a graceful fallback).

    The fee is read LIVE from the contract via quoteFee (single source of truth):
      fee = baseFee + (amount >= threshold ? surcharge : 0), capped at base+surcharge.
    `maxFee` is set to the quoted fee — the payer ceiling that makes pay() revert
    (FeeTooHigh) if the on-chain fee ever exceeds what was quoted. If the live
    quote fails (router not deployed / RPC down) we degrade: fee/total/maxFee and
    calldata are None and `feeUnavailable` is True, so the frontend reads quoteFee
    on-chain itself and passes maxFee = that value.
    """
    chain = intent.chain or "base"
    cid = chain_id_for(chain)
    router = router_address_for(chain)
    router_v2 = router_v2_address_for(chain)
    tok = token_for(chain, intent.currency)
    if cid is None or (router is None and router_v2 is None) or tok is None:
        return None

    token_addr, decimals = tok
    amount_base = to_base_units(intent.amount, decimals)
    # Stored id ALWAYS wins (it's what the /pay link advertised and what the
    # indexer matches); post-0015 every intent has one, so the derive fallback
    # only covers a row created before this code ran its migration.
    invoice_id = intent.onchain_invoice_id or derive_invoice_id(intent.reference_id, cid)
    merchant = (intent.recipient or "").lower()
    is_native = token_addr == ZERO_ADDRESS
    function = "payNative" if is_native else "pay"

    # STATIC permit policy from the registry — eip2612 → permit flow, else approve+pay.
    # The frontend reads these; no runtime "does this token support permit" introspection.
    pol = fee_policy_for(chain, intent.currency) or {}

    # ── SPLIT intent → RSendsSplitRouter instructions (fee-less) ──
    split_legs = loaded_split_recipients(intent)
    if split_legs:
        split_router = split_router_address_for(chain)
        if split_router is None:
            return None  # split router not configured → graceful fallback

        legs = sorted(split_legs, key=lambda leg: leg.position)
        recipients = [leg.address.lower() for leg in legs]
        shares = [leg.share_bps for leg in legs]
        from app.services.split_math import compute_split_amounts
        amounts = compute_split_amounts(amount_base, shares)

        calldata = (
            build_pay_split_native_calldata(invoice_id, amount_base, recipients, shares)
            if is_native
            else build_pay_split_calldata(
                invoice_id, token_addr, amount_base, recipients, shares
            )
        )
        return {
            "invoiceId": invoice_id,
            "merchant": "",  # no single payee — the split IS the recipient set
            "token": token_addr,
            "amount": str(amount_base),
            "chainId": cid,
            "router": split_router,
            "function": "paySplitNative" if is_native else "paySplit",
            "decimals": decimals,
            "isNative": is_native,
            "permitType": pol.get("permitType", "none"),
            "permitVersion": pol.get("permitVersion"),
            # RSendsSplitRouter takes NO fee (subscription monetization) —
            # the payer parts with exactly the amount.
            "fee": "0",
            "total": str(amount_base),
            "maxFee": None,
            "calldata": calldata,
            "payWithPermitCalldata": None,  # permit variant built client-side via ABI
            "feeUnavailable": False,
            "split": {
                "router": split_router,
                "recipients": recipients,
                "sharesBps": shares,
                "amounts": [str(a) for a in amounts],
            },
        }

    # ── RSendsRouterV2 (fee-less, ownerless) — v2 wins when both configured ──
    # No quoteFee exists on v2 and no fee leg exists in the flow: fee is a
    # literal "0", total == amount, maxFee has no meaning (None), and the
    # calldata carries no fee word. feeUnavailable can never be True here.
    if router_v2 is not None:
        if is_native:
            calldata = build_pay_native_calldata_v2(invoice_id, merchant, amount_base)
            permit_calldata = None  # native has no permit path
        else:
            calldata = build_pay_calldata_v2(invoice_id, merchant, token_addr, amount_base)
            permit_calldata = build_pay_with_permit_calldata_v2(
                invoice_id, merchant, token_addr, amount_base
            )
        return {
            "invoiceId": invoice_id,
            "merchant": merchant,
            "token": token_addr,
            "amount": str(amount_base),
            "chainId": cid,
            "router": router_v2,
            "routerVersion": 2,
            "function": function,
            "decimals": decimals,
            "isNative": is_native,
            "permitType": pol.get("permitType", "none"),
            "permitVersion": pol.get("permitVersion"),
            "fee": "0",
            "total": str(amount_base),
            "maxFee": None,
            "calldata": calldata,
            "payWithPermitCalldata": permit_calldata,
            "feeUnavailable": False,
        }

    out = {
        "invoiceId": invoice_id,
        "merchant": merchant,
        "token": token_addr,
        "amount": str(amount_base),
        "chainId": cid,
        "router": router,
        "routerVersion": 1,
        "function": function,
        "decimals": decimals,
        "isNative": is_native,
        "permitType": pol.get("permitType", "none"),
        "permitVersion": pol.get("permitVersion"),
    }

    # Live, authoritative fee straight from the contract.
    fee = await quote_fee_onchain(cid, router, token_addr, amount_base)
    if fee is None:
        out.update(
            fee=None, total=None, maxFee=None,
            calldata=None, payWithPermitCalldata=None, feeUnavailable=True,
        )
        return out

    max_fee = fee  # payer ceiling == quoted fee
    if is_native:
        calldata = build_pay_native_calldata(invoice_id, merchant, amount_base, max_fee)
        permit_calldata = None  # native has no permit path
    else:
        calldata = build_pay_calldata(invoice_id, merchant, token_addr, amount_base, max_fee)
        permit_calldata = build_pay_with_permit_calldata(
            invoice_id, merchant, token_addr, amount_base, max_fee
        )

    out.update(
        fee=str(fee),
        total=str(amount_base + fee),
        maxFee=str(max_fee),
        calldata=calldata,
        payWithPermitCalldata=permit_calldata,
        feeUnavailable=False,
    )
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  On-chain token metadata + startup guard (defense-in-depth)
#
#  The PRIMARY address-safety backstop is the deploy script
#  (SetFeeConfig.verifyAndSet), which refuses to enable a token whose on-chain
#  symbol()/decimals() don't match the registry. This boot-time guard re-checks
#  the SAME identity pair for enabled tokens and distinguishes:
#    - metadata MISMATCH  → real danger → SystemExit (panic startup)
#    - RPC UNREACHABLE     → transient   → bounded retry/backoff then continue
#                                          (never crash-loop on a flaky RPC)
#  name() is intentionally not asserted (no canonical registry field; symbol +
#  decimals are the identity gate, matching the deploy script).
# ═══════════════════════════════════════════════════════════════════════════

class TokenMetadataMismatch(RuntimeError):
    """An enabled token's on-chain metadata does not match the registry (real danger)."""


def _decode_abi_string(result_hex: str) -> Optional[str]:
    """Decode an ABI-encoded `string` return (or a bytes32-style fallback)."""
    try:
        data = bytes.fromhex(result_hex[2:] if result_hex.startswith("0x") else result_hex)
    except ValueError:
        return None
    if len(data) >= 64:
        offset = int.from_bytes(data[0:32], "big")
        if offset + 32 <= len(data):
            length = int.from_bytes(data[offset:offset + 32], "big")
            raw = data[offset + 32:offset + 32 + length]
            if len(raw) == length:
                return raw.decode("utf-8", "replace")
    # bytes32-style symbol/name (legacy tokens): trailing-zero padded.
    return data.rstrip(b"\x00").decode("utf-8", "replace") or None


class _EmptyResult:
    """Sentinel: the node ANSWERED, and the answer carried no data (`"0x"`).

    This is structurally distinct from a transport failure, which RAISES. The
    two must never collapse into a shared `None` again — that collapse is what
    let a token address with no code on the chain (the cross-chain-address
    failure this guard exists to catch) be logged as `verified`: `_eth_call`
    returned `None`, and both mismatch branches in `_verify_one_token` were
    guarded by `is not None`.

    No `__bool__`, on purpose: callers must test `is EMPTY_RESULT`. A falsy
    sentinel would be re-absorbed by the next `if not result` someone writes.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "<eth_call: empty>"


EMPTY_RESULT = _EmptyResult()


async def _eth_call_outcome(chain_id: int, to: str, data: str):
    """One `eth_call`, with the two outcomes kept apart at the transport layer.

    Returns the hex payload, or `EMPTY_RESULT` when the node answered with no
    data. **Raises** on transport failure. Never returns `None`.
    """
    from app.services.rpc_manager import get_rpc_manager

    rpc = get_rpc_manager(chain_id)
    result = await rpc.call("eth_call", [{"to": to, "data": data}, "latest"])
    if not result or result == "0x":
        return EMPTY_RESULT
    return result


async def _eth_call(chain_id: int, to: str, data: str) -> Optional[str]:
    """Back-compat shim over `_eth_call_outcome`: empty → `None`.

    Kept because `token_decimals_onchain`/`token_symbol_onchain` are part of
    `scripts/verify_onchain_registry.py`'s interface. New callers that need to
    tell empty from unreachable must use `_eth_call_outcome`.
    """
    res = await _eth_call_outcome(chain_id, to, data)
    return None if res is EMPTY_RESULT else res


async def token_decimals_outcome(chain_id: int, token: str):
    """ERC20 `decimals()`. Returns an int, or `EMPTY_RESULT`. Raises on RPC error."""
    res = await _eth_call_outcome(chain_id, token, "0x" + _selector("decimals()").hex())
    return EMPTY_RESULT if res is EMPTY_RESULT else int(res, 16)


async def token_symbol_outcome(chain_id: int, token: str):
    """ERC20 `symbol()`. Returns a str (or None if undecodable), or `EMPTY_RESULT`."""
    res = await _eth_call_outcome(chain_id, token, "0x" + _selector("symbol()").hex())
    return EMPTY_RESULT if res is EMPTY_RESULT else _decode_abi_string(res)


async def token_decimals_onchain(chain_id: int, token: str) -> Optional[int]:
    """ERC20 decimals() via eth_call. Raises on RPC error (transient); None if empty."""
    res = await token_decimals_outcome(chain_id, token)
    return None if res is EMPTY_RESULT else res


async def token_symbol_onchain(chain_id: int, token: str) -> Optional[str]:
    """ERC20 symbol() via eth_call. Raises on RPC error (transient)."""
    res = await token_symbol_outcome(chain_id, token)
    return None if res is EMPTY_RESULT else res


# Gap between the two rounds of the empty-answer confirmation when only one
# provider could be reached. A module constant on purpose: it is a physical
# property of "wait for a rate-limit window to move", not a deployment choice,
# and the confirmation must have no configuration surface at all.
_EMPTY_RECHECK_DELAY = 3.0


async def _poll_empty_once(chain_id: int, probe_token: str) -> tuple[Optional[bool], int]:
    """One confirmation round. Returns `(verdict, providers_that_answered)`.

    Verdict is True when every provider that ANSWERED said empty, False when at
    least one returned data, None when nobody answered. A provider that errored
    is not a vote — it neither confirms nor refutes.
    """
    from app.services.rpc_manager import get_rpc_manager

    data = "0x" + _selector("decimals()").hex()
    answers = await get_rpc_manager(chain_id).poll_providers(
        "eth_call", [{"to": probe_token, "data": data}, "latest"]
    )
    replied = [(name, res) for name, res in answers if not isinstance(res, Exception)]
    if not replied:
        return None, 0
    return all((not res or res == "0x") for _, res in replied), len(replied)


async def _chain_answers_empty_unanimously(
    chain_id: int, *, probe_token: str
) -> Optional[bool]:
    """Does THIS CHAIN's whole provider set answer `decimals()` with no data?

    The subject is the chain. `probe_token` is only the address the question is
    asked with — the caller picks it (the first token that came back empty), and
    the answer is about the providers, not about that token.

    Ask EVERY configured provider for `decimals()` and report agreement.

    A degraded or rate-limited provider can answer `{"result": "0x"}` instead of
    an error. One such provider must not be able to panic the process into a
    boot loop, so an empty answer is confirmed across the whole provider set
    before it is believed.

    **When fewer than two providers answered, provider separation is not
    available** — Base Sepolia ships a single default provider, so "unanimous"
    would mean one vendor and the confirmation would buy nothing. In that case
    substitute *time* separation: wait, ask again, and believe empty only if
    both rounds agree. A degraded provider is transient; an address with no
    contract code is permanent. That difference is the only signal left when
    there is nobody to cross-check against.

    Only a True verdict is re-checked, because only True can end in SystemExit.
    False and None already continue, so a second round could not change what
    happens and would just delay a boot that is already degrading.

    Returns:
        True  — empty, confirmed across providers or across time → registry mismatch.
        False — at least one answer carried data → provider fault.
        None  — nobody answered → transport, handled as unreachable.
    """
    verdict, answered = await _poll_empty_once(chain_id, probe_token)
    if verdict is not True or answered >= 2:
        return verdict

    logger.warning(
        "[registry-guard] chain %d: decimals() for %s came back EMPTY and only "
        "%d provider(s) answered — too few to cross-check. Re-asking in %.0fs "
        "before treating it as a registry error.",
        chain_id, probe_token, answered, _EMPTY_RECHECK_DELAY,
    )
    await asyncio.sleep(_EMPTY_RECHECK_DELAY)

    second, _ = await _poll_empty_once(chain_id, probe_token)
    if second is True:
        return True
    # The two rounds disagree (or the second could not be taken): a permanent
    # absence of code does not answer differently three seconds later.
    return second


async def verify_enabled_tokens_onchain(*, retries: int = 3, backoff: float = 2.0) -> None:
    """Boot guard: for each enabled, non-native token on a chain that has a
    configured router, assert on-chain symbol()/decimals() match the registry.

    Mismatch → SystemExit (panic). RPC unreachable → retry with backoff, then log
    and continue (do NOT crash-loop). No-op when no router addresses are configured
    (dev/test) — the deploy-script gate remains the primary backstop.
    """
    settings = get_settings()
    routers = getattr(settings, "rsends_router_addresses", {}) or {}
    routers_v2 = getattr(settings, "rsends_router_v2_addresses", {}) or {}
    # The identity guard (symbol/decimals) is fee-independent — it must also
    # cover v2-only chains, so gate on the UNION of the two maps.
    all_router_chains = set(map(str, routers)) | set(map(str, routers_v2))
    if not all_router_chains:
        logger.info("[registry-guard] no router addresses configured — skipping on-chain token verification")
        return

    for name, syms in FEE_POLICY.items():
        cid = CHAIN_IDS.get(name)
        if cid is None or str(cid) not in all_router_chains:
            continue  # no router deployed for this chain → nothing to verify
        await _verify_chain_tokens(cid, syms, retries, backoff)


async def _verify_chain_tokens(
    chain_id: int, syms: dict, retries: int, backoff: float
) -> None:
    """Verify one chain's enabled tokens, and resolve an empty answer ONCE.

    Whether the provider set is answering coherently is a property of the
    CHAIN, not of a token: a degraded provider returns empty for every token in
    the registry, so asking per token multiplied one 3s wait by the registry
    size (measured: 5 tokens = 15.05s of pure sleep, 45.04s with the
    unreachable backoff on top).

    The cross-check therefore has exactly ONE call site, and that call site is
    immediately followed by `return` — the loop cannot reach it a second time
    for the same chain. The guarantee is the control flow, not a counter or a
    per-chain memo: deleting the `return` is a visible structural change, where
    dropping a memo lookup is a silently missing condition.
    """
    for sym, pol in syms.items():
        if pol["native"] or not pol["enabled"]:
            continue
        if await _verify_one_token(chain_id, sym, pol, retries, backoff):
            # This token's decimals() came back empty. That is a question about
            # the chain's providers — decide it here, once, and stop verifying
            # this chain either way: a provider set that just answered
            # incoherently cannot verify the rest of the registry, and in the
            # unanimous case the process is exiting anyway.
            await _resolve_empty_chain(chain_id, sym, pol["address"])
            return


async def _resolve_empty_chain(chain_id: int, sym: str, addr: str) -> None:
    """Decide what an empty `decimals()` means for this chain. Called once.

    Unanimous empty → the registry has the address filed under the wrong chain,
    and there is no reading of that which is safe to boot past. Anything else is
    a degraded or rate-limited endpoint: say so loudly and let the boot proceed.
    """
    unanimous = await _chain_answers_empty_unanimously(chain_id, probe_token=addr)
    if unanimous is True:
        raise SystemExit(
            f"[registry-guard] FATAL no contract code for enabled token "
            f"{sym} ({addr}) on chain {chain_id}: every provider answered "
            f"decimals() with empty data. The registry has this address "
            f"filed under the wrong chain — refusing to start"
        )
    logger.warning(
        "[registry-guard] PROVIDER FAULT on chain %d: decimals() for %s "
        "(%s) came back EMPTY from one provider but not from the others "
        "(%s) — this is a degraded/rate-limited endpoint, not a registry "
        "error. Continuing; the rest of this chain's tokens are not verified "
        "against it — re-check the provider list.",
        chain_id, sym, addr,
        "no provider answered" if unanimous is None else "providers disagree",
    )


async def _verify_one_token(
    chain_id: int, sym: str, pol: dict, retries: int, backoff: float
) -> bool:
    """Verify one token. Returns True iff its `decimals()` came back EMPTY.

    It reports that fact; it does not act on it. Acting on it requires asking a
    question about the whole provider set, which belongs to the chain level —
    see `_verify_chain_tokens`. A real metadata mismatch and an unreachable RPC
    are genuinely per-token facts and are still resolved here.
    """
    addr = pol["address"]
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            onchain_decimals = await token_decimals_outcome(chain_id, addr)
            onchain_symbol = await token_symbol_outcome(chain_id, addr)
        except Exception as exc:  # transient RPC/network error
            last_exc = exc
            if attempt < retries - 1:
                await asyncio.sleep(backoff * (2 ** attempt))
            continue

        # The call SUCCEEDED and came back empty: there is no code at this
        # address on this chain. Report it and stop — what it MEANS depends on
        # whether the other providers agree, which is a chain-level question.
        if onchain_decimals is EMPTY_RESULT:
            return True

        # `symbol()` answering nothing while `decimals()` answered proves there
        # IS code at the address — a legacy bytes32 symbol that decodes to
        # empty. That keeps today's tolerance; the wrong-chain signal is
        # `decimals()` coming back empty, handled above.
        mismatches = []
        if onchain_decimals != pol["decimals"]:
            mismatches.append(f"decimals on-chain={onchain_decimals} registry={pol['decimals']}")
        if onchain_symbol is not EMPTY_RESULT and onchain_symbol is not None \
                and onchain_symbol != sym:
            mismatches.append(f"symbol on-chain={onchain_symbol!r} registry={sym!r}")
        if mismatches:
            raise SystemExit(
                f"[registry-guard] FATAL token metadata mismatch for {sym} "
                f"({addr}) on chain {chain_id}: {'; '.join(mismatches)} — refusing to start"
            )
        logger.info("[registry-guard] verified %s (%s) on chain %d", sym, addr, chain_id)
        return False

    # Exhausted retries due to transient errors → degrade, do not crash.
    logger.warning(
        "[registry-guard] could not verify %s (%s) on chain %d after %d attempts "
        "(RPC unreachable: %s) — continuing; deploy-script gate is the primary backstop",
        sym, addr, chain_id, retries, last_exc,
    )
